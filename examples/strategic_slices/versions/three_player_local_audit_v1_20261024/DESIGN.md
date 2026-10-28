# 三人H2本地运行与标签核查v1

父版本`three-player-complexity-study-v1`。用户先要求“在本地先尝试跑一下”，
随后审阅前14次尝试，并于2026-10-24授权继续。
本版本记录实际CPU执行与核查，不替换父研究的关闭快照，不激活训练。

## 与父版本逐项差异

1. 实际在macOS本地执行冻结H2全部33个完整父游戏；原先只是远端准备及小样证据。
   H3/A2H2完整33局未运行，旧100未替换，第25局保持挑战身份。
2. 本地首次CLI覆盖：workers1、候选120秒、认证180秒、Q/S300秒、硬限720秒、memory_gb0。
   仅对原46/76进行独立重试：候选600秒、硬限1200秒，其余首次参数不变。
   这是两次运行的参数差异，不修改任何父版本默认值。
3. 保存后独立重载采用workers2、构树/认证各180秒、硬限420秒、memory_gb0；
   不重新搜索/修复profile、不重新测Q/S，检查序列化后认证。
4. 新增只读汇总脚本：冻结前14条结果；按首次认证优先合并重试；对严格最优调查的入口posterior检查目标支持。
   不按Q/S挑选reference，不把缺失计0，不按推断删除调查目标。
5. 原35增加两项固定reference诊断：调查后始终不给答案的完整后续策略重算，以及入口答案后验检查。
   它们是调查前通道诊断，不是当前节点S，不是替换原生对手的训练协议。
6. 使用父版本已有sequence LP检查新正S最大见证及遗漏策略平局区间；验证范围以实际完成记录为准。

## 保持不变

每人1承诺选项、全局两个隐藏偏好且分属不同玩家、9个world、2RR；调查1、提出即扣报价1；
独立均匀三值先验、公开历史和累积私有答案、response-only社会平局。
游戏完整原生terminal树、平局安全缩减、惯性BR+联合候选、epsilon1e-8、tie tolerance1e-9；
max_nodes600000、构树/缩减各180秒、max_sweeps512、joint_evaluations400、repair_passes8。
S为冻结对手下当前真实信息中逐条遗漏的完整后续策略损失；遗漏策略剩余平局均匀，
当前第一步regret另列，零counterfactual节点S缺失；不把调查前答案访问收益混为S。

认证是完整枚举树上的数值own-utility epsilon-Nash及声明离路径信念下的局部支持/回应平局检查；
不声称唯一、解析精确或形式化序贯均衡。

## 身份与限制

每次执行保存完整pipeline_snapshot、CLI、resolved config、输入/source hash、Python/NumPy/SciPy环境，
并拷贝父版本源代码。新增诊断脚本单独记录hash，在本版本闭合时一并注册。
macOS不施加Linux RLIMIT_AS，峰值内存、CPU核数未记录，不能推算为远端资源需求。
新source注册只闭合既有运行的来源证据，不回写或替换实际运行时的父版本snapshot身份。

训练算法、reward、advantage、采样、评测、保存恢复和模型运行均未变更或执行；
生产active仍`terminal-node-regret-grpo-readable-v8`。D未测，prompt未修改。

实际结果见[后续报告](../../LOCAL_THREE_PLAYER_FOLLOWUP_20261024.md)，
此前[前14条回顾](../../LOCAL_THREE_PLAYER_20261023.md)保留原范围。
