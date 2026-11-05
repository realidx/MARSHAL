# Native800远端D runner v1

2026-11-05，父版本native800-prompt-score-v4。用户授权接入，明确“不用做验证，接入后远端server跑”。本版不执行CPU／mock／GPU／模型测试，不将既有v4题面CPU检查当成本runner验证。

运行合同、全部参数和远端命令见[远端说明](../../NATIVE800_D_REMOTE_20261105.md)与本目录SNAPSHOT.json。只新增D执行器，不改prompt-v4、具名工具、scorer-v1、主Q/S、800成员、父池、GRPO或旧生产active。

每题8独立posterior world draw，当前玩家从入口行动到原生终局，其余玩家按冻结reference。原生child编号靠既有IndexedReference子树几何计数导航，不重求Oracle、不展开完整树。不重置到父先验、不使用旧固定k窗口。

own terminal D与入口协议评分分列，后续节点只检查原生合法性，不新计算后续Q/S。本版本不实现训练collector或SP训练臂。32并发完成即补位，父游戏间顺序运行并复用同一reference；不是固定32整批等待，也不声称跨父全局满并发。

逐完成轨迹原子gzip记录、严格身份恢复；基础设施失败单独停机留证。无效/截断不自动重试，不补造终局utility。新run完整pipeline_snapshot保留CLI覆盖、实际配置、源码与模型/input身份、环境、采样/评分合同。没有最终100自动选择，validation只用于诊断。

交付自包含transfer archive，不包括模型权重、完整历史标签profile或日志；已冻结入口JSONL带所需Q，父游戏原生job/reference随包。打包只作文件归档/hash，不是运行验证。后续源代码若需修复，必须另留版本，不覆盖旧关闭快照。
