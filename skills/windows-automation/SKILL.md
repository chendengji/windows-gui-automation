---
name: windows-automation
summary: Windows GUI 自动化的宏观决策技能 — 决策主干（UI 可探测 / 纯坐标）+ 工具选型 + 窗口管理 + 作业交互 + 红线
description: 做 Windows 桌面/浏览器/软件自动化前先判该走哪条路：元素树读得到走 windows-computer-use MCP；读不到（无元素树软件）走 click-recorder 坐标录制重放。宏观决策层：工具选型、一般步骤、窗口管理、作业与用户交互、红线。不写 MCP 具体工具用法细节（见社区文档）。
triggers: [窗口, 桌面, 自动化, 点击, 输入, 浏览器, 截图, 录制, 重放, 宏, 坐标, 元素树, mcp, click-recorder]
---

# Windows Automation — 宏观决策层

本技能只管**决策与红线**：什么情况走哪条路、用什么工具、一般怎么走、什么时候必须停下手问用户。
**具体的工具参数与操作细节不在此**（windows-computer-use MCP 的社区文档已有，需要时现查）。

## 零、决策主干（先判这个，再谈工具）

自动化前先回答一个问题：**这个软件的界面，机器能不能"看懂"？**

> **但在判定之前先查脚本库**：`click-recorder search <关键词>` 看该软件/场景是否已有固化脚本（§五）。有就直接用或改造——大部分"不知道用什么工具"的情况，答案就在库里。

| 探测结果 | 走哪条路 | 工具 |
|---------|---------|------|
| 能读到元素树/UIA（标准 Win32、Qt 控件、WPF、浏览器标签页） | **分支 A** | windows-computer-use MCP |
| 读不到（自绘界面、工业/工程软件、独占全屏、反自动化、游戏） | **分支 B** | click-recorder（坐标录制重放） |

**判定方法**（试一次即可，别猜）：
1. `get_window_state(handle)` 或 `automation_elements(list)` —— 能列出带标题/类型的控件节点 → 分支 A。
2. 返回空/只有一个大空白节点 → 该界面是自绘的，**没有任何 UIA 可挂** → 分支 B。

**分支 B 的存在意义正是"分支 A 失效"**：坐标模式不依赖元素树，靠人真点一遍采集真值。

## 一、工具选型（情况 → 工具）

| 情况 | 工具 | 说明 |
|------|------|------|
| 浏览器（Chrome/Edge）操作 | MCP（分支 A） | 拿不到 DOM；要 DOM 另配 Playwright，不在本技能范围 |
| 标准桌面软件（能读元素树） | MCP（分支 A） | 元素定位优于坐标，抗窗口移动 |
| 无元素树软件（工业/工程/自绘/全屏） | **click-recorder**（分支 B） | 录制采集真值 → 升级脚本 |
| 系统级（启进程/查服务/剪贴板） | MCP `automation_system` | |
| 文件另存/打开对话框 | MCP `automation_dialog` | 标准对话框优先用，比坐标稳 |
| 屏幕文字识别 | MCP `automation_visual(extract_text)` | 中文用 chi_sim |
| 跨窗口长流程 | MCP `automation_mission`/`automation_task` | 或分支 B 的宏 |
| **有 CLI / REST / API 可用** | **优先用它，别做 GUI 自动化** | GUI 自动化是最后手段，慢且脆 |

## 二、一般性操作步骤（任何分支通用）

1. **启动界面提醒**（见 §六）——让用户随时知道你在干什么。
2. **探查**：读窗口/元素/截图，别凭猜点。
3. **定位窗口**：记下句柄；**句柄会失效**（关窗/重开/切标签），操作前必要时重新查。
4. **聚焦**：确保目标窗口在前台。**聚焦后不要动鼠标/Alt+Tab**，否则坐标错位。
5. **执行**：分步做，每步做校验（截图或读状态）。
6. **留证**：关键节点截图存档，便于事后回溯与交用户确认。

## 三、窗口管理（共性关键）

- **标签页不同 → 窗口标题不同**：Chrome/Edge 窗口标题随激活标签页变化（形如 `当前标签页 - Google Chrome`），**不能按固定标题定位**。按 class 名（`Chrome_WidgetWin_1`）或进程名找。
- **先最大化再操作**：内容遮挡、坐标错位多因窗口未最大化。
- **句柄会失效**：关窗、重开、切标签都会换句柄；录制/重放后要**按标题重找**（click-recorder 的 player 已内置此逻辑）。
- **坐标脆弱性**：绝对屏幕坐标在窗口移动/DPI 变化/分辨率变化时全错。分支 B 已支持 `coordinate_mode="relative"`（相对窗口左上角，重放时按当前窗口位置换算）。
- **高 DPI 缩放**：坐标偏移的常见根因；优先元素定位，或确认缩放比例一致。

## 四、分支 A：UI 可探测 → windows-computer-use MCP

