"""键盘按键名归一化与映射 — 参考 macro-recorder-plus utilities/key_sequences.py 与 platform/windows_input.py。

- normalize_key_name:   pynput key 值/字符串 → 规范名（如 Key.ctrl_l → "ctrl"）
- normalize_hotkey:     组合键排序去重（ctrl+shift+... 顺序稳定）
- keyboard_key_to_name: pynput Key/KeyCode → 规范名
- name_to_keyboard_key: 规范名 → pynput Key 对象（用于重放）
"""
from __future__ import annotations

from typing import Any

ALIASES = {
    "control": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift_l": "shift", "shift_r": "shift",
    "alt_l": "alt", "alt_r": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
    "return": "enter", "esc": "escape",
}
ORDER = {"ctrl": 0, "shift": 1, "alt": 2, "win": 3}
MODIFIERS = {"ctrl", "shift", "alt", "win"}
SPECIAL_KEYS = {
    "enter", "tab", "backspace", "delete", "home", "end",
    "page_up", "page_down", "up", "down", "left", "right",
    "space", "escape", "insert", "caps_lock", "print_screen", "pause",
}


def normalize_key_name(key: str) -> str:
    key = str(key).strip().lower()
    if key.startswith("key."):
        key = key.split(".", 1)[1]
    return ALIASES.get(key, key)


def normalize_hotkey(keys: list[str] | tuple[str, ...]) -> list[str]:
    norm = [normalize_key_name(k) for k in keys if k]
    return sorted(dict.fromkeys(norm), key=lambda k: (ORDER.get(k, 99), k))


def keyboard_key_to_name(key: Any) -> str:
    char = getattr(key, "char", None)
    if char:
        if str(char).isprintable():
            return normalize_key_name(str(char))
        cc = ord(str(char)[0])
        if 1 <= cc <= 26:
            return chr(ord("a") + cc - 1)
    vk = getattr(key, "vk", None)
    if vk is None:
        vk = getattr(getattr(key, "value", None), "vk", None)
    if vk is not None:
        vk = int(vk)
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        names = {
            0x20: "space", 0xBA: ";", 0xBB: "=", 0xBC: ",",
            0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
            0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
        }
        if vk in names:
            return names[vk]
    return normalize_key_name(str(key))


def name_to_keyboard_key(name: str) -> Any:
    from pynput import keyboard

    key = normalize_key_name(name)
    lookup = {
        "ctrl": keyboard.Key.ctrl, "shift": keyboard.Key.shift,
        "alt": keyboard.Key.alt, "win": keyboard.Key.cmd,
        "enter": keyboard.Key.enter, "escape": keyboard.Key.esc,
        "backspace": keyboard.Key.backspace, "delete": keyboard.Key.delete,
        "home": keyboard.Key.home, "end": keyboard.Key.end,
        "tab": keyboard.Key.tab, "space": keyboard.Key.space,
        "up": keyboard.Key.up, "down": keyboard.Key.down,
        "left": keyboard.Key.left, "right": keyboard.Key.right,
        "page_up": keyboard.Key.page_up, "page_down": keyboard.Key.page_down,
        "insert": keyboard.Key.insert, "caps_lock": keyboard.Key.caps_lock,
    }
    if key in lookup:
        return lookup[key]
    if len(key) == 1:
        return keyboard.KeyCode.from_char(key)
    if key.startswith("f") and key[1:].isdigit():
        return getattr(keyboard.Key, key)
    return keyboard.KeyCode.from_char(key)
