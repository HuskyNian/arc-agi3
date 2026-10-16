# ARC AGI 3 开发计划与实验记录

持续记录方案、实现、实验条件和结果。当前状态（2026-10-16 清理后）：旧工作区、历史回测、精简 prompt 的实现、专属测试、沙箱接口和配置开关已删除。P1停滞反馈、P2逐步验证执行保留并在 notebook 中开启；剩余20项测试通过，未跑Kaggle成绩。新功能关闭时系统prompt与A0逐字一致，所有notebook代码格编译通过。模型、serving、调度和预算不变。运行说明见 [新实现说明](docs/strategy-and-execution.md)，历史结果与失败记录保留。

## 开发约定

- 运行模式审计：`TRUE_SUBMISSION` 同时影响游戏来源、pass 数、会话并发、时间预算和诊断，并非仅切换 gateway。详见 [第二次运行报告](analysis/second_run.md)。待实现：将真实比赛模式与诊断等级、实验预算解耦；作为独立实验验证日志开销，不与 prompt 消融混改。

- 以固定硬件、固定总运行时间下的得分和关卡完成情况为主要指标；tokens/s 是辅助指标。
- 每次实验明确源码版本、notebook 版本、配置、游戏集合、顺序、pass 数和时间预算；单项改动对比，保留失败结果。
- 重复运行报告均值和波动，不按游戏挑最好结果拼分；调度器共享预算时，不把各 pass 当成完全独立的运行。
- 不往 prompt 堆长篇要求、重复解释或强制反思。统计和日志留在宿主端，不加入模型上下文。
- 不因 token 多就认定过度推理；区分有效分析、重复推理、只读计算、失败工具调用和输出截断。
- 不首先降低 thinking 或删除 thinking 历史；不同时改模型、prompt、上下文、调度和工具。
- 保持真实探索、死亡和重置的动作成本；不以学习后重新开整局的结果替代比赛首次接触成绩。
- 每项任务记录“待实现 / 已实现未验证 / 已验证 / 放弃”。未跑分不得写成已有效。

## 当前方案与资料

- 模型：Qwen3.8-Flash-Next，W4A16 AutoRound；SGLang / Pennyroyal，MTP 推测解码。
- Notebook 配置：harness 128 Ki 上下文，预留 12 Ki 输出；保留 thinking；批量裁剪旧历史；最多 10 个活跃游戏流。
- 工具：Python 沙箱、棋盘与历史、最近动作动画、差分、UNDO、动作保护；同游戏保留合格函数和支持的 import。
- 普通变量不隐式跨调用保留；沿用原有函数保留机制。旧 workspace/backtest/compact 实验实现已删除；当前增加停滞反馈与 execute_plan，结构化文字 world model 仍关闭。
- 用户计划将修改后的源码上传 Kaggle Dataset，直接加载，移除 notebook 的 harness patch。上传后的路径和实际导入来源仍须在 Kaggle 验证；bundle 中的 pickle 等部署资源也须保留或另行构建。
- 仓库原作者的 `WRITEUP.md` 记录公开成绩 27.89；用户描述当前约 30 分。现已取得 working_output 完整产物：本地这份 benchmark 均分 47.28；不等同于隐藏集排行榜成绩。
- 框架图：[PNG](docs/images/framework-runtime.png)、[SVG](docs/images/framework-runtime.svg)、[Mermaid](docs/architecture.mmd)。

参考研究（2026-10-13 调研）：

