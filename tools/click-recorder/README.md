# click-recorder

针对**无元素树软件**（MCP/UIA 读不到按钮）的鼠标点击**录制 → 复现**工具。

整合自：
- **macro-recorder-plus**：动作数据模型（`label` 按钮名 / `auto_focus`+`window_placement` 窗口聚焦 / `coordinate_mode` / `type=x_click`）、录制思路（pynput 全局监听）、重放思路（ActionExecutor）
- **ClickYen**：窗口管理（`WindowManager` 枚举/按标题查找/前台窗口/聚焦激活，win32 句柄级，不依赖元素树）
- **PyAutoGUI-Recorder**：录制→生成可执行动作的直白思路

## 功能

一次宏 = **目标窗口 + 有序动作序列**，支持：

| 动作 | 内容 | 说明 |
|------|------|------|
| `x_click` | 坐标(x,y) + **按钮名** | 鼠标左键点击；录制时逐点由你辅助输入按钮名 |
| `key_type` | 文本 text | 连续可打印字符 → 文本输入（unicode，支持中文） |
| `key_press` | 组合/特殊键 keys | 如 ctrl+c、enter、tab、f9 等 |

每步含：`label` 名称 + 点击前延迟 + `auto_focus`(自动聚焦目标窗口) + `window_placement`。

```
录制：目标窗口 ──► 操作软件（左键点击/键盘输入都被录）──► 存成 JSON
复现：加载 JSON ──► 聚焦窗口 ──► 逐动作执行（点击/键入/按键）
```

> 录制中每次左键点击后会【暂停监听】并询问按钮名（回车跳过），避免命名输入被误录成键盘动作；按 F9 结束。
> 录制开始时可先声明参数（`名=值` 或 `名=env:环境变量`），重放时以 `${名}` 形式引用。

## 三段链路

```
① 录制采集真值      →  ② 人工叙述流程线路与逻辑    →  ③ agent 固化成脚本入库
   人真点一遍                    人写自然语言（flow_note）          upgrade 生成 .py + 补分支
```

录制只给**被验证过的动作真值**；线路与意图（哪些步是登录、等什么窗口、失败怎么重试、循环几次）
由人在 ② 补述。跳过②的后果：脚本只有动作没有逻辑，换一次数据就要重录。
条件分支、数据读写、异步等待、异常重试则须由 agent 在 ③ 补（依据 `flow_note`）。

## 脚本库（统一命名与格式，不“用了就丢”）

```
~/.pi/gui-macros/
├── index.json              # 脚本登记表：agent 靠它“找出存储的脚本”
└── <软件slug>/
    ├── <场景slug>.json      # 宏：真值动作 + 人工叙述 + 参数
    └── <场景slug>.py        # 固化脚本（upgrade 生成）
```

**key = `<软件>/<场景>`**（例 `WPS/导出pdf`）。索引项含软件名、窗口标题、坐标模式、
`flow_note`、参数列表、录制时窗口矩形——后者是判断“换显示器能不能直接用”的依据。

**动手前先检索，不是重新录制**：`search` 命中既有脚本就直接用或改造。

## 使用

```bash
# 统一用启动器（与当前目录无关；CLICK_RECORDER_HOME 可覆盖安装位置）
alias cr='bash ~/.pi/agent/scripts/click-recorder'   # 与目录无关

# 录制入库（统一命名：软件名 + 场景名）
cr record --software 示例软件 --scene 导出pdf
# 录制（按标题关键词指定目标窗口，列出候选供选）
cr record --software 示例软件 --scene 导出pdf --window "目标软件"

# 录制过程中：声明参数 → 左键点击输入按钮名（回车跳过）→ F9 结束 → 叙述流程线路与逻辑（q 跳过）

cr list                          # 列出脚本库全部条目
cr search 导出                   # 按关键词检索（软件/场景/窗口/叙述/参数）
cr show 示例软件/导出pdf           # 查看步骤与流程叙述（参数值自动掩码）
cr play 示例软件/导出pdf --dry-run  # 只预览（首跑必做）
cr play 示例软件/导出pdf --speed 2
cr play 示例软件/导出pdf --param user=bob   # 运行时注入参数
cr upgrade 示例软件/导出pdf         # 固化成 .py 入库
cr rebase 示例软件/导出pdf          # 坐标改造（换显示器前）
cr rebase 示例软件/导出pdf --from "0,0,1920,1080"  # 指定旧窗口矩形
```

**重放能力**（均在 JSON 里声明，player 运行时执行）：

| 能力 | 字段 |
|------|------|
| 人工叙述流程线路与逻辑 | `flow_note`（整体）+ `steps[].note`（单步） |
| 宏级主循环 / 整体失败重试 | `loop_count` / `retry` |
| 步级循环 / 步级失败重试 | `steps[].loop_count` / `steps[].retry` |
| 参数替换 | `params` + 文本里写 `${名}`；值为 `env:VAR` 时运行时取环境变量（**密码不落盘**） |
| 条件等待 | `type="wait_for"`，`kind=window` `window_gone` `image` + `target` + `timeout`；超时抛错 → 触发 retry |
| 一次性预置步骤 | `pre_actions`（主循环开始时执行一次，不随循环重复） |
| **跨显示器坐标** | `coordinate_mode="normalized"` + `steps[].xf/yf`（窗口客户区比例，重放按当前窗口尺寸换算）——**不同显示器/分辨率/DPI 首选** |
| 窗口相对坐标 | `coordinate_mode="relative"` + `steps[].x_rel/y_rel`（窗口可移动、尺寸固定） |
| 旧宏改造 | `rebase <key>` 把 `exact` 宏一次性转成 `normalized`，此后换显示器免手改 |

## 设计

- `click_recorder/keys.py`     键盘按键名归一化/映射（取 macro-recorder-plus key_sequences/windows_input）
- `click_recorder/model.py`   宏/步骤/窗口数据模型（JSON 结构兼容 macro-recorder-plus 风格）+ `${}` 参数替换 + `flow_note` 叙述
- `click_recorder/windows.py` 窗口枚举/查找/前台/聚焦/矩形（win32 句柄级）
- `click_recorder/recorder.py` pynput 全局鼠标监听 + F9 停止 + 逐点按钮名输入 + 归一化/相对坐标计算 + 录后提示流程叙述
- `click_recorder/player.py`  解析窗口（句柄失效按标题重找）→ 逐动作执行，支持循环/重试/参数/条件等待/归一化坐标；内置界面提醒 emit
- `click_recorder/cli.py`     record / list / search / show / play / upgrade / rebase（含 `~/.pi/gui-macros/` 脚本库与 `index.json` 登记）

> 坐标模式：录制时自动计算窗口**归一化比例坐标**，有它则自动切 `coordinate_mode="normalized"`
> （不同显示器/分辨率/DPI 缩放下重放按当前窗口尺寸换算）；其次才是 `relative`（窗口可移动、尺寸固定）。
> 旧 `exact` 宏用 `rebase` 一次性改造成 `normalized`，此后换显示器免手改。
> 若为旧宏（`exact` 模式，无 `x_rel`），重放基于记录时的绝对屏幕坐标，需窗口位置固定（如无边框/独占全屏软件）。
