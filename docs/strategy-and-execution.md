# 停滞反馈与逐步验证执行（2026-10-16）

本轮恢复原 prompt 作为基础。C1 工作区、G1 历史回测、Q1/Q2 精简的实现、沙箱接口、专属测试和开关已删除；只保留历史分析记录。新功能独立运行。

## 配置与 Kaggle 使用

| 开关 | 源码默认 | 当前 notebook | 作用 |
| --- | --- | --- | --- |
| `ARC3_STRATEGY_MONITOR` | `off` | `on` | `off` 不监控；`shadow` 只记日志；`on` 增加短反馈 |
| `ARC3_VERIFIED_PLAN` | `0` | `1` | 提供 `execute_plan` |

更新源码 Dataset，然后重启 Kaggle kernel，从头运行。路径仍为 `/kaggle/input/datasets/zhuzhumiao/nian-arc-agi3`，原 bundle 仍需挂载。

Notebook 修改了两处：

- 第一个代码 cell（JSON index 2，总第3格）：移除旧三项开关、开启新两项；自动发现及校验使用 `strategy_monitor.py` / `verified_plan.py`。
- 第四个代码 cell（JSON index 8，总第9格）：校验新模块实际导入路径，`source_manifest.json` 保存两个新开关及源码哈希。

模型、serving、温度、thinking、调度和运行预算未更改。源码默认新功能关闭便于独立使用；notebook 按本次请求启用两项。两个新开关关闭时，系统 prompt 与 A0 保存文本逐字一致。

## P1：有证据的停滞反馈

`StrategyMonitor` 保存在每个游戏 agent 内，记录工具调用编号和最多8条最近同类证据，不调用额外模型，不改变动作或重置游戏。

连续3次出现相同状态、代码/保留函数指纹、失败细节时触发：

1. 同一工具异常，且没有执行动作。
2. 同一动作保护拒绝，且没有执行动作。
3. 验证计划报告相同预测反例。
4. 相同只读计算返回相同输出，且未尝试动作。建议改变输入、搜索限额、探测假设或执行已有依据的动作。

每次反馈后至少冷却8次工具调用。新状态、代码变化、正常不同计算或关卡/死亡事件打断连续计数。每游戏隔离；不会把其他游戏经验注入本游戏。

反馈包含 `kind / tool_calls / count / detail / advice`。例如指出第几次工具调用再次出现同一预测反例，并建议检查预测规则或观测提取。正常计算不追加过程清单；成功搜索输出持续变化不触发。没有升关、像素发生变化、排队等待、单次长推理，均不单独作为停滞判据。

这版属于保守的纠错提醒。它不自动替模型选择新策略、不强制放弃关卡，也不检测没有工具调用的纯语言推理循环；这些扩大干预范围的实验以后单独验证。

## P2：短计划执行接口

```python
def observe(frame):
    # 此处必须是适用于当前游戏且经观察支持的提取函数。
    return {'player': locate_player(frame)}

def predict(frame, action_dict):
    # 此处必须实现当前假设，不能直接照抄 observe 作为预测。
    return {'player': predicted_player(frame, action_dict)}

planning_frame = current_frame
report = execute_plan(
    ['RIGHT', 'RIGHT', 'UP'], predict, observe,
    start=(planning_frame.level, planning_frame.step),
)
print(report)
```

上述 `locate_player` / `predicted_player` 是示意中的游戏相关函数，需要模型根据证据实现；接口不会假定存在玩家。

