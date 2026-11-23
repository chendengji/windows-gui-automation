"""CLI 入口 — click-recorder record / list / show / play / search / upgrade / rebase。

脚本库布局（统一命名与格式，脚本不会用了就丢）：

    ~/.pi/gui-macros/
    ├── index.json                     # 脚本登记表：agent 据此"找出存储的脚本"
    └── <软件slug>/
        ├── <场景slug>.json            # 宏：真值动作 + 人工叙述 + 参数
        └── <场景slug>.py              # 固化脚本（upgrade 生成）

key = "<软件>/<场景>"，例：WPS/导出pdf。

用法示例：
    python -m click_recorder.cli record --name 登录 --software 示例软件 --scene 登录
    python -m click_recorder.cli list
    python -m click_recorder.cli search 导出
    python -m click_recorder.cli show 示例软件/登录
    python -m click_recorder.cli play 示例软件/登录 --dry-run
    python -m click_recorder.cli play 示例软件/登录 --param user=bob
    python -m click_recorder.cli upgrade 示例软件/登录
    python -m click_recorder.cli rebase 示例软件/登录          # exact → normalized（跨显示器）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from . import windows
from .model import Macro, WaitForStep
from .recorder import ClickRecorder
from .player import replay


# click-recorder 项目根（upgrade 生成的脚本需要它做 sys.path）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 脚本库：统一目录、统一命名、登记表
# ---------------------------------------------------------------------------
def lib_dir() -> str:
    """脚本库根目录（所有形成的宏与固化脚本都落这里，不散落各处）。"""
    d = os.path.join(os.path.expanduser("~"), ".pi", "gui-macros")
    os.makedirs(d, exist_ok=True)
    return d


def index_path() -> str:
    return os.path.join(lib_dir(), "index.json")


def load_index() -> dict:
    p = index_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {"version": 1, "entries": {}}


def save_index(idx: dict) -> None:
    with open(index_path(), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", name or "macro").strip("_") or "macro"


def key_from(software: str, scene: str) -> str:
    return f"{_safe_name(software)}/{_safe_name(scene)}"


def key_dir(key: str) -> str:
    d = os.path.join(lib_dir(), *_safe_key(key))
    os.makedirs(d, exist_ok=True)
    return d


def _safe_key(key: str) -> list[str]:
    parts = [p for p in (key or "").split("/") if p]
    return [_safe_name(p) for p in parts] or ["_root"]


def macro_json_path(key: str) -> str:
    return os.path.join(key_dir(key), _safe_name(key.split("/")[-1]) + ".json")


def macro_script_path(key: str) -> str:
    return os.path.join(key_dir(key), _safe_name(key.split("/")[-1]) + ".py")


def _resolve_key(name: str) -> str:
    """接受 '软件/场景' 或裸场景名（自动匹配已登记的条目）。"""
    if "/" in name:
        return key_from(name.split("/")[0], name.split("/")[-1])
    idx = load_index()
    for k in idx.get("entries", {}):
        if k.split("/")[-1] == _safe_name(name) or k.endswith("/" + name):
            return k
    return key_from("未归类", name)


def register(macro: Macro, key: str, *, script: str | None = None) -> None:
    """把宏与固化脚本登记进 index.json（agent 靠它检索脚本库）。"""
    idx = load_index()
    steps = macro.steps
    click_xy = next((s for s in steps if s.type == "x_click"), None)
    entry = {
        "software": key.split("/")[0],
        "scene": key.split("/")[-1],
        "window_title": macro.window.title,
        "window_class": macro.window.class_name,
        "coordinate_mode": macro.coordinate_mode,
        "display": macro.display,
        "flow_note": macro.flow_note,
        "params": sorted(macro.params),
        "steps": len(steps),
        "loop_count": macro.loop_count,
        "retry": macro.retry,
        "has_relative": bool(click_xy and click_xy.x_rel is not None),
        "has_normalized": bool(click_xy and click_xy.xf is not None),
        "json": macro_json_path(key),
        "script": script,
        "created": entry0_created(macro, idx, key),
        "updated": round(time.time(), 3),
    }
    idx.setdefault("entries", {})[key] = entry
    save_index(idx)


def entry0_created(macro: Macro, idx: dict, key: str) -> float:
    prev = (idx.get("entries", {}) or {}).get(key, {})
    return float(prev.get("created", macro.created) or macro.created)


def _load(key: str) -> Macro:
    p = macro_json_path(key)
    if not os.path.exists(p):
        print(f"[错误] 未找到宏 '{key}'（{p}）。用 list 或 search 查看脚本库。", file=sys.stderr)
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return Macro.from_dict(json.load(f))


def _save(macro: Macro, key: str, *, script: str | None = None) -> None:
    p = macro_json_path(key)
    with open(p, "w", encoding="utf-8") as f:
        f.write(macro.to_json())
    register(macro, key, script=script)
    return p


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------
def _ask_params() -> dict:
    """录制前声明参数：每个参数名对应 ${name} 占位；值形如 env:VAR 时运行时取环境变量（密码不落盘）。"""
    print("[录制] 声明本次宏需要的参数（格式 参数名=值或env:环境变量名；回车结束）。")
    print("[录制] 例：username=${username} 的源值，password=env:MY_LOGIN_PWD（推荐，不落盘）")
    params: dict = {}
    while True:
        try:
            line = input("  参数 (回车结束): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        if "=" not in line:
            print("    (跳过：需要 名=值 格式)")
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            params[k] = v
            print(f"    ✔ 参数 {k}={('***' if v.startswith('env:') else v)}")
    return params


def cmd_record(args) -> None:
    import pyautogui
    pyautogui.FAILSAFE = False  # 录制时禁用左上角安全熔断

    if args.window:
        cands = windows.find_windows(args.window)
        if not cands:
            print(f"[错误] 按标题 '{args.window}' 未找到可见窗口。", file=sys.stderr)
            sys.exit(1)
        print("找到窗口：")
        for i, w in enumerate(cands[:10], 1):
            print(f"  {i}. '{w.title}'  hwnd={w.hwnd}  class={w.class_name}")
        sel = input("选择序号（回车=第一个）: ").strip()
        target = cands[int(sel) - 1] if sel.isdigit() and 0 < int(sel) <= len(cands[:10]) else cands[0]
    else:
        target = windows.get_foreground()
        if not target:
            print("[错误] 无法获取前台窗口。请先激活目标软件窗口，或用 --window 指定。", file=sys.stderr)
            sys.exit(1)
        print(f"[信息] 目标窗口 = 当前前台窗口 '{target.title}' (hwnd={target.hwnd})")
        if input("确认？(回车确认 / 输入 n 改用 --window 指定) ").strip().lower() in ("n", "no"):
            sys.exit(0)

    # 统一命名：软件名 + 场景名
    software = args.software or _ask("软件名（如 WPS / 示例软件）", target.title)
    scene = args.scene or _ask("场景名（如 登录 / 导出pdf）", args.name or "任务1")
    key = key_from(software, scene)

    params = _ask_params()
    rec = ClickRecorder(target, macro_name=scene)
    rec.params = params
    macro = rec.run()

    if not macro.steps:
        print("[录制] 未记录任何点击，未保存。")
        sys.exit(0)

    path = _save(macro, key)
    print(f"\n[录制] 已保存 {len(macro.steps)} 步 → {path}")
    print(f"[录制] 库内 key = {key}   坐标模式 = {macro.coordinate_mode}"
          + ("（跨显示器/分辨率适用）" if macro.coordinate_mode == "normalized" else ""))
    if macro.flow_note:
        print(f"[叙述] 已记录流程线路与逻辑（{len(macro.flow_note.splitlines())} 行）。")
    else:
        print("[叙述] 未填写流程叙述；建议补上（它是 agent 固化脚本的依据）。")
    if params:
        print(f"[录制] 已声明参数：{', '.join(params)}")
    print(f"[录制] 下一步：`click-recorder upgrade {key}` 生成固化脚本；"
          f"`click-recorder show {key}` 查看。")


def _ask(prompt: str, default: str) -> str:
    try:
        v = input(f"{prompt}（默认 {default}）: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return v or default


# ---------------------------------------------------------------------------
# list / search / show
# ---------------------------------------------------------------------------
def cmd_list(args) -> None:
    idx = load_index()
    entries = idx.get("entries", {}) or {}
    if not entries:
        print("(空) 脚本库还没有条目。用 `click-recorder record` 录制。")
        return
    print(f"脚本库：{lib_dir()}   （{len(entries)} 条）")
    for k, e in sorted(entries.items()):
        mode = e.get("coordinate_mode", "?")
        note = (e.get("flow_note") or "").replace("\n", " ")
        note = (note[:40] + "…") if len(note) > 40 else (note or "(无叙述)")
        print(f"  {k:<32} {e.get('steps', 0):>3} 步  {mode:<10} "
              f"窗口='{(e.get('window_title') or '')[:18]}'  {note}")


def cmd_search(args) -> None:
    """按关键词在脚本库里检索（软件名/场景/窗口标题/流程叙述/参数），供 agent 找出既有脚本。"""
    q = (args.query or "").strip()
    if not q:
        print("[错误] 需要关键词。", file=sys.stderr)
        sys.exit(1)
    idx = load_index()
    hits = []
    for k, e in (idx.get("entries", {}) or {}).items():
        blob = " ".join(str(x) for x in [
            k, e.get("software", ""), e.get("scene", ""), e.get("window_title", ""),
            e.get("window_class", ""), e.get("flow_note", ""),
            " ".join(e.get("params", [])), e.get("coordinate_mode", ""),
        ])
        if q.lower() in blob.lower():
            hits.append((k, e))
    if not hits:
        print(f"(无命中) 关键词 '{q}' 不在脚本库中。用 list 查看全部条目。")
        return
    print(f"命中 {len(hits)} 条：")
    for k, e in hits:
        print(f"  {k}  模式={e.get('coordinate_mode')}  窗口='{e.get('window_title')}'  "
              f"步={e.get('steps')}  参数={e.get('params')}")
        if e.get("flow_note"):
            for ln in e["flow_note"].splitlines()[:3]:
                print(f"      · {ln}")
    print("\n用 `click-recorder play <key>` 重放；`upgrade <key>` 生成固化脚本。")


def _show_step(s) -> str:
    if s.type == "x_click":
        if s.xf is not None and s.yf is not None:
            loc = f" 归一=({s.xf:.3f},{s.yf:.3f})"
        elif s.x_rel is not None:
            loc = f" 相对=({s.x_rel},{s.y_rel})"
        else:
            loc = ""
        return f"点击 '{(s.label or '(未命名)')}' @({s.x},{s.y}){loc} {s.button}"
    if s.type == "key_type":
        return f"键入 '{s.text}'"
    if s.type == "wait_for":
        return f"等待[{s.kind}] '{s.target}' ({s.timeout}s)"
    return f"按键 {'+'.join(s.keys)}"


def cmd_show(args) -> None:
    key = _resolve_key(args.name)
    m = _load(key)
    print(f"key: {key}")
    print(f"宏: '{m.name}'  窗口: '{m.window.title}' (hwnd={m.window.hwnd})  模式={m.coordinate_mode}  "
          f"{len(m.steps)} 步")
    if m.params:
        shown = {k: ('***' if str(v).startswith('env:') else v) for k, v in m.params.items()}
        print(f"参数: {shown}")
    if m.loop_count > 1 or m.retry:
        print(f"循环={m.loop_count}  整体重试={m.retry}")
    if m.flow_note:
        print("流程线路与逻辑（人工叙述）：")
        for ln in m.flow_note.splitlines():
            print(f"    · {ln}")
    if m.display and m.display.get("window_rect"):
        r = m.display["window_rect"]
        print(f"录制时窗口矩形: {r}  （跨显示器可用 rebase 改造坐标）")
    for i, s in enumerate(m.pre_actions, 1):
        print(f"  [预{i}/{len(m.pre_actions)}] {_show_step(s)}  delay={s.delay_before}s")
    for i, s in enumerate(m.steps, 1):
        extra = ""
        if s.loop_count > 1:
            extra += f"  x{s.loop_count}"
        if s.retry:
            extra += f"  retry={s.retry}"
        note = f"  注：{s.note}" if s.note else ""
        print(f"  [{i:>2}] {_show_step(s)}  delay={s.delay_before}s  auto_focus={s.auto_focus}{extra}{note}")


# ---------------------------------------------------------------------------
# play / upgrade / rebase
# ---------------------------------------------------------------------------
def cmd_play(args) -> None:
    key = _resolve_key(args.name)
    m = _load(key)
    params = {}
    for kv in (args.param or []):
        if "=" not in kv:
            print(f"[错误] --param 需要 名=值 格式：{kv}", file=sys.stderr)
            sys.exit(1)
        k, v = kv.split("=", 1)
        params[k.strip()] = v.strip()
    print(f"[play] key={key}  模式={m.coordinate_mode}")
    replay(m, dry_run=args.dry_run, speed=args.speed, params=params or None)


def cmd_upgrade(args) -> None:
    """从宏 JSON + 人工叙述生成参数化 Python 编排脚本（固化入库，不散落）。"""
    key = _resolve_key(args.name)
    m = _load(key)
    out = args.output or macro_script_path(key)
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_upgrade_template(m, key, out))
    register(m, key, script=out)
    print(f"[升级] 已生成 {out}")
    print("[升级] 循环/重试/参数替换/条件等待/坐标换算由 player 运行时承担，不要在此重复实现。")
    print("[升级] 请在 ★ agent 升级点 处补：条件分支、数据源、失败判定（依据宏里的流程叙述）。")


def cmd_rebase(args) -> None:
    """坐标改造：把 exact 模式旧宏改造成 normalized（跨显示器/分辨率/DPI 缩放适用）。

    原理：用录制时的窗口矩形（或 --from 指定）把绝对坐标换算成窗口客户区比例坐标，
    此后重放按**当前**窗口尺寸换算 —— 换显示器、改分辨率、改 DPI 都不用再管。
    """
    key = _resolve_key(args.name)
    m = _load(key)
    if m.coordinate_mode == "normalized":
        print(f"[rebase] 已是 normalized 模式，无需改造。")
        return

    old = args.from_rect or (m.display or {}).get("window_rect")
    if not old:
        # 尝试按标题取当前窗口矩形
        found = windows.find_windows(re.escape(m.window.title))
        if found:
            old = windows.get_window_placement(found[0].hwnd)
    if not old:
        print("[错误] 无录制时窗口矩形，请用 --from \"left,top,right,bottom\" 指定。", file=sys.stderr)
        sys.exit(1)

    w = max(1, int(old["right"]) - int(old["left"]))
    h = max(1, int(old["bottom"]) - int(old["top"]))
    changed = 0
    for s in list(m.pre_actions) + list(m.steps):
        if s.type != "x_click":
            continue
        xr = s.x - int(old["left"])
        yr = s.y - int(old["top"])
        s.x_rel, s.y_rel = xr, yr
        s.xf, s.yf = round(xr / w, 6), round(yr / h, 6)
        changed += 1
    if not changed:
        print("[rebase] 该宏无点击步骤，无需改造。")
        return
    m.coordinate_mode = "normalized"
    _save(m, key, script=macro_script_path(key) if os.path.exists(macro_script_path(key)) else None)
    print(f"[rebase] 已改造 {changed} 个点击步骤 → normalized 模式（窗口矩形 {w}x{h}）")
    print(f"[rebase] 旧绝对坐标已保留在 x/y 字段备查。换显示器/分辨率可直接重放。")


def _upgrade_template(m: Macro, key: str, out: str) -> str:
    """生成编排脚本骨架。循环/步级重试/参数替换/条件等待由 player 运行时承担，不在此重复实现。"""
    lines = []
    for k, v in m.params.items():
        if str(v).startswith("env:"):
            env = str(v)[4:]
            lines.append(f'    "{k}": os.environ.get("{env}", ""),  # 敏感值走环境变量，不落盘')
        else:
            lines.append(f'    "{k}": {v!r},')
    params = "\n".join(lines) or "    # 无参数；需要时在录制前声明，或用 --param 运行时注入"

    pre = "\n".join(f"    # 预置 {i}: {_show_step(s)}"
                    for i, s in enumerate(m.pre_actions, 1)) or "    # (无预置步骤)"
    steps = "\n".join(
        f"    # {i:>2}: {_show_step(s)}"
        + (f"   x{s.loop_count}" if s.loop_count > 1 else "")
        + (f"   retry={s.retry}" if s.retry else "")
        + (f"   # {s.note}" if s.note else "")
        for i, s in enumerate(m.steps, 1)
    ) or "    # (无步骤)"

    flow = m.flow_note.replace("\n", "\n# ") or "# (未填写流程叙述——这是固化脚本的主要依据，建议补上)"

    return '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""自动生成 — 宏 '%(name)s' 的参数化编排脚本。

库内 key：%(key)s
来源：click-recorder upgrade（宏 JSON：%(macro_path)s）
窗口：'%(win)s'（%(cls)s）  坐标模式：%(mode)s

三段链路：录制采集真值（JSON）→ 人工叙述流程线路与逻辑 → agent 固化成此脚本入库。
循环/步级重试/参数替换/条件等待/坐标换算由 click_recorder.player 运行时承担，不要在此重复实现。

==== 流程线路与逻辑（人工叙述，固化脚本的主要依据）====
%(flow)s
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.environ.get("CLICK_RECORDER_HOME", r"%(project_dir)s"))   # click-recorder 项目根（可用环境变量覆盖）

from click_recorder.model import Macro
from click_recorder.player import replay


# ---- 参数（${name} 占位替换源）----
# 敏感值用 env: 前缀，运行时取环境变量，**不要硬编码密码**
PARAMS = {
%(params)s
}

MACRO_PATH = r"%(macro_path)s"


# ---- 一次性预置步骤（已在 JSON 的 pre_actions，运行时自动执行一次）----
%(pre)s


# ---- 主步骤清单（仅注释，便于升级时对照；实际执行由 player 从 JSON 读取）----
%(steps)s


def main():
    ap = argparse.ArgumentParser(description="重放宏 '%(name)s'")
    ap.add_argument("--dry-run", action="store_true", help="只打印步骤不实际点击")
    ap.add_argument("--speed", type=float, default=1.0, help="速度倍率")
    ap.add_argument("--param", action="append", default=[], metavar="K=V", help="运行时覆盖参数")
    ap.add_argument("--loop", type=int, default=%(loop)d, help="主循环次数")
    ap.add_argument("--retry", type=int, default=%(retry)d, help="整体重试次数")
    args = ap.parse_args()

    overrides = {}
    for kv in args.param:
        k, _, v = kv.partition("=")
        overrides[k] = v

    with open(MACRO_PATH, "r", encoding="utf-8") as f:
        macro = Macro.from_dict(json.load(f))
    macro.params = {**macro.params, **PARAMS, **overrides}
    if args.loop > 0:
        macro.loop_count = args.loop
    macro.retry = max(macro.retry, args.retry)

    # ★ agent 升级点：在此补条件分支 / 数据源 / 失败判定
    #   例：先读 CSV 得到参数填进 overrides；或在 pre_actions 前插入 wait_for；
    #       或失败后切换备用流程（改 macro 再 replay）。

    try:
        replay(macro, dry_run=args.dry_run, speed=args.speed, params=overrides or None)
    except Exception as e:
        print(f"[失败] {{e}}")
        sys.exit(2)


if __name__ == "__main__":
    main()
''' % {
        "name": m.name,
        "key": key,
        "macro_path": macro_json_path(key),
        "win": m.window.title,
        "cls": m.window.class_name,
        "mode": m.coordinate_mode,
        "project_dir": _PROJECT_DIR,
        "params": params,
        "pre": pre,
        "steps": steps,
        "flow": flow,
        "loop": max(1, m.loop_count),
        "retry": m.retry,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="click-recorder",
                                description="无元素树软件的鼠标点击录制/重放 + 脚本库管理（聚焦窗口+坐标+按钮名+叙述+固化）")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="录制点击宏（入库并登记）")
    r.add_argument("--name", help="兼容旧参数：默认场景名")
    r.add_argument("--software", help="软件名（如 WPS）")
    r.add_argument("--scene", help="场景名（如 导出pdf）")
    r.add_argument("--window", help="按标题正则指定目标窗口（不填则用当前前台窗口）")
    r.set_defaults(fn=cmd_record)

    l = sub.add_parser("list", help="列出脚本库全部条目")
    l.set_defaults(fn=cmd_list)

    s = sub.add_parser("search", help="按关键词检索脚本库（软件/场景/窗口/叙述/参数）")
    s.add_argument("query")
    s.set_defaults(fn=cmd_search)

    sh = sub.add_parser("show", help="查看宏步骤与流程叙述")
    sh.add_argument("name")
    sh.set_defaults(fn=cmd_show)

    pl = sub.add_parser("play", help="重放宏")
    pl.add_argument("name")
    pl.add_argument("--dry-run", action="store_true", help="只打印步骤不实际点击")
    pl.add_argument("--speed", type=float, default=1.0, help="速度倍率（默认1）")
    pl.add_argument("--param", action="append", metavar="K=V", help="运行时参数（可多次）")
    pl.set_defaults(fn=cmd_play)

    u = sub.add_parser("upgrade", help="生成参数化 Python 编排脚本（固化入库）")
    u.add_argument("name")
    u.add_argument("-o", "--output", help="输出脚本路径（默认入库到 <场景>.py）")
    u.set_defaults(fn=cmd_upgrade)

    rb = sub.add_parser("rebase", help="坐标改造：exact → normalized（跨显示器/分辨率）")
    rb.add_argument("name")
    rb.add_argument("--from", dest="from_rect",
                    help="旧窗口矩形 'left,top,right,bottom'（不填则取录制时矩形）")
    rb.set_defaults(fn=cmd_rebase)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()