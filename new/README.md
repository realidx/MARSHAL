# `new/` 导航

## 当前工作

- [直接行动 slices–SP 与当前 oracle 试验](../examples/strategic_slices/README.md)：`bounded-next-own-v1` 已冻结 100/20/40 个共享父游戏、659/128/248 个 slices，58 个 family 分离，正 S 父游戏 12/2/4。首版三人支持固定为 3 个世界，双人最多 27 个世界；训练入口与 CPU/mock 验收通过，真实模型信号和 GPU 更新待执行。
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
