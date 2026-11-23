"""录制器 — pynput 全局监听鼠标左键点击 + 键盘输入，逐点询问按钮名，F9/输入q 结束。

思路参考 macro-recorder-plus recorder/input_recorder.py（pynput 全局监听 + 事件队列）与
recorder/event_normalizer.py（键盘归一化）+ utilities/key_sequences.py（组合键排序）。

要点：
- 鼠标点击 → 记录为 x_click 步骤，随后【暂停监听】让用户输入按钮名（避免命名输入被录成键盘动作）。
- 键盘输入 → 归一化为 key_type(连续可打印字符文本) / key_press(组合键或特殊键)。
- F9 结束录制。
"""
from __future__ import annotations

import queue
import threading
import time

from pynput import keyboard, mouse

from . import windows
from .keys import MODIFIERS, SPECIAL_KEYS, keyboard_key_to_name, normalize_hotkey
from .model import ClickStep, KeyStep, Macro, WindowRef


class ClickRecorder:
    def __init__(self, window: WindowRef, macro_name: str = "macro"):
        self.window = window
        self.macro_name = macro_name
        self.steps: list = []
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._paused = threading.Event()   # True=正在输入按钮名，暂停录制
        self._mouse_listener = None
        self._kb_listener = None
        self._last_ts = 0.0
        # 参数脚手架：录制前声明的参数名，重放时以 ${name} 形式引用
        self.params: dict[str, str] = {}
        # 键盘归一化状态（回调线程内读写）
        self._mods: set[str] = set()
        self._text_buf: str = ""

    # ---------------- 键盘归一化（回调线程） ----------------
    def _flush_text(self, ts: float) -> None:
        if self._text_buf:
            self._q.put(("key", {"type": "key_type", "text": self._text_buf, "ts": ts}))
            self._text_buf = ""

    def _on_press(self, key):
        if self._stop.is_set():
            return
        name = keyboard_key_to_name(key)
        if name == "f9":                      # 结束热键（不记录）
            self._stop.set()
            return
        if self._paused.is_set():             # 输入按钮名期间不录制键盘
            return
        ts = time.time()
        if name in MODIFIERS:
            self._mods.add(name)
            return
        if self._mods:                        # 组合键（如 ctrl+c）
            self._flush_text(ts)
            self._q.put(("key", {"type": "key_press",
                                 "keys": normalize_hotkey(list(self._mods) + [name]), "ts": ts}))
            return
        if len(name) == 1 and name.isprintable():
            self._text_buf += name            # 普通可打印字符 → 累积文本
            return
        if name == "backspace":
            if self._text_buf:
                self._text_buf = self._text_buf[:-1]
            else:
                self._q.put(("key", {"type": "key_press", "keys": ["backspace"], "ts": ts}))
            return
        if name in SPECIAL_KEYS or (name.startswith("f") and name[1:].isdigit()):
            self._flush_text(ts)
            self._q.put(("key", {"type": "key_press", "keys": [name], "ts": ts}))
            return

    def _on_release(self, key):
        name = keyboard_key_to_name(key)
        if name in MODIFIERS:
            self._mods.discard(name)

    # ---------------- 鼠标回调（回调线程） ----------------
    def _on_click(self, x, y, button, pressed):
        if not pressed or str(button) != "Button.left":
            return
        if self._stop.is_set() or self._paused.is_set():
            return
        ts = time.time()
        self._flush_text(ts)
        self._q.put(("click", {"x": int(x), "y": int(y), "ts": ts}))

    # ---------------- 生命周期 ----------------
    def start_listeners(self):
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener.start()
        self._kb_listener.start()

    def stop_listeners(self):
        for l in (self._mouse_listener, self._kb_listener):
            try:
                if l:
                    l.stop()
            except Exception:
                pass

    # ---------------- 主流程 ----------------
    def run(self) -> Macro:
        self.start_listeners()
        self._last_ts = time.time()
        print(f"[录制] 目标窗口: '{self.window.title}'  hwnd={self.window.hwnd}  class={self.window.class_name}")
        print("[录制] 现在操作目标软件：左键点击 + 键盘输入都会被录制。")
        print("[录制] 每次左键点击后会暂停询问按钮名（回车跳过）；按 F9 或输入 q 结束。")
        try:
            while not self._stop.is_set():
                try:
                    kind, data = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._consume(kind, data)
        except KeyboardInterrupt:
            self._stop.set()
        finally:
            self.stop_listeners()
        # 收尾：冲刷残留文本（此时监听已停，安全）
        if self._text_buf:
            self._q.put(("key", {"type": "key_type", "text": self._text_buf, "ts": time.time()}))
            self._text_buf = ""
        while True:
            try:
                kind, data = self._q.get_nowait()
            except queue.Empty:
                break
            self._consume(kind, data)
        macro = Macro(name=self.macro_name, window=self.window, created=time.time(),
                      steps=self.steps, params=dict(self.params))
        # 有归一化坐标时启用 normalized 模式（跨显示器/分辨率/DPI 缩放适用）
        if any(isinstance(s, ClickStep) and s.xf is not None for s in macro.steps):
            macro.coordinate_mode = "normalized"
        elif any(isinstance(s, ClickStep) and s.x_rel is not None for s in macro.steps):
            macro.coordinate_mode = "relative"
        # 记录录制时的显示器/窗口环境，供跨显示器改造时对照
        wp0 = windows.get_window_placement(self.window.hwnd) if self.window.hwnd else None
        macro.display = {"window_rect": wp0}
        # 人工叙述：录制只给真值，线路与分支/重试意图由人补述，agent 据此固化成脚本
        macro.flow_note = _ask_flow_note(macro)
        return macro


