"""click-recorder — 针对无元素树软件的鼠标点击录制/重放工具。

整合来源：
- 数据模型/动作结构 参考 macro-recorder-plus (models/actions.py: label, window_placement, auto_focus, coordinate_mode)
- 窗口管理           参考 ClickYen (core/window_manager.py: EnumWindows/按标题查找/前台/聚焦)
- 录制思路           参考 macro-recorder-plus recorder/input_recorder.py (pynput 全局监听)
- 重放思路           参考 macro-recorder-plus platform/windows_input.py (ActionExecutor) + pyautogui
"""
__version__ = "0.1.0"