**只记决策与第一个必踩的坑，工具用法现查社区文档**：

- 参数有两种格式，混用会报 `Validation failed`：**扁平**（`automation_mouse`/`keyboard`/`elements`/`dialog`/`shortcut`/`get_*_state`）vs **嵌套 `{"request":{...}}`**（`automation_windows`/`system`/`visual`/`smart`/`mission`/`task`/`watch`）。先按扁平试，报 schema 错就包一层。
- 点击顺序即工作流：有严格先后关系的操作要建模成**有序步骤序列**，每步校验通过再进下一步，某步失败即停，不跳过。
- 无接管控制流：本环境的 MCP 只做操作与读屏，不做人类接管弹窗。

## 五、分支 B：纯坐标 → click-recorder

### 5.1 脚本库：统一命名、统一格式，不"用了就丢"

形成的每个流程都固化入库，**不散落临时目录**：

```
~/.pi/gui-macros/
├── index.json              # 脚本登记表：agent 靠它"找出存储的脚本"
└── <软件slug>/
    ├── <场景slug>.json      # 宏：真值动作 + 人工叙述 + 参数
    └── <场景slug>.py        # 固化脚本（upgrade 生成）
```

**key = `<软件>/<场景>`**（例 `WPS/导出pdf`）。索引项含：软件名、窗口标题、坐标模式、`flow_note`、参数列表、录制时窗口矩形——这些就是"换显示器能不能直接用"的判断依据。

**动手前第一步是检索，不是重新录制**：`search` 能命中既有脚本就直接用/改造；真没有才录。

### 5.2 命令

统一用启动器（不依赖当前目录）：`~/.pi/agent/scripts/click-recorder`。它按
`CLICK_RECORDER_HOME` → 默认安装位置 解析项目根；搬家只改这一个环境变量，已固化脚本也跟着生效。

```bash
alias cr='bash ~/.pi/agent/scripts/click-recorder'      # 建议设别名

cr record --software WPS --scene 导出pdf            # 录制入库（左键+键盘都被录，F9 结束）
cr list                                              # 列出脚本库全部条目
cr search 导出                                        # ★ 先检索既有脚本
cr show WPS/导出pdf                                   # 查看步骤与流程叙述
cr play WPS/导出pdf --dry-run                         # 预览（首跑必做）
cr play WPS/导出pdf --param user=bob
cr upgrade WPS/导出pdf                                 # 固化成 .py 入库
cr run WPS/导出pdf --dry-run                           # 运行已固化脚本（自动用工具所在 Python）
cr rebase WPS/导出pdf                                  # 坐标改造（换显示器前）
```

未设别名时直接写 `bash ~/.pi/agent/scripts/click-recorder <子命令>`。
（若项目从默认位置搬过家，设 `CLICK_RECORDER_HOME=<新项目根>`，不要改技能里的路径。）

### 5.3 三段链路（**中间那段是人工叙述，不是可选的**）

```
① 录制采集真值        →   ② 人工叙述流程线路与逻辑    →   ③ agent 固化成脚本入库
   人真点一遍                  人写自然语言：线路/分支/重试        upgrade 生成 .py + 补分支
```

**为什么三段都不可少**：

- ① 只给**被验证过的动作真值**——agent 从零设计工作流必然幻觉坐标和按钮名。
- ② 真值里没有**线路与意图**：哪些步是登录、等什么窗口出现、失败怎么重试、循环几次。
  录制结束后会提示叙述（可多行，输入 `q` 跳过），写入 `flow_note`。
- ③ agent 据 ①+② 固化脚本；**升级点标在生成脚本的 `★ agent 升级点`**，就在 `flow_note` 下方。

**跳过②的后果**：脚本只有动作、没有逻辑，换一次数据就要重录。

### 5.4 跨显示器 / 分辨率 / DPI：用 normalized 模式 + rebase

**首选归一化坐标，不要手改坐标**：

| 模式 | 行为 | 适用 |
|------|------|------|
| `normalized` | 存 `xf`/`yf` ∈[0,1]（窗口客户区比例），重放按**当前**窗口尺寸换算 | **跨显示器/分辨率/DPI 首选** |
| `relative` | 相对窗口左上角像素偏移，重放按当前窗口位置换算 | 窗口可移动、尺寸固定 |
| `exact` | 录制时的绝对屏幕坐标 | 窗口位置必须固定（旧宏） |

**录制时自动算归一化坐标**，有新坐标就自动切 `normalized`。旧 `exact` 宏用 `rebase` 一次性改造成 `normalized`：

```
cr rebase <key>                          # 用录制时窗口矩形自动改造
cr rebase <key> --from "0,0,1920,1080"   # 手动指定旧窗口矩形
```

**改造前先看 `index.json`**：`display.window_rect` 是录制时的窗口几何，对照当前环境即可判断能否直接用。换显示器后建议先 `play --dry-run` 核对描述，再真跑。

