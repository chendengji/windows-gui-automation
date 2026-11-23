"""数据模型 — 动作结构参考 macro-recorder-plus/models/actions.py 的 MacroAction。

动作类型：
- type="x_click"    鼠标点击：x/y + button（另存 x_rel/y_rel 相对窗口客户区，用于窗口可移动）
- type="key_press"  键盘组合/特殊键：keys（如 ["ctrl","c"] / ["enter"] / ["f9"]）
- type="key_type"   文本输入：text（unicode，重放时逐字符注入，支持中文）
- type="wait_for"   条件等待：等窗口出现/消失、或文本/图像出现（支持超时）

所有动作共享：label(按钮名/动作名，用户可辅助输入) + delay_before + auto_focus +
window_placement(窗口放置) + note + loop_count(本步重复) + retry(本步失败重试)。

参数化：text/keys 中可用 ${name} 占位，重放时按 Macro.params 替换。
  params 的值若是形如 "env:MY_SECRET" 的字符串，运行时从环境变量取——
  **密码等敏感值不落盘**，只写 env 名。

coordinate_mode：
- "exact"       绝对屏幕坐标（窗口位置必须固定）
- "relative"    窗口相对像素坐标（重放时按当前窗口位置换算，窗口可移动）
- "normalized"  窗口客户区归一化比例坐标（0.0~1.0，重放时按当前窗口尺寸换算，
                 **不同显示器/分辨率/DPI 缩放下都适用**——跨显示器首选）
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any

PARAM_RE = re.compile(r"\$\{(\w+)\}")


def render(value: Any, params: dict | None) -> Any:
    """把字符串里的 ${name} 占位替换为 params 值；缺失时保留原样并加 (未提供) 标记。"""
    if not isinstance(value, str) or not params or "${" not in value:
        return value
    def _sub(m):
        key = m.group(1)
        if key in params:
            v = params[key]
            if isinstance(v, str) and v.startswith("env:"):
                import os
                v = os.environ.get(v[4:], "")
            return str(v)
        return m.group(0) + f"(未提供:{key})"
    return PARAM_RE.sub(_sub, value)


@dataclass
class WindowRef:
    """目标窗口引用 — 参考 ClickYen WindowManager 返回的窗口元数据。"""
    title: str = ""
    hwnd: int = 0
    class_name: str = ""
    process: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WindowRef":
        d = d or {}
        return cls(
            title=d.get("title", ""),
            hwnd=int(d.get("hwnd", 0) or 0),
            class_name=d.get("class_name", ""),
            process=str(d.get("process", "")),
        )


@dataclass
class BaseStep:
    """动作公共字段 — 对应 macro-recorder-plus 的 MacroAction 公共部分。"""
    type: str = "x_click"
    label: str = ""
    delay_before: float = 0.25
    auto_focus: bool = True
    window_placement: dict | None = None
    note: str = ""
    loop_count: int = 1    # 本步重复次数（>1 时循环执行本步）
    retry: int = 0         # 本步失败重试次数

    def _common(self) -> dict:
        return {
            "type": self.type,
            "label": self.label,
            "delay_before": round(self.delay_before, 3),
            "auto_focus": self.auto_focus,
            "window_placement": self.window_placement,
            "note": self.note,
            "loop_count": int(self.loop_count),
            "retry": int(self.retry),
        }

    @classmethod
    def _from_common(cls, d: dict) -> dict:
        return dict(
            label=d.get("label", ""),
            delay_before=float(d.get("delay_before", 0.25)),
            auto_focus=bool(d.get("auto_focus", True)),
            window_placement=d.get("window_placement"),
            note=d.get("note", ""),
            loop_count=int(d.get("loop_count", 1) or 1),
            retry=int(d.get("retry", 0) or 0),
        )


@dataclass
class ClickStep(BaseStep):
    """鼠标点击动作。

    x/y 为录制时的绝对屏幕坐标；x_rel/y_rel 为相对窗口左上角的像素偏移；
    xf/yf 为相对窗口客户区的归一化比例（0.0~1.0）。
    """
    type: str = "x_click"
    x: int = 0
    y: int = 0
    button: str = "left"
    x_rel: int | None = None
    y_rel: int | None = None
    xf: float | None = None
    yf: float | None = None

    def to_dict(self) -> dict:
        d = self._common()
        d.update({"x": self.x, "y": self.y, "button": self.button,
                  "x_rel": self.x_rel, "y_rel": self.y_rel,
                  "xf": (None if self.xf is None else round(self.xf, 6)),
                  "yf": (None if self.yf is None else round(self.yf, 6))})
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ClickStep":
        c = cls._from_common(d)
        return cls(type="x_click", x=int(d.get("x", 0)), y=int(d.get("y", 0)),
                   button=d.get("button", "left"),
                   x_rel=(None if d.get("x_rel") is None else int(d["x_rel"])),
                   y_rel=(None if d.get("y_rel") is None else int(d["y_rel"])),
                   xf=(None if d.get("xf") is None else float(d["xf"])),
                   yf=(None if d.get("yf") is None else float(d["yf"])),
                   **c)


@dataclass
class KeyStep(BaseStep):
    """键盘动作：key_press(组合/特殊键) 或 key_type(文本)。"""
    type: str = "key_press"
    keys: list[str] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict:
        d = self._common()
        if self.type == "key_type":
            d.update({"text": self.text})
        else:
            d.update({"keys": self.keys})
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "KeyStep":
        c = cls._from_common(d)
        t = d.get("type", "key_press")
        return cls(type=t, keys=list(d.get("keys", [])), text=d.get("text", ""), **c)


@dataclass
class WaitForStep(BaseStep):
    """条件等待动作。kind：window(标题出现) / window_gone(消失) / text(区域文本) / image(图像模板)。"""
    type: str = "wait_for"
    kind: str = "window"
    target: str = ""
    timeout: float = 10.0
    interval: float = 0.25

    def to_dict(self) -> dict:
        d = self._common()
        d.update({"kind": self.kind, "target": self.target,
                  "timeout": round(self.timeout, 3), "interval": round(self.interval, 3)})
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WaitForStep":
        c = cls._from_common(d)
        return cls(type="wait_for", kind=d.get("kind", "window"), target=d.get("target", ""),
                   timeout=float(d.get("timeout", 10.0)),
                   interval=float(d.get("interval", 0.25)), **c)


def step_from_dict(d: dict) -> BaseStep:
    t = (d or {}).get("type", "x_click")
    if t in ("key_press", "key_type"):
        return KeyStep.from_dict(d)
    if t == "wait_for":
        return WaitForStep.from_dict(d)
    return ClickStep.from_dict(d)


@dataclass
class Macro:
    """一个可复现的宏（鼠标+键盘动作序列）— 对应 macro-recorder-plus 的 Macro。

    - pre_actions：一次性设置步骤（打开软件/文档），只在重放开始时执行一次；
      steps 可整体循环 loop_count 次。
    - params：参数表，${name} 占位替换源。值为 "env:VAR" 时运行时取环境变量（密码不落盘）。
    - retry：整段重放失败时的重试次数。
    - flow_note：**人工叙述的流程线路与逻辑**（人写、agent 读）——录制只给真值，
      线路与分支/重试意图由人叙述，agent 据此固化成脚本。这是三段链路的中间环节。
    """
    name: str = ""
    window: WindowRef = field(default_factory=WindowRef)
    created: float = 0.0
    coordinate_mode: str = "exact"
    steps: list[BaseStep] = field(default_factory=list)
    pre_actions: list[BaseStep] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    loop_count: int = 1
    retry: int = 0
    flow_note: str = ""
    display: dict | None = None     # 录制时的显示器/缩放/窗口矩形，供跨显示器改造参考

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "coordinate_mode": self.coordinate_mode,
            "created": round(self.created, 3),
            "window": self.window.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "pre_actions": [s.to_dict() for s in self.pre_actions],
            "params": dict(self.params),
            "loop_count": int(self.loop_count),
            "retry": int(self.retry),
            "flow_note": self.flow_note,
            "display": self.display,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Macro":
        d = d or {}
        return cls(
            name=d.get("name", "Untitled"),
            window=WindowRef.from_dict(d.get("window", {})),
            created=float(d.get("created", 0.0)),
            coordinate_mode=d.get("coordinate_mode", "exact"),
            steps=[step_from_dict(s) for s in d.get("steps", [])],
            pre_actions=[step_from_dict(s) for s in d.get("pre_actions", [])],
            params=dict(d.get("params", {})),
            loop_count=int(d.get("loop_count", 1) or 1),
            retry=int(d.get("retry", 0) or 0),
            flow_note=d.get("flow_note", ""),
            display=d.get("display"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)