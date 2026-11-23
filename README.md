# gui-automation-skill — Windows GUI 自动化的**决策层**技能包

社区项目大多在做**技术层面**的 GUI 操作（点击、输入、读屏），很少有人做**决策层面**：
agent 面对不同软件和任务，不知道**该用什么工具、走什么操作流程**。本包补的就是这一层。

> 不是又一个 GUI 操作库，而是**选型与流程决策知识 + 一条可落地的纯坐标链路**。

## 核心内容

| 组件 | 作用 |
|------|------|
| `skills/windows-automation/SKILL.md` | **决策主干**：UI 可探测（元素树）还是纯坐标？什么情况用什么工具、一般怎么走、窗口管理、作业交互、红线。不含 MCP 工具用法细节（见社区文档） |
| `tools/click-recorder/` | 分支 B 的落地工具：录制采集真值 → 人工叙述流程线路与逻辑 → agent 固化成脚本入库 |
| `launchers/click-recorder` | 与目录无关的启动器（`CLICK_RECORDER_HOME` 覆盖安装位置） |

界面提醒（四边呼吸发光 + 顶部居中面板）由独立仓库 [`screen-reminder`](https://github.com/chendengji/screen-reminder) 提供，本包不重复收录。

## 分支 B 的三段链路

```
① 录制采集真值        →   ② 人工叙述流程线路与逻辑    →   ③ agent 固化成脚本入库
   人真点一遍                  人写自然语言（flow_note）        upgrade 生成 .py + 补分支
```

**② 不可省**：真值里没有线路与意图（哪些步是登录、等什么窗口、失败怎么重试、循环几次）。
跳过②的脚本只有动作没有逻辑，换一次数据就要重录。

## 脚本库（不"用了就丢"）

```
~/.pi/gui-macros/
├── index.json              # 登记表：agent 靠它检索既有脚本
└── <软件slug>/<场景slug>.{json,py}
```

key = `<软件>/<场景>`。索引项含软件名、窗口标题、坐标模式、`flow_note`、参数列表、录制时窗口矩形。
**动手前先 `cr search`，不是重新录制。**

## 跨显示器 / 分辨率 / DPI

录制自动算**窗口客户区归一化比例坐标**（`xf`/`yf` ∈ [0,1]）→ `coordinate_mode="normalized"`，
重放按**当前**窗口尺寸换算，换显示器/改分辨率/改 DPI 都不用管。

旧 `exact` 宏用 `cr rebase <key>` 一次性改造成 `normalized`（保留 `x`/`y` 备查）。

## 安装

```bash
# 1) 工具：把 tools/click-recorder 放到任意稳定位置
cp -r tools/click-recorder ~/Dev/click-recorder
#    搬家只需设环境变量，已固化的脚本同样生效
export CLICK_RECORDER_HOME=$HOME/Dev/click-recorder

# 2) 启动器：放任意在 PATH 里的目录（例 ~/.pi/agent/scripts）
install -m755 launchers/click-recorder ~/.pi/agent/scripts/click-recorder

# 3) 技能：把 skills/ 拷进你的 agent 技能目录
cp -r skills/windows-automation <你的技能目录>/

# 4) 界面提醒：另装 screen-reminder 仓库
```

## 命令

```bash
cr record --software WPS --scene 导出pdf     # 录制入库
cr search 导出                               # 检索既有脚本
cr show WPS/导出pdf                          # 查看步骤与流程叙述
cr play WPS/导出pdf --dry-run                # 预览（首跑必做）
cr upgrade WPS/导出pdf                       # 固化成 .py 入库
cr rebase WPS/导出pdf                        # 坐标改造（换显示器前）
```

`cr` = `bash ~/.pi/agent/scripts/click-recorder`。

## 设计边界

- 本包**不实现** GUI 操作底层（不做点击注入、不做 OCR）；那些是社区成熟项目的活。
- 分支 A（UI 可探测）走 `windows-computer-use` MCP，工具用法现查其文档，本包只记决策与红线。
- 密码/密钥不落盘：宏参数用 `env:VAR` 引用，运行时取环境变量。

## 许可

MIT