def _ask_flow_note(macro: Macro) -> str:
    """提示用户叙述这条流程的线路与逻辑（人写、agent 读）。"""
    print("\n[叙述] 录制只给了真值动作，线路与逻辑需你补充（可多行，空行结束；输入 q 跳过）。")
    print("[叙述] 例：第 1-3 步是登录（账号从参数取）；点提交后等结果窗口出现；"
          "失败重试 1 次；整体循环 3 次处理三张表。")
    lines: list[str] = []
    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        if line.lower() == "q" and not lines:
            return ""
        lines.append(line)
    return "\n".join(lines)

    def _consume(self, kind: str, data: dict) -> None:
        ts = data.get("ts", time.time())
        delay = round(ts - self._last_ts, 3)
        self._last_ts = ts
        wp = windows.get_window_placement(self.window.hwnd) if self.window.hwnd else None
        if kind == "click":
            self._paused.set()                 # 暂停监听，避免命名输入被录
            try:
                name = input(
                    f"  点击 @({data['x']},{data['y']})  delay={delay}s — 输入按钮名(回车跳过, q 结束): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                self._stop.set()
                self._paused.clear()
                return
            self._paused.clear()
            if name.lower() == "q":
                self._stop.set()
                return
            # 窗口相对坐标 + 归一化比例坐标（重放时按当前窗口位置/尺寸换算，跨显示器适用）
            x_rel = y_rel = xf = yf = None
            if wp:
                x_rel = int(data["x"]) - int(wp["left"])
                y_rel = int(data["y"]) - int(wp["top"])
                w = max(1, int(wp["right"]) - int(wp["left"]))
                h = max(1, int(wp["bottom"]) - int(wp["top"]))
                xf = round(x_rel / w, 6)
                yf = round(y_rel / h, 6)
            self.steps.append(ClickStep(x=data["x"], y=data["y"], label=name,
                                        delay_before=delay, auto_focus=True,
                                        window_placement=wp, x_rel=x_rel, y_rel=y_rel,
                                        xf=xf, yf=yf))
            print(f"    ✔ 步骤 #{len(self.steps)}  '{(name or '(未命名)')}' 点击 @({data['x']},{data['y']})"
                  + (f"  归一=({xf:.3f},{yf:.3f})" if xf is not None else ""))
        elif kind == "key":
            if data["type"] == "key_type":
                step = KeyStep(type="key_type", text=data["text"], delay_before=delay,
                               auto_focus=True, window_placement=wp)
            else:
                step = KeyStep(type="key_press", keys=data["keys"], delay_before=delay,
                               auto_focus=True, window_placement=wp)
            self.steps.append(step)
            desc = f"键入 '{data['text']}'" if data["type"] == "key_type" else f"按键 {'+'.join(data['keys'])}"
            print(f"    ✔ 步骤 #{len(self.steps)}  {desc}")