### 5.5 JSON 字段（自描述规格，改这个比改代码简单）

| 字段 | 作用 |
|------|------|
| `flow_note` | **人工叙述的流程线路与逻辑**——固化脚本的主要依据 |
| `steps[].note` | 单步说明（人写） |
| `steps[].type` | `x_click` / `key_press` / `key_type` / `wait_for` |
| `steps[].xf`/`yf` | 归一化比例坐标（跨显示器）；`x_rel`/`y_rel` 相对像素偏移 |
| `steps[].loop_count` / `retry` | 步级循环 / 步级失败重试 |
| `steps[].wait_for` | `kind=window` `window_gone` `image` + `target` + `timeout`；超时抛错 → 触发 retry |
| `pre_actions` | 一次性预置步骤（打开软件/文档），主循环开始时执行一次 |
| `params` | `${name}` 占位替换源；值为 `env:VAR` 时运行时取环境变量（**密码不落盘**） |
| `loop_count` / `retry` | 宏级主循环 / 整体失败重试 |
| `display` | 录制时窗口矩形，供跨显示器判断与 rebase |

### 5.6 agent 升级：录制做不到的才靠它

录制只覆盖**机械动作序列**。以下必须 agent 在 JSON/生成脚本上补（依据 `flow_note`）：

- **条件分支**（如果…则…）
- **数据读写**（从 CSV/表格取参数填进 `overrides`）
- **异步等待**（`wait_for` 的 target 选准，或脚本里插等待）
- **异常重试与校验**（失败后改 macro 再 replay）

**不要另写一套点击逻辑**——JSON 宏是唯一真值，脚本是它之上的薄编排层，否则丢可复现性。
## 六、作业过程与用户交互

### 6.1 界面提醒（screen_reminder）

屏幕**四边呼吸发光边框 + 顶部居中面板**显示当前操作，**不抢焦点、鼠标点击穿透**，用户看得见你在干什么，也照常能自己操作。

```bash
python screen_reminder.py start                        # 任务开始，一次
python screen_reminder.py set "正在点击「保存」"         # 每步一句，零输出
python screen_reminder.py set "正在导出" --hold          # 任务级保持
python screen_reminder.py status / stop
```

- **守护自动感知**：daemon 每 500ms 读 pi session 的 `automation_*`/`cua_*` 调用，自动亮+变文字+变颜色，agent **零注意力成本**；30s 无操作自动隐藏；**聊天不触发**（offset 跳到文件尾，只对新调用生效）。
- 分支 B 重放**自动亮提醒**（player 内置，无需调用方管）；pyautogui/pynput 包装见 `screen_reminder_auto.py`。
- `set` 零输出零等待，勿解析其 stdout；daemon 自管生命周期。

### 6.2 与用户交互

- **长任务分段**：不要一口气跑完再汇报；关键节点停下来给状态，让用户能中断。
- **失败即停**：某步失败先看截图/日志再决定，不跳过、不盲目重试。
- **必须停下来问用户的**：不可逆操作（删除/发送/提交）、需要用户只在场的凭证或验证码、目标软件有审批/授权窗口、坐标模式无法确认窗口就是目标。
- **首跑先 dry-run**：分支 B 任何宏真跑前必 `--dry-run` 过一遍。

## 七、红线

- **密码/密钥不落盘**：宏 JSON 里用 `env:VAR` 引用，运行时取环境变量。示例宏里明文存 `secret123` 的做法是反例。
- **未获审批不操作**：MCP 分支的键盘/鼠标可能触发 HITL，需 `approve_automation` 授权窗口期；先查 `automation_safety(status)` 确认 `kill_switch=false`、`dry_run=false`。
- **限速**：MCP 默认 120 次/分钟，超出被 block；重试先 `automation_safety(reset_counters)`。
- **禁用 opt-in 危险功能**（人脸/键盘记录等）默认关，不要开。
- **不动用户源目录**：文献库/源 PDF 目录只读，自动化产物一律放工作目录。
- **不抢焦点**：所有提醒与自动化都不应用户中断操作；坐标点击前先聚焦目标窗口。
- **记忆写作防误伤**：不要把 ≥40 字符无空格斜杠串（工具名连写）写进记忆正文/标题——清扫器会把这类串误判为密钥掩码成 `****`。用空格/顿号分隔或拆行。

## 八、故障排查速查

- 窗口定位不到 → 标题随标签页变了（§三）；换 class 名/进程名。
- 坐标全错 → 窗口移动/DPI 变化/未最大化；分支 B 改用 relative 模式。
- 元素读不到 → 自绘界面，转分支 B。
- 重放点空 → 句柄失效，player 会按标题重找；确认窗口标题没变。
- `wait_for` 超时 → target 写错或界面未渲染完，加大 timeout 或改 kind。
- 提醒不亮 → daemon 未启动（`python screen_reminder.py start`）；聊天不会亮（正常）。