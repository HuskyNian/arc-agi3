# 持久工作区、历史回测与精简 prompt

2026-10-16 清理后：本页仅保留旧实验的历史说明，下文接口、配置和运行指令均已失效。对应实现、专属测试和开关已删除；当前使用说明见 [停滞反馈与验证执行](strategy-and-execution.md)。

实现日期：2026-10-15。功能已通过本地沙箱测试；旧 C1/G1/Q1 组合实跑退化，新 Q2 保守措辞版尚未跑分。见 [最新分析](../analysis/strategy_revision_2026-10-15.md)。

## 运行开关

三个旧功能独立开关，现均默认关闭。修改环境变量后重新启动 harness/kernel。

| 设置 | 默认 | 作用 |
| --- | --- | --- |
| `ARC3_WORKSPACE` | `0` | 显式持久数据工作区（旧实验） |
| `ARC3_RULE_BACKTEST` | `0` | Python 中的只读 `backtest` 接口（旧实验） |
| `ARC3_COMPACT_PROMPT` | `0` | 仅压缩原系统提示的措辞和明确重复，其他提示保持原版 |

`0` 可分别关闭。全部关闭时回到旧 prompt 和旧工具接口；已有函数保留配置不变。工作区与函数保留互不依赖，但跨调用复用规则函数建议维持 notebook 已有的 `ARC3_PERSISTENT_FUNCTIONS=1`、`ARC3_PERSISTENT_FUNCTIONS_SCOPE=game`、`ARC3_PERSISTENT_FUNCTIONS_IMPORTS=1`。

## 1. 工作区：保存数据，避免隐式恢复整套解释器

模型在 Python 工具中使用：

```python
# 当前关的布局；同关 RESET 后仍可读取。
workspace.put('layout', {'walls': [[4, 5], [4, 6]]})

# 已支持的规则参数；跨关保留，仍需检查新增机制。
workspace.put('rules', {'move_distance': 1}, scope='game')

# 当前观测下的计划；任何真实动作后自动清除。
workspace.put('plan', ['RIGHT', 'UP'], scope='observation')

layout = workspace.get('layout')
rules = workspace.get('rules', scope='game')
workspace.keys(scope='game')
workspace.delete('layout')
workspace.info()
```

- 默认 `level`：换关清理，同关重置保留。仅放布局/关内规则等可复用数据，不要把当前物体位置误当作不变布局。
- `observation`：真实动作后清理，包括画面不变、UNDO 和 RESET；拒绝执行的动作不应清理。适合当前状态相关的搜索缓存和计划。执行计划时可先加载到本次调用的局部变量，之后每一步仍需验证。
- `game`：跨关保留，切换游戏/会话时清理。不同 pass、不同 agent 不共享数据。
- 数据由宿主进程保管，不重复塞进每次 prompt 或初始沙箱状态；模型通过 RPC 按需读取。不会写任意文件或执行 pickle。
- 支持有限、无环的 JSON 数据；tuple 读取后变为 list。返回副本，修改后需要再次 `put`。不接受函数、帧对象、集合、非字符串字典键、NaN/Infinity。
- 最多 128 条、总编码大小 2,000,000 bytes、单条 512,000 bytes。失败写入不破坏旧值；显式写入成功后，即使该 snippet 随后异常/超时，也仍保留。
- `workspace.info()['version']` 随真实观测更新。长计算开始前可保存版本，写入时 `put(..., expected_version=version)` 防止在已经执行动作后误存旧计划。必须使用计算开始前的版本才能检测过期。
- 不保存任意局部变量，也不在进程重启后恢复。若规则程序版本变化，应由模型替换/删除依赖旧规则的缓存；当前没有通用的模型依赖自动失效系统。

原有合格函数保留继续负责代码，workspace 负责数据。函数可读取 workspace；推荐纯预测函数通过参数接收可变数据，避免依赖当前观测去预测历史状态。

## 2. 历史回测与反例反馈

规则直接使用普通 Python 函数，无需增加一套注册 DSL 或每轮固定流程：

```python
# 示例规则，仅适用于确认过 R 是单格玩家、RIGHT 能右移的局部情形。
def observe(frame):
    rows = frame.ascii.splitlines()
    cells = [(r, c) for r, row in enumerate(rows)
             for c, value in enumerate(row) if value == 'R']
    if len(cells) != 1:
        raise ValueError('expected one player cell')
    return {'player': list(cells[0])}

def predict(before, action_display):
    if action_display != 'RIGHT':
        return None  # 不支持的动作不冒充预测正确。
    r, c = observe(before)['player']
    return {'player': [r, c + 1]}

backtest(predict, observe)
```

如果撞墙，可能得到这样的具体反例：

```json
{"index": 7, "step": 12, "action": "RIGHT",
 "differences": {"player": {"predicted": [4, 8], "observed": [4, 7]}}}
```

接口：`backtest(predict, observe, indices=None, limit=32, max_examples=3)`。

