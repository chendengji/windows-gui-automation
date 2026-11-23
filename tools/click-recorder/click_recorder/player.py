"""重放器 — 解析目标窗口 → 逐动作执行（点击/键入/按键/条件等待），支持循环、重试、参数替换。

思路参考 macro-recorder-plus platform/windows_input.py 的 ActionExecutor（auto_focus/窗口放置）
与 HeldInputTracker（组合键 press/release）；键盘重放用 pynput Controller（支持中文/特殊键），
鼠标用 pyautogui（坐标移动+点击）。

新增能力（录制采集真值 → 用户补参 → agent 升级 的运行时支撑）：
- pre_actions：一次性设置步骤，重放开始时执行一次（不随循环重复）
- loop_count：宏级循环（steps 整体重复）与步级循环（本步重复）
- retry：步级与宏级失败重试
- params + ${name} 占位替换；值为 "env:VAR" 时运行时取环境变量（密码不落盘）
- wait_for：条件等待（窗口出现/消失、图像模板），超时抛错 → 触发重试
- coordinate_mode="relative"：按当前窗口位置换算坐标，窗口可移动
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import traceback

import pyautogui

from . import windows
from .keys import name_to_keyboard_key
from .model import (BaseStep, ClickStep, KeyStep, Macro, WaitForStep, render)


# ---------------------------------------------------------------------------
# 界面提醒集成（screen-reminder）
#
# 在重放器内部 emit，而非要求调用方自行接入——player 是共享基础设施，
# 任何宏重放都免费获得状态提示。fire-and-forget：零输出零等待，缺失脚本时静默跳过，
# 绝不拖慢或阻断重放。
# ---------------------------------------------------------------------------
_REMINDER_SCRIPT = os.path.join(
    os.path.expanduser("~"), ".pi", "agent", "scripts", "screen_reminder.py"
)
_last_remind = [0.0]
_REMIND_THROTTLE = 0.5  # 秒，避免高频闪烁


def _remind(text: str, *, hold: bool = False, force: bool = False) -> None:
    """更新屏幕界面提醒（fire-and-forget，零输出零等待）。"""
    if not os.path.exists(_REMINDER_SCRIPT):
        return
    now = time.time()
    if not force and now - _last_remind[0] < _REMIND_THROTTLE:
        return
    _last_remind[0] = now
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        args = [sys.executable, _REMINDER_SCRIPT, "set", text]
        if hold:
            args.append("--hold")
        subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 步骤描述 / 参数渲染
# ---------------------------------------------------------------------------
def step_desc(step: BaseStep) -> str:
    if isinstance(step, ClickStep):
        if step.xf is not None and step.yf is not None:
            loc = f" 归一=({step.xf:.3f},{step.yf:.3f})"
        elif step.x_rel is not None:
            loc = f" 相对=({step.x_rel},{step.y_rel})"
        else:
            loc = ""
        return f"点击 '{(step.label or '(未命名)')}' @({step.x},{step.y}){loc} {step.button}"
    if isinstance(step, WaitForStep):
        return f"等待[{step.kind}] '{step.target}'（{step.timeout}s）"
    if step.type == "wait_for":
        return f"等待[{step.kind}] '{getattr(step, 'target', '')}'"
    if step.type == "key_type":
        return f"键入 '{render(step.text, _CTX.params)}'"
    return f"按键 {'+'.join(render(k, _CTX.params) for k in step.keys)}"


class _Ctx:
    """重放上下文：参数表 + 目标窗口当前句柄/矩形。"""
    def __init__(self, params: dict):
        self.params = params
        self.hwnd: int = 0
        self.rect: dict | None = None


_CTX = _Ctx({})


def _resolve_window(macro: Macro, ctx: _Ctx) -> bool:
    """解析目标窗口：先试记录的 hwnd，失效则按标题正则找。"""
    if macro.window.hwnd:
        try:
            import win32gui
            if win32gui.IsWindow(macro.window.hwnd):
                ctx.hwnd = macro.window.hwnd
                ctx.rect = windows.get_window_placement(ctx.hwnd)
                return True
        except Exception:
            pass
    if macro.window.title:
        found = windows.find_windows(re.escape(macro.window.title))
        if found:
            ctx.hwnd = found[0].hwnd
            ctx.rect = windows.get_window_placement(ctx.hwnd)
            return True
    return False


def _refresh_rect(ctx: _Ctx) -> None:
    if ctx.hwnd:
        ctx.rect = windows.get_window_placement(ctx.hwnd)


def _click_xy(step: ClickStep, macro: Macro, ctx: _Ctx) -> tuple[int, int]:
    """按 coordinate_mode 换算点击坐标。

    - normalized：当前窗口宽高的比例（跨显示器/分辨率/DPI 缩放适用）
    - relative：当前窗口左上角 + 相对像素偏移（窗口可移动）
    - exact：录制时的绝对坐标（窗口位置必须固定）
    """
    r = ctx.rect
    if macro.coordinate_mode == "normalized" and step.xf is not None and step.yf is not None:
        if r:
            w = max(1, int(r["right"]) - int(r["left"]))
            h = max(1, int(r["bottom"]) - int(r["top"]))
            return int(r["left"] + step.xf * w), int(r["top"] + step.yf * h)
    if macro.coordinate_mode == "relative" and step.x_rel is not None and step.y_rel is not None:
        if r:
            return int(r["left"] + step.x_rel), int(r["top"] + step.y_rel)
    return step.x, step.y


# ---------------------------------------------------------------------------
# 条件等待
# ---------------------------------------------------------------------------
def _find_by_title(pattern: str):
    return windows.find_windows(pattern)


def _wait_for(step: WaitForStep, dry_run: bool) -> None:
    if dry_run:
        return
    pattern = render(step.target, _CTX.params)
    deadline = time.time() + max(step.timeout, 0.1)
    while True:
        if step.kind in ("window", "window_gone"):
            hit = bool(_find_by_title(pattern))
            ok = hit if step.kind == "window" else not hit
            if ok:
                return
        elif step.kind == "image":
            try:
                if pyautogui.locateOnScreen(pattern, confidence=0.85):
                    return
            except Exception:
                pass
        else:  # text 等：暂无内置实现，退化为固定延时并告警
            print(f"  [提示] wait_for kind='{step.kind}' 暂无内置实现，按 timeout/2 延时。")
            time.sleep(max(step.timeout / 2, 0.1))
            return
        if time.time() >= deadline:
            raise TimeoutError(
                f"wait_for 超时（{step.timeout}s）：kind={step.kind} target='{pattern}'"
            )
        time.sleep(step.interval)


# ---------------------------------------------------------------------------
# 单步执行 / 重试
# ---------------------------------------------------------------------------
def _execute(step: BaseStep, macro: Macro, ctx: _Ctx, controller, dry_run: bool,
            speed: float) -> None:
    params = ctx.params
    if isinstance(step, WaitForStep) or step.type == "wait_for":
        _wait_for(step, dry_run)
        return

    if dry_run:
        return

    focus = step.auto_focus and ctx.hwnd
    if isinstance(step, ClickStep):
        if focus:
            windows.activate(ctx.hwnd)
        x, y = _click_xy(step, macro, ctx)
        try:
            pyautogui.moveTo(x, y, duration=0.06)
        except Exception:
            pass
        btn = step.button if step.button in ("left", "right", "middle") else "left"
        pyautogui.click(x, y, button=btn)
        return

    if step.type == "key_type":
        if focus:
            windows.activate(ctx.hwnd)
        controller.type(render(step.text, params))
        return

    # key_press：按组合键顺序 press/release
    if focus:
        windows.activate(ctx.hwnd)
    keys = [name_to_keyboard_key(render(k, params)) for k in step.keys]
    for k in keys:
        controller.press(k)
    time.sleep(0.03)
    for k in reversed(keys):
        controller.release(k)


def _run_step(step: BaseStep, macro: Macro, ctx: _Ctx, controller, dry_run: bool,
             speed: float) -> None:
    """带重试执行一步（含步级循环）。"""
    loops = max(1, step.loop_count)
    attempts = max(0, step.retry)
    for _ in range(loops):
        last_err: Exception | None = None
        for attempt in range(attempts + 1):
            try:
                _execute(step, macro, ctx, controller, dry_run, speed)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < attempts:
                    _remind(f"步骤失败，重试 {attempt + 1}/{attempts}")
                    time.sleep(0.3 * (attempt + 1))
        if last_err is not None:
            raise RuntimeError(f"步骤失败（已重试 {attempts} 次）：{last_err}") from last_err


def _print_step(i: int, total: int, step: BaseStep, dry_run: bool) -> str:
    """打印一步进度，并返回该步的短描述（供界面提醒复用）。"""
    detail = step_desc(step)
    suffix = " (dry-run)" if dry_run else ""
    loop = f" x{step.loop_count}" if step.loop_count > 1 else ""
    retry = f" retry={step.retry}" if step.retry else ""
    print(f"  [{i}/{total}] {detail}  delay={step.delay_before}s{loop}{retry}{suffix}")
    return detail


def replay(macro: Macro, *, dry_run: bool = False, speed: float = 1.0,
           params: dict | None = None) -> None:
    """重放宏。params 可覆盖/补充 macro.params（运行时注入）。"""
    _CTX.params = {**macro.params, **(params or {})}
    steps = macro.steps
    head = f"[重放] 宏 '{macro.name}' — 窗口 '{macro.window.title}' — {len(steps)} 步"
    if macro.loop_count > 1:
        head += f" ×循环{macro.loop_count}"
    if macro.retry:
        head += f" retry={macro.retry}"
    head += f"{' (dry-run)' if dry_run else ''}"
    print(head)
    if not steps:
        print("[重放] 宏为空，无事可做。")
        return

    if dry_run:
        # dry-run 为即时预览，不亮界面提醒（避免刷屏提示）
        for i, s in enumerate(macro.pre_actions, 1):
            print(f"  [预{i}/{len(macro.pre_actions)}] {_print_step(0,0,s,True)}  (pre_action)")
        for i, s in enumerate(steps, 1):
            _print_step(i, len(steps), s, True)
        print("[重放] (dry-run) 完成")
        return

    # 任务级保持显示：整个重放期间界面提醒常亮
    _remind(f"正在重放宏「{macro.name}」", hold=True, force=True)

    # 解析目标窗口（hwnd 失效则按标题重找）
    if not _resolve_window(macro, _CTX):
        print(f"[重放] 警告：未找到目标窗口 '{macro.window.title}'，将按绝对坐标执行。")

    from pynput import keyboard as pkb
    controller = pkb.Controller()

    macro_attempts = max(0, macro.retry)
    for mi in range(macro_attempts + 1):
        try:
            # 一次性设置步骤
            for i, s in enumerate(macro.pre_actions, 1):
                _remind(f"预置步骤 {i}/{len(macro.pre_actions)}")
                if s.delay_before > 0:
                    time.sleep(s.delay_before / max(speed, 0.1))
                _run_step(s, macro, _CTX, controller, False, speed)

            # 主循环
            for _ in range(max(1, macro.loop_count)):
                for i, s in enumerate(steps, 1):
                    detail = _print_step(i, len(steps), s, False)
                    _remind(detail)  # 逐步提示当前动作（节流，fire-and-forget）
                    if s.delay_before > 0:
                        time.sleep(s.delay_before / max(speed, 0.1))
                    _refresh_rect(_CTX)   # 每步刷新窗口位置（relative 模式需要）
                    _run_step(s, macro, _CTX, controller, False, speed)
            break  # 成功，退出重试
        except Exception as e:
            if mi < macro_attempts:
                print(f"[重放] 第 {mi + 1} 次整体失败：{e} — 重试 "
                      f"{mi + 1}/{macro_attempts}")
                _remind(f"整体失败，重试 {mi + 1}/{macro_attempts}")
                traceback.print_exc()
                time.sleep(0.5)
                continue
            print(f"[重放] 失败：{e}")
            traceback.print_exc()
            _remind(f"重放失败「{macro.name}」", hold=True, force=True)
            raise

    print("[重放] 完成")
    _remind(f"重放完成「{macro.name}」", hold=True, force=True)