- 一次1至16步；点击格式同 `action`。`predict` 的动作参数始终是字典，例如 `{'action':'RIGHT'}`。
- `start` 必须匹配当前 level/step。只在本次调用中持有计划，不跨调用存储；新的代码/规则用于新调用。调用者应传入真正规划时的帧标识，而不是给旧计划填新标识。
- 每步先用 `predict(before_frame, action_dict)` 得到预期字段，再执行一个真实动作，调用 `observe(after_frame)` 检查结果。匹配则继续，无中间 LLM 调用。
- 首次执行前也验证观测提取能返回所需字段。回调返回非空、至多32字段的有限 JSON 字典，总字符上限8192；字段名不超过80字符。检查只覆盖预测字段。
- 回调得到帧副本，打印被抑制；回调不能调用动作或实时动画。它们必须使用传入帧及有依据的参数。此约束不构成对任意恶意 Python 的安全隔离，也无法证明模型没有用全局变量抄答案。
- 预测不符、回调错误、保护拒绝、死亡、换关或通关立即停止。停止后，同一 snippet 的后续动作被拦住，`except Exception` 不会绕过该停止。新 snippet 可根据反馈重新规划。
- RESET 必须单独用原 `action` 执行，之后基于重置后的观测计划。原 no-op、死亡、重复动作和终止保护继续生效。
- 无需可靠模型时仍可直接 `action()` 探测；不强制每步建模、回测或执行完整规划工作流。

返回 `complete / mismatch / prediction_error / observation_error / stale_plan / boundary / blocked` 等状态，及 executed/verified 计数、首个反例。原保护抛异常或输入校验失败会产生 `interrupted` 事件，并保留原异常。工具超时可能只留下 start 事件；宿主仍保留已经执行的动作。

即便 snippet 忽略返回值，宿主也把最后两份计划报告加入工具结果。终止事件优先于普通字段比较，避免把换关后的新布局误报成模型预测失败。

## Prompt 和成本

只在启用 P2 时追加一段 API 说明，原来的逐轮、换关、死亡和摘要指导保持不变。P1 无静态长提示，只在命中具体事件且处于 `on` 模式时给出反馈。

P2 使用既有30秒工具预算，不增加额外推理请求。每步动作会刷新真实状态并经宿主处理，比一次无校验批量动作多一些序列化/通信工作；收益应来自避免错误尾部动作及不必要的重新决策，不保证 GPU tokens/s 增加。

局部字段匹配不代表整个模型或目标正确。相同棋盘也可能隐藏不同状态，所以停滞提示只是证据提醒，不能成为自动禁止策略的理由。

## 诊断与下一次测试

日志写入运行目录的 `strategy/<game_id>_p<pass>.jsonl`，不存图像、完整棋盘或完整推理。每条包含会话ID、工具调用编号、状态/代码指纹、生成tokens累计数、工具耗时、已执行动作数、计划开始/结束、反例及是否发出反馈。每工具最多保留32条计划事件，溢出单独记数；写日志失败不会终止游戏。

把 `strategy/`、`source_manifest.json` 和最终 `benchmark.json` 一起下载，单独保存为新一轮目录。可以运行：

```sh
python analysis/summarize_strategy_run.py working_output3
```

这份汇总能判断新增工具有没有被调用、停滞反馈频率、计划中断原因；不能据此直接证明涨分。

建议匹配预算测试顺序：

| 组别 | monitor | verified_plan |
| --- | --- | --- |
| 原方案控制 | off | 0 |
| 检查监控误报 | shadow | 0 |
| 仅 P1 | on | 0 |
| 仅 P2 | off | 1 |
| 组合（当前 notebook） | on | 1 |

旧三项已移除，无需配置。少量游戏用于排错；完整开发集比较时固定顺序、pass数、时长和硬件。主要看总分、完成关卡、错误计划的后续动作成本、真实模型/工具开销，而不是只看推理字数或回调通过率。

## 本地验证

清理后保留的20项 unittest 全部通过，覆盖真实沙箱子进程、工具/保护边界、回调只读、预测不符后停止、成功计划连续执行、超时动作计账、原始反馈保留、宿主整条链路、shadow/on/off、冷却和游戏隔离，以及 notebook 源码加载。旧功能专属的25项测试随实现删除。全部 notebook 代码格编译通过，原始 prompt 逐字一致检查通过。尚未运行 Kaggle GPU/真实游戏的得分实验。