- `predict(before_frame, action_display)` 返回非空字段字典，`observe(after_frame)` 返回可比较的实际字段；只比较预测里声明的字段。MOUSE 的 action_display 带点击坐标，沿用 transitions 的字符串格式。
- 默认检查当前关最近 32 条合格转移，可设 1–64；`indices` 是 `transitions` 的非负下标，传入后仍受 limit 限制。返回实际测试下标，不能将采样误报成全历史覆盖。
- 排除缺少前后帧、跨关、RESET、自动动作以及 game_over/level_completed/done/run_complete 的终止转移，避免将自动重置或新关画面当作普通动力学。此版本不验证死亡/胜利终止条件。
- 返回 tested/passed/failed/errors/unsupported、字段覆盖次数、跳过原因和最多 3 个反例/错误。最多 32 个短字段名，单份预测/观测限制大小，过长差异值只显示预览。
- 状态有 `no_checks`、`model_error`、`counterexample`、`consistent_on_sample`。空预测、缺失观测字段、异常或全不支持不会报告成功。
- 回测回调不能调用真实 `action`、写 workspace 或触发实时动画读取；可读取已保存参数。回调打印被抑制；输入帧以副本传递。完成后正常动作接口恢复。
- 预测回调不接收真实 after-frame；但这不是对恶意模型代码的防泄漏隔离，代码仍能自行引用全局 history/current_frame。使用时应保持预测函数只依赖 before-frame、动作和合法历史状态，不能用观察到的答案作弊。
- 此版本是逐转移的局部模型检查，不是自动系统辨识，也不是完整的隐藏状态序列回放。历史一致仅支持已测试字段/状态；静态背景预测无法证明动态规则正确。
- 与 Python snippet 共用时间上限；回调死循环由原有进程超时终止，不会花游戏动作。模型在需要验证规则时主动调用，代码修改后不自动运行所有回测。

完整搜索状态机、自动策略重启、历史动画数据库仍是后续实验。本次先交付 C1 和按需 G1，不把它们包装成已经完成的通用世界模型。

## 3. Prompt 调整

当前 Q2 保守版：同样开启 workspace/backtest 时，系统文本从 19,979→19,006 字符（-4.87%）。完整原版生成后，仅做精确措辞替换及有保留句的去重；恢复原逐轮、换关、死亡、函数提醒和摘要要求。默认关闭。查看 [原文与新版差异](../analysis/prompt_v2.diff) 和 [审计](../analysis/prompt_v2_audit.json)。这不是行为等价证明，也未证明涨分或加速。

以下为已退役 Q1 的历史记录，不代表当前实现。它不仅精简，也改了策略语义；不再作为纯压缩实验。

Q1 按原 notebook 的配置生成并比较（[历史测量结果](../analysis/prompt_comparison.json)）：

| 内容 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 系统 prompt | 18,467 字符 | 5,320 字符 |
| 示例首轮用户 prompt | 1,811 字符 | 199 字符 |

新系统 prompt 已包括 workspace/backtest 说明，总字符数减少约 **71.2%**。这是字符计数，不是 tokenizer token 数或实测加速比例。

调整内容：

- API 只在系统提示中解释，逐轮保留实际状态、动作结果和必要反馈。
- 去掉重复的全局检查清单、“不要节省工具调用”、“一直调查直到清楚”等引导。
- 搜索、建模、回测均按需；不要求每轮输出 world model、完整规则表或长反思。
- 精简换关、死亡和摘要提示，避免将猜测的死亡原因写成确定规则。
- 允许程序处理完整字母棋盘，但保持输出为小片段和计算结果；未新增网格 API。
- 保留工具格式、RESET 成本、终止标志、历史帧语义、沙箱限制、函数依赖和计数规则。
- 不关闭 thinking，不改温度、上下文长度或输出 token 上限。缺少模型推理对照时，不宣称推理已经更快。

## 4. Kaggle 接入

`arc-agi-3-m2-my.ipynb` 已改为直接导入源码 Dataset，无需 harness patch：

1. 新 Dataset 至少包含同一目录下的 `ARC3-Inference/` 和 `tufa-arc-agi-framework/`，保留完整目录结构。不要上传 working_output 或模型权重作为源码。
2. 保留原 bundle Dataset：它仍供应其余依赖源码、`deploy_target.pkl`、`benchmark_initial.pkl` 等部署资源。
3. notebook 自动定位唯一包含新增 workspace 模块的项目目录；多份候选时在运行前设置 `ARC3_SOURCE_ROOT` 指向选定项目目录，避免默默加载错误版本。
4. 新源码优先于原 bundle。导入时核对 inference/taaf 路径；如果 kernel 已缓存旧模块，会报错要求重启。
5. `/kaggle/working/source_manifest.json` 保存实际导入路径、Python 源码哈希和三个实验开关。

未在本机运行 Kaggle GPU/完整 benchmark；这里没有对应模型服务和比赛运行环境。

## 5. 验证和实验安排

本地测试命令（项目根目录）：

```sh
PYTHONPATH=ARC3-Inference python -W error::ResourceWarning -m unittest discover -s ARC3-Inference/tests -v
```

28 项测试全部通过，覆盖真实子进程 RPC、数据拷贝/类型/容量、超时与异常、跨关与跨游戏清理、保留函数读取工作区、反例与修正规则、空覆盖/模型异常、边界转移、回测无动作副作用、功能关闭及 prompt 合约；还包括 notebook 语法和源码发现逻辑。测试暴露的沙箱 subprocess 管道未关闭问题已一并修复。测试不代表模型得分不退化。

额外使用 cd82 的真实历史检查故意错误的“不变”规则：16 条转移中报告 3 个反例，未执行游戏动作。见 [接口检查结果](../analysis/backtest_real_history_smoke.json)。该检查仅验证历史输入与反例输出链路，不是新 solver 的成绩评估。

下一轮仍应单项对照，固定游戏、顺序、硬件与总时间；比较关卡数、得分、后续关卡成本以及实际工作区/回测使用情况。当前 notebook 是 C1=1/G1=1/Q2=0。先完成当前对照并补充原方案复测，Q2 单独验证，不与新能力混改。完整优先级见最新分析。
