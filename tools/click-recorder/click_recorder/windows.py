"""窗口管理 — 参考 ClickYen/core/window_manager.py 的 WindowManager。

提供：枚举可见窗口 / 按标题正则查找 / 取当前前台窗口 / 聚焦激活 / 取窗口矩形。
不依赖 UIA 元素树，纯 win32 句柄级操作，适合无元素树软件。
"""
from __future__ import annotations

import re

import win32api
import win32con
import win32gui
import win32process

from .model import WindowRef


def list_windows(visible_only: bool = True) -> list[WindowRef]:
    """枚举可见窗口，返回 WindowRef 列表。"""
    out: list[WindowRef] = []

    def _cb(hwnd, _):
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        try:
            cls = win32gui.GetClassName(hwnd)
        except Exception:
            cls = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        out.append(WindowRef(title=title, hwnd=hwnd, class_name=cls, process=str(pid)))

    win32gui.EnumWindows(_cb, None)
    return out


def get_foreground() -> WindowRef | None:
    """取当前前台窗口。"""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        title = ""
    try:
        cls = win32gui.GetClassName(hwnd)
    except Exception:
        cls = ""
    return WindowRef(title=title, hwnd=hwnd, class_name=cls)


def find_windows(pattern: str, visible_only: bool = True) -> list[WindowRef]:
    """按标题正则查找窗口（不区分大小写）。"""
    rx = re.compile(pattern, re.IGNORECASE)
    return [w for w in list_windows(visible_only) if rx.search(w.title)]


def activate(hwnd: int) -> bool:
    """聚焦/激活窗口（还原后置前）。"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        try:
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False


def get_window_placement(hwnd: int) -> dict | None:
    """取窗口矩形。"""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        return {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}
    except Exception:
        return None


def cursor_pos() -> tuple[int, int]:
    return win32api.GetCursorPos()