| 来源 | 主要可迁移部分 | 使用边界 |
| --- | --- | --- |
| [Schema](https://arxiv.org/html/2609.39140v1) | 历史回测、程序内搜索、执行时预测验证 | 前沿模型公开集实验，不等同于当前单卡预算 |
| [Tycho](https://arxiv.org/html/2607.28287) | 按需建模、历史驱动隐藏状态、预测覆盖率 | 自动频繁修复并非最优；需计算建模成本 |
| [VISTA](https://vista-research.github.io/) | 历史帧、动画和局部区域按需检索 | 不必强制所有游戏先构建完整模拟器 |
| [NVIDIA AVO](https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/) | 持久记忆、停滞检测与纠偏 | ARC 结果来自技术文章；不是 Kaggle 隐藏集成绩 |
| [Kepler](https://arxiv.org/html/2610.00834v1) | 可审计证据、条件预测检查 | 论文明确区分最终重放与首次探索；不能复制其重放评分口径 |
| [Prime Agent](https://arxiv.org/html/2608.23552v1) | 持久工作区、程序化处理上下文 | 先迁移持久化，不照搬多 Agent 并发与自修改体系 |
| [可执行世界模型消融](https://arxiv.org/html/2607.15439v1) | 检验表示、简化和验证各自的成本收益 | 仅要求可执行模型不一定涨分；完整验证更昂贵 |

比赛依据：[Kaggle](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3)、[Competition Mode](https://docs.arcprize.org/toolkit/competition_mode)、[评分](https://docs.arcprize.org/methodology)。2026-10-13 核实：notebook 最多 9 小时，评测断网；Competition Mode 每环境只能创建一次，只允许关卡重置，不能重新开整局。公开集满分不代表隐藏比赛集满分。

## 2026-10-13 开发记录

### 已完成

- [x] 检查原 notebook 的 patch 加载路径；patch 涉及的 16 个本地文件与补丁目标版本匹配。
- [x] 保存并检查框架运行图。
- [x] 调研上述方法并确定渐进改造方向。
- [x] 核对用户提供的 Kaggle 初期日志及本地统计实现。
- [x] 建立本 TODO。当前没有改动运行代码、模型配置或 prompt。

### 基线 A0 的初期日志

来源：用户提供的 Kaggle 输出；非本地实测。benchmark 开始时间日志为 `2026-10-13 16:05:47`，该时间的时区未另行核实。

| 项目 | 观察值 |
| --- | --- |
| 游戏 / passes / runs | 25 / 4 / 100 |
| solver concurrency / 活跃流上限 | 100 / 10 |
| 每游戏运行上限 | 29018 秒，约 8 小时 3 分 38 秒 |
| 请求日志 | `save_request_logs=True` |
| 状态 | in progress；won=0 |
| 平均分 / 中位数 | 0.45 / 0.00，均为早期进度值 |
| 已计入动作 | 374 |
| 已计入生成 tokens | 357538 |
| generated tokens/sec | 591.76，以 benchmark job elapsed 为分母 |
| total wallclock | 5248.9 秒，各游戏已记录耗时之和 |
| 实际 benchmark 经过时间 | 357538 / 591.76 ≈ 604.19 秒，约 10.07 分钟；由日志反推 |
| GPU 显存 | 启动后 91.1/95.6 GiB；交互时 93.4/95.6 GiB，约 97.7% |
| 系统 RAM | 107.0 → 112.3 / 176.9 GiB |
| notebook 进程 RSS | 0.3 → 0.7 GiB；不包含独立 serving 进程 |
| 线程 / fd | 约 161–163 / 78–83；仅当前进程，不是 GPU 并发请求数 |
| working 输出占用 | 0.0 → 0.2 / 19.5 GiB |

解释和限制：

- `total wallclock` 由每个 run 最后一次动作时间与结束时间中的较大值求和；包含并发重叠，也不是 GPU 忙碌时间，不能直接作为 job elapsed。
- `total tokens` 在此摘要中实际是生成 tokens，不是输入加输出。进行中的统计来自动作记录；未落到动作记录或结束记录的生成可能尚未计入。
- per-game 是四次 pass 的平均。例如 `levels=0.2` 可以来自 1/4=0.25 格式化为一位小数，不能当成完成了 0.2 个关卡的单次运行。
- 100 个会话由 10 个活跃名额调度；其余等待。早期零 tokens、零动作大多与尚未获准推理相符，但需后续调度数据排除长期饥饿。
- warmup RESET 是 notebook 配置的启动保活动作；该行本身不证明服务启动失败。
- 约 956 generated tokens/action 仅为早期全局粗比值；包含机制探索、代码与推理，不能直接判定过度推理。
- 591.76 tokens/s 与原作者早期运行报告的 609.0 同数量级，但配置、上下文阶段和计数时点不同，不能据此测出退化或极限。
- 显存接近容量上限，但没有 GPU busy、功耗、频率、缓存命中、实际 decode batch、MTP 接受情况，不能判断推理到达极限。
- RAM 增长可能来自历史、页缓存或 serving；当前日志不足以定位，也不足以认定泄漏。
- 以上是早期快照的判断；最终结果已在 2026-10-14 回填，详见下方记录与分析报告。

源码依据：`taaf/diagnostics.py` 的 `run_summary_text`、`_total_tokens`、`_total_wallclock`；`tool_agent.py` 的请求记录与 priority gate；notebook 的 monitor 与 serving cell。

## P0 先补观测，不改变模型行为

状态：待实现。先复用现有输出，再补缺失字段；日志不进入 prompt。

- [x] 取得 A0 的 `benchmark.json`、`diagnostics.html`、`serve.log`、100 会话请求与轨迹，保存在 working_output；分析完成。
- [ ] 后续运行固定并记录实际 notebook/source 版本与哈希；本次没有不可变哈希可供逐字核对。
- [x] 已取得并分析同次运行的全量请求、transcripts 与动作事件。后续按样本保留大快照，全量保留轻量指标。
- [x] Notebook 启动记录实际导入的 inference / taaf 路径、源码哈希和三个新功能开关到 source_manifest.json；已测试源码发现逻辑，Kaggle 实际加载待验证。
- [ ] 明确输出 `job_elapsed_s` 与 `sum_recorded_game_elapsed_s`，避免混淆；计数注明 completed responses / action-accounted 等口径。
- [ ] Notebook 宿主端每 10 秒采 GPU busy、memory read/write busy、显存、功耗、功耗上限、温度和 SM 频率，写入 CSV；每 60 秒只打印一行汇总。N/A 不视为 0，失败不影响游戏。
- [ ] 同步采 SGLang `/metrics`（以当前 Pennyroyal fork 实际暴露为准），保存可用的队列、活跃请求、缓存、prefill/decode、MTP 数据；缺失字段明确标记 unavailable。
- [x] 已聚合 serve.log 的请求时间、缓存、活跃批次和 MTP：缓存约 93.4%、accept len 样本均值 2.68；无需重复添加已有服务日志。
- [ ] 增加轻量 request metrics：请求 ID、游戏/pass、关卡、单调起止时间、prompt/completion/cached tokens、finish_reason、重试/超时、上下文裁剪。无缓存字段不记作 0%；按 response/request ID 去重。
- [ ] 缓存指标从实际 response usage 或 serving 取得：当前 `solver.py` 调用游戏记账时传入 `uncached_input_tokens=0`，不能据此推断未缓存输入为零或缓存命中率 100%。
- [ ] 增加宿主端回合统计：只读工具调用、动作调用、实际动作、Python 错误、保护触发、死亡和关卡推进。复用已有事件，不复制完整棋盘或历史到指标文件。
- [ ] 记录“连续未执行动作的生成 tokens/时间”及其工具结果，区分有效检查与无进展循环。优先用人工抽样核实，暂不自动中断推理。
- [ ] 记录调度等待、已获名额、真正 in-flight 请求、handover 与首次动作时间。不要把 100 个已创建会话当成 100 个 GPU 请求。
- [ ] 当前 `ARC3_DIAG_CONCURRENCY` 最快每秒打印且带逐游戏列表；长期跑前改成低频聚合，不直接全程开启刷屏。其内部计数也需核对含义后再命名展示。
- [ ] 控制完整请求快照体积：现有日志重复包含整段 messages，后续支持抽样/限量；优先保留轻量 metrics，避免占满 working 的约 19.5 GiB。

验证：统计改动使用合成 usage、并发耗时和缺失字段检查计数；短跑验证写盘开销、输出量及异常隔离。不要为文档或监控显示格式添加重型测试。用相同条件比较观测前后的耗时，确认没有明显拖慢。

## P3 历史动画按需检索（B1，优先级后移）

状态：待实现。前置：P0 数据足以建立基线。

- [ ] 将最近动画的单槽存储扩展为按 game/pass、level、action 编号索引的宿主端存储，保留动画序列顺序。
- [ ] 提供按编号读取动画、取指定帧和指定区域的简单接口；复用已存原始事件，避免不必要的副本。
- [ ] 默认不额外向 prompt 注入动画图片或 timeline；只按需读取，并限制输出大小。
- [ ] 必要说明保持一句，例如：“可按动作编号读取过去的动画；怀疑遗漏瞬时变化时再查看。”不增加逐轮必须检查动画的要求。
- [ ] 分开标记正常决策帧、动画帧、死亡帧、重置帧和新关卡帧，避免构造不存在的转移。
- [ ] 验证可跨动作检索、顺序正确、死亡/重置证据不覆盖，以及存储上限和清理策略。

判定：同预算下得分/关卡完成是否改善；历史动画是否被使用；是否发现新机制；额外 image tokens、工具耗时和内存是否抵消收益。动画相关游戏可用于调试，但全 25 游戏回归才作为保留依据。

## P1 首个行为实验：受控持久工作区（C1）

状态：已实现、通过本地行为测试、未验证得分。通过显式 workspace.put/get 保存 JSON 数据，沿用独立沙箱和原有函数保留。完整日志中已有 sp80 的 CUR 丢失案例；205 次 NameError 不全属于状态丢失，不能宣称都可修复。

- [x] 同游戏保存合格函数与显式 game 数据；level 保存关内数据，observation 保存当前状态相关缓存/计划。
- [x] 显式、有容量限制的 put/get；复制读写，失败写入不覆盖旧值，成功写入可跨后续异常/超时保留。
- [x] 宿主根据真实 level/observation 清理过期数据，提供 expected_version 防止旧观测写入。
- [ ] 规则 model 版本依赖的缓存自动失效；目前由模型显式更新/删除，无隐式依赖管理。
- [ ] 与当前函数保留机制比较重复生成 tokens、工具错误、内存和固定预算得分。

## P4 可选预测验证执行（D1）

状态：待实现。

- [ ] 在现有批量动作保护上加入预测断言：执行一步、比较实际结果、发现矛盾就停止剩余计划。
- [ ] 从关键实体位置、物品、终止条件等可检查预测开始；不用每次预测全图。
- [ ] 记录覆盖范围和关键动态区域，避免只预测静态背景导致虚假高通过率。
- [ ] 未知机制允许显式探索，不把无法预测等同于禁止行动。
- [ ] 比较矛盾后浪费动作、误停止、死亡、关卡完成与总耗时；不能只报告预测准确率。

## P4 按需世界模型与搜索（E1）

状态：候选，需前述实验证据。

- [ ] 提供稳定的 state / step / render / outcome 接口，支持从历史携带隐藏状态。
- [ ] 提供有节点数、时间、深度限制的通用搜索；点击游戏缩减候选动作集合。
- [x] G1 已提供 backtest(predict, observe) 按需回放当前关历史并返回有限反例；不是自动每轮验证，历史一致不视为未观察状态已正确。
- [ ] 只在规则可复用、组合规划困难、预计能节省动作时建模；修复成本过大可退回直接推理。
- [ ] 暂不强制每游戏建立模拟器，不照搬固定多 Agent 或每轮审核流程。

## P5 后续按数据决定

- [ ] 只有 GPU/服务数据表明确有瓶颈时，分别测试 active streams / MAXREQ、MTP 步数、上下文裁剪与缓存；不得只追求显存更满。
- [ ] serving 测试固定请求工作负载与长度分布，并覆盖上下文裁剪后的 prefill；最终用游戏分数—时间曲线复核。
- [ ] 卡住时的一次性诊断与策略切换；不加每轮长反思 prompt。
- [ ] 调度加入可核实的进展/停滞信号；不使用模型自报“快成功”作为唯一依据。
- [ ] 如果确认有大量 `finish_reason=length` 且无工具调用，再单独测试推理预算/更短工具引导；不预先关闭 thinking，也不把缩短输出当成必然提效。

## 截断恢复与分步计算（F1，保留候选）

状态：待实现，与 C1 分开验证。

- [ ] 101 次 length 响应均达 12288 tokens，消耗 124.1 万 tokens；抽样定位截断后是否重复推导、能否继续执行。
- [ ] 仅在重复截断/长期无动作时测试一次性简短反馈或可续算的计算接口，不添加每轮长反思。
- [ ] 不把 reasoning 占 87.1% 等同于无效推理；不直接全局关闭 thinking。
- [ ] 若修改单请求输出预算，单独做消融，记录截断率、恢复成本与得分。

## 实验执行顺序与结果表

完整 25×4 基线已完成。执行顺序更新：A1 最小观测 → 配对短基线 / C1 → G1 → 按证据推进 G2；G0 可独立短筛，H1/F1/B1 保留候选。G1/G2 是原 D1/E1 的具体分阶段实现，不另建一套重复工具。各项先独立验证。后续短实验可用固定 25×1：同硬件、10 个活跃流，依现有每会话预算缩放得到 `532*60*25//110 = 7254` 秒（约 2 小时 1 分）；这只是筛选配置，并非完整 25×4 调度过程的等价替代。固定启动顺序与所有预算设置，必须先跑相同短预算基线，不能直接与 47.28 比较；候选先短筛，再复跑和完整回归。

| ID | 改动 | 条件 | 状态与结果 |
| --- | --- | --- | --- |
| A0 | 原始基线 | 25×4，100 会话，10 活跃流，29018 秒上限 | 已完成：47.28 分，33/100 通关，410/732 关，8h11m53s，611.18 generated tokens/s；分析见 analysis/README.md |
| A1 | 仅观测增强 | 模型行为与 A0 一致 | 待实现；先检查性能开销与计数准确性 |
| B1 | 仅历史动画检索 | 与对应基线同预算 | 待实现，优先级后移至 P3 |
| C1 | 仅持久工作区 | 单独对比，再考虑组合 | 已实现，本地测试通过；Kaggle 得分未验证 |
| F1 | 截断恢复 / 分步计算 | 与 C1 分开验证 | 待实现，保留候选 |
| G0 | 精确棋盘只读接口 | 独立短筛，不增加完整棋盘输出 | 待实现 |
| G1 | 普通规则函数的按需历史回测 | 代码沿用函数保留，无额外注册 DSL | 已实现，本地与真实历史负例检查通过；未验证涨分 |
| Q1 | 精简 prompt | 保留 thinking 和 token 上限，独立开关 | 已实现，系统字符数 18467→5320；无实测推理加速 |
| G2 | 持久搜索、执行检查与跨关复用 | 根据 G1 结果推进，承接 D1/E1 | 候选 |
| H1 | 卡住后的推理上下文重建 | 同一环境，保留成本；与同预算继续推理对照 | 候选 |
| D1 | 仅预测验证执行 | 单独对比，再考虑组合 | 待实现 |
| E1 | 按需模型与搜索 | 以前述结果决定 | 候选 |

每次结果追加以下字段：

```text
日期 / 实验 ID：
源码与 notebook 版本 / Dataset 版本 / 配置差异：
游戏集合、顺序、pass 数 / seed（如支持）/ 预算 / 硬件：
启动耗时 / benchmark 实际耗时 / 是否正常结束：
最终均分、各 pass 分数 / 完成关卡与游戏：
累计与分阶段生成吞吐 / 输入与缓存 tokens / 重试及超时：
动作、死亡、保护触发 / 无进展推理 / 工具错误：
新增工具使用次数、耗时与实际帮助的案例：
内存、显存、磁盘峰值 / 产物路径：
保留或回退决定 / 证据 / 下一步：
```

GPU 指标定义参考：[NVIDIA nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html)。显存已用量、GPU kernel busy 与 memory read/write busy 是不同指标；后两者也不等于理论 FLOPS 或内存带宽利用率。服务指标参考 [SGLang](https://docs.sglang.io/docs/references/production_metrics)，实际字段须以 notebook 固定的 fork 为准。

## 2026-10-14 完整基线分析记录

- [x] 分析 working_output，创建 [分析报告](analysis/README.md)、汇总脚本、逐游戏/会话/关卡/请求/服务 CSV 与图表。
- [x] 从动作数和完成关数独立重算全部 100 个分数，与 benchmark 一致。
- 关键发现：固定完成关数的均分上限 49.04，当前 47.28；优先帮助多过关。
- 8768 次 Python 调用，754 次返回 traceback；205 次 NameError 中仅部分可由持久工作区解决。
- 101 次输出截断消耗 6.72% 的客户端生成 tokens；作为定向优化候选，不把全部推理视为浪费。
- 服务缓存约 93.4%，MTP accept len 均值 2.68；没有 GPU busy / 功耗时间序列，不能证明已到极限，也没有证据优先大改 serving。
- 四个 pass 均分 50.78 / 56.32 / 44.25 / 37.77，共享调度且得到的生成预算不同，不能当成四次等算力独立重复。
- 本次只增加分析与计划文件，没有改 notebook、运行源码、prompt 或模型配置。所有行为实验仍为待实现/未验证。

### 较大改进方向再评估

- [x] 根据用户要求重新检查机制探索、几何表示、搜索与复用；保存 [设计讨论](analysis/high_upside_changes.md)。
- 修正判断：修复 NameError 不是大幅涨分的充分理由；C1 作为基础，为可运行规则、搜索状态和跨关解法提供持久化。
- 主要能力实验上调为 G1/G2：用具体历史反例修正规则，再搜索、执行和跨关复用；按需启用，不强制所有游戏构建完整模拟器。
- G0 检验精确网格接口；H1 检验保留事实和成本的推理上下文重建。均未实现，不重开环境、不拼接最好分数。
- 不添加长流程 prompt，不以减少 reasoning tokens 本身作为成功标准。

## 2026-10-15 实现记录：C1 / G1 / Q1

- [x] C1：新增 workspace.py，独立宿主工作区，game / level / observation 三种生命周期；不共享游戏/pass，不序列化整个解释器。
- [x] G1：新增 rule_backtest.py，Python 提供 backtest；采样、字段覆盖、反例上限和跳过边界明确；回测禁止真实动作、workspace 写入和实时动画请求。
- [x] Q1：新增 compact_prompt.py；API 只解释一次，移除逐轮重复检查清单和无上限调查要求。新能力按需，不强制反思、建模或回测。
- [x] Notebook：移除旧 patch 执行，自动发现源码 Dataset，优先导入新代码，保留原 bundle 的部署资源，保存 source_manifest.json。
- [x] 修复测试暴露的沙箱 subprocess 管道未关闭问题；超时/异常路径也回收资源。
- [x] 26 项测试全部通过（含真实沙箱子进程、功能关闭、源码发现与 prompt 合约）；ResourceWarning 设为 error。
- [x] cd82 真实历史负例检查：16 条转移中识别 3 个反例，无游戏动作；这是接口验证，不是模型能力跑分。
- [x] 三个新开关全 0 时，生成的系统 prompt 与 A0 配置下旧文本逐字一致。
- [x] 系统 prompt 18467→5320 字符（约 -71.2%），示例首轮用户 prompt 1811→199；不将字符减少等同于 token/s 或得分提升。
- [ ] Kaggle 配对消融：全关 → 仅 C1 → C1+G1 → C1+G1+Q1；同游戏/顺序/总预算，记录新增工具的实际使用及成绩。

实现与运行说明：[workspace-and-backtest.md](docs/workspace-and-backtest.md)。测量：[prompt_comparison.json](analysis/prompt_comparison.json)；真实历史接口检查：[backtest_real_history_smoke.json](analysis/backtest_real_history_smoke.json)。

### 源码 Dataset 路径

- 用户已上传源码到 `/kaggle/input/datasets/zhuzhumiao/nian-arc-agi3`；notebook 第一个代码 cell 已将其设为 ARC3_SOURCE_ROOT 的默认路径。
- 仍可用环境变量覆盖；假设 Dataset 根目录直接包含 ARC3-Inference 和 tufa-arc-agi-framework，实际 Kaggle 目录与导入结果待运行验证。

## 第二次完整运行：C1 + G1 + Q1

- [x] 分析 working_output2：相同 25×4，均分 47.28→39.89（-7.40），通关 33→25，完成关卡 410→390，动作 20670→22937。
- [x] 全部 200 个前后成绩重算一致；时长约 8h12m，游戏 ID、关卡数、基准动作数相同。
- [x] 根据用户配置，三个新开关均为 1；TRUE_SUBMISSION=False 不会关闭功能，不应为启用功能手动切成 True。
- [ ] 缺 source_manifest.json、serve.log、transcripts 和动作事件；无法核实实际启用/调用频率或归因。
- [ ] 下一轮仅将 ARC3_COMPACT_PROMPT 设为 0，其他条件固定；再视结果单独消融 G1/C1。本轮分析未修改实际开关。
- [ ] 优先检查 tr87、ft09、cd82 退化轨迹与 sp80/dc22 改善轨迹。
- 当前决定：不保留“已改善”的结论；字符减少不代表推理加速，工程测试不代表模型成绩不退化。

详见 [第二次运行报告](analysis/second_run.md) 与 [逐游戏比较](analysis/second_run_games.csv)。


## 2026-10-15 第三轮中途复核与 Q2

- [x] 识别混合产物：working_output2/logs.md 是15:02新运行的中途日志，benchmark.json仍是00:52旧运行；不可拼成完整第三轮。
- [x] 新增 analyze_third_progress.py，还原21个同预算时间检查点；最新约3h31m：A0 23.69，全开19.64，关Q1 21.68。历史200个最终分数重算通过。
- [x] 复核 AVO、Tycho、Schema、VISTA、Workspace Optimization 原始来源，记录可迁移机制、模型/公开集边界与规则核实缺口。
- [x] Q2：原系统prompt构建后才做17组措辞替换、3组条件去重；恢复原逐轮/换关/死亡/摘要/函数提醒。19979→19006字符（-4.87%），全关与A0文本逐字一致。
- [x] 源码默认Q2=0，notebook仅第一个代码cell（JSON index2）的compact配置改为0；C1/G1仍1。
- [x] 28项本地测试通过；新增分支合约、原用户prompt保留、prefix不改写检查。未运行新Kaggle实验，不声称语义或成绩绝对不变。
- [ ] 收齐第三轮最终benchmark、manifest和失败轨迹；后续每轮使用独立目录。
- [ ] P0：同条件原方案对照、工具实际使用及等待/服务耗时记录。
- [ ] P1：停滞事件先shadow统计，再单独测试短反例反馈；避免每轮强制反思和误把搜索/排队当停滞。
- [ ] P2：版本化计划 + 每步预测检查 + 首个不匹配停执行；不强制所有游戏建模。
- [ ] P3：同游戏跨关技能与适用条件、机制多标签检索；精确网格读取另做观察接口实验。
- [ ] P4：开发阶段跨游戏提炼冻结通用技能；评测时在线共享须先核实明确规则，当前保持隔离。

报告：[策略复核与优先级](analysis/strategy_revision_2026-10-15.md)。Prompt：[当前完整文本](analysis/prompt_v2_conservative.txt)、[逐行差异](analysis/prompt_v2.diff)、[审计](analysis/prompt_v2_audit.json)。


## 2026-10-16 撤回旧实验，实现 P1/P2

- [x] C1/G1/Q1/Q2 默认与 notebook 配置全关；不分配工作区，不给模型旧接口说明，历史代码/测试保留复现。
- [x] P1：新增 strategy_monitor.py。连续3次相同状态/代码下的错误、保护拒绝、预测反例或相同只读输出，给具体证据和下一步建议；8次工具调用冷却，最多8条近期证据。off/shadow/on独立开关。
- [x] 不以没升关、像素变化、单次长推理或排队等待判定停滞；不自动重开游戏、不硬性放弃关卡、不增加监督LLM。
- [x] P2：新增 verified_plan.py 与沙箱 execute_plan。1..16步，预测/观测只读，每步真实动作后验证；不符、错误、拒绝、换关或死亡停执行，余下snippet动作锁住，原保护和动作成本保留。
- [x] 新功能不依赖旧workspace/backtest；正确计划连续执行不经过额外LLM调用，无可靠预测时仍可直接action探索。
- [x] 宿主无条件保留计划报告（即便模型忽略返回值），按游戏/pass写strategy/*.jsonl，包含配置、会话/调用编号、状态和代码指纹、tokens、工具耗时、动作数、触发及计划事件。
- [x] 新增 analysis/summarize_strategy_run.py 汇总小日志；无需完整请求日志即可看使用率和中断类型。
- [x] notebook第1代码cell（index2）：旧三项0，新monitor=on、verified_plan=1；第4代码cell（index8）：新模块导入核验与manifest五开关。模型/serving/调度/预算未改。
- [x] 45项本地测试通过，含真实sandbox与宿主动作/状态刷新链路、超时动作记账、停止锁、隔离与反馈冷却；全部notebook代码格编译通过。
- [x] 全关系统prompt与A0的18467字符逐字一致；P2仅追加918字符说明，P1无静态prompt。完整文本在analysis/prompt_strategy_execution.txt。
- [ ] 更新Kaggle Dataset、重启kernel后跑真实游戏；本地验证不代表上分。
- [ ] 原方案、shadow、仅P1、仅P2、组合分别做匹配预算实验；下载manifest/benchmark/strategy目录到独立run目录。

实际能力边界：P1只处理工具链中可核实的重复证据，不自动理解纯推理循环；P2只验证声明字段，不保证完整世界模型或目标正确。完整说明：[strategy-and-execution.md](docs/strategy-and-execution.md)。


## 2026-10-16 删除停用实现

- [x] 删除 workspace.py、rule_backtest.py、compact_prompt.py、旧专属测试 test_workspace_backtest.py。
- [x] 删除失效审计脚本 analysis/audit_prompt_v2.py 和旧精简源码快照 analysis/compact_prompt_v1_source.txt。
- [x] 移除宿主实例/同步/调用、沙箱嵌入源码/RPC/回调分支及旧三个配置开关；新验证回调继续独立保持只读保护。
- [x] notebook第1、第4个代码cell移除旧配置及manifest字段，只保留两个新实验开关。
- [x] 删除旧模块字节码；代码引用扫描无悬空依赖。历史跑分分析、prompt文本对比和开发过程记录保留，旧说明明确标记失效。
- [x] 剩余20项测试通过（旧功能专属25项随实现删除），全部notebook代码格编译通过，原始prompt逐字一致核验通过。
