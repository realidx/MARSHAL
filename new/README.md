# `new/` 导航

## 当前工作

- [2026-10-16 v5训练准备与遗漏](terminal_node_grpo_readiness_20261016/README.md)：同节点8采样、连续regret、节点GRPO已实现；CPU验收，GPU smoke待执行。当前启动命令见[训练入口](../examples/strategic_slices/TERMINAL_TRAINING.md)。

- [2026-10-16训练protocol文献核对](../examples/strategic_slices/TRAINING_PROTOCOL_REVIEW_20261016.md)：原论文的reward、advantage与归一化选择；连续反馈的最优解/KL区别，以及先验证binary同state基线的建议。研究草案，不是新训练结果。

- [Strategic slices 当前进度](../examples/strategic_slices/PROGRESS.md)：terminal v4 已完成真实 D（6,400 trajectories、6,200 terminal）及 100 题选择（56 parents / 37 families）。单 H100-96 smoke/resume 已通过；训练暂停于 550 updates / 3,500,783 tokens，尚未完成 6M。best/latest 的 terminal 与全部 24-case CalBench 导出评测及原始轨迹已归档，见 [执行与审核](terminal_hf_test_calbench_20261008/README.md)。
- [数据与训练主导航](../examples/strategic_slices/README.md)：当前 terminal reference、D、选集、训练合同及历史 bounded/terminal-reward 方案；分别见 [D 与选集](../examples/strategic_slices/TERMINAL_D.md)、[训练合同](../examples/strategic_slices/TERMINAL_TRAINING.md)。
- [550 次更新与全部验证曲线审核](terminal_training_review_20261008/README.md)：中期输出失稳、后期验证下降与调查入口信号不足；完整统计/曲线/复现脚本，以及新 v4 的 20 题 batch、500K 验证和 1M 恢复保存修订。
- [Strategic game slices checkpoint](strategic_game_slices_checkpoint_20261001.md)：当前讨论的定义、pilot 证据与下一步实验提案；新对话从这里开始。
- [双人 BENAC slice pilot](benac_slice_pilot/README.md)：C/S 计算、连续窗口与模型 D 探测流程。
- [井字棋 slice pilot](tictactoe_slice_pilot/README.md)：早期概念与初始模型诊断，不是最终游戏。

## 历史笔记

原先散放在 `new/` 顶层的 52 份旧笔记与配套 JSON 已按主题移至：

- [训练与运行环境](notes/2026-09/training_runtime/)
- [游戏与数据设计](notes/2026-09/game_design/)
- [评测与 CalBench](notes/2026-09/evaluation/)

仅调整了这些笔记的位置。仍被其他文档或工具引用的协议文件保留在 `new/` 顶层，例如 [研究计划](plan.md)、[语义诊断协议](semantic_diagnose_protocol.md)和 [CalBench 评测协议](calbench_formal_evaluation_protocol_20260918.md)。

## 代码与证据

`diagnostic_v*` 等版本化目录之间存在 Python 导入关系；各 `*_evidence_*`、`*_results_*` 目录承载原始证据或复现材料，因此保留原路径。[论文评测来源清单](../paper/calbench_transfer_inventory.md)也直接引用了部分证据包。`local_data/` 是被 Git 忽略的本地生成数据，不会随 Git 同步。
