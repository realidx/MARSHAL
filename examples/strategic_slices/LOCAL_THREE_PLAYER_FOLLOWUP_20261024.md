# 三人H2本地整批后续核查，2026-10-24

用户授权继续完成本地整批、复核与失败诊断。沿用已关闭的
`three-player-complexity-study-v1`，不修改solver/游戏/Q/S定义、旧100、prompt或生产v8。
这是实际运行与诊断记录；不覆盖研究v1的关闭快照。

## 首次整批已完成

33局全部尝试，31局完成原生terminal数值认证并测量Q/S，原46/76缺失。
没有截短终局、删除动作、放宽epsilon或用零代替缺失。

同一组31个已测原游戏的配对统计，单位为父游戏：

| 指标 | 旧基线 | H2 |
|---|---:|---:|
| 任一种单条遗漏正S | 2 | 9 |
| 调查答案正S | 2 | 6 |
| 公共历史正S | 2 | 4 |
| reference实际路径上有正S | 2 | 3 |
| 存在调查严格最优节点 | 1 | 8 |

H2调查答案正S来自3/7/43/49/78/96，历史正S来自22/35/49/65；reference路径上正S来自7/22/65。
新增world支持、信息结构与可能不同的reference均会影响结果；这不是隔离因果效应或模型训练效果。
偏离reference的节点不因此无价值，reference路径也不等于目标模型self-play路径，最终仍需模型D。

节点级信号仍稀疏：183348个positive-CF信息context中，调查答案正S为28个、历史正S为21个，
两类不重合，共49个（约0.0267%），其中45个已有当前第一步行动损失。
reference路径45940个context中仅6个正S，其中5个已有当前行动损失。
这里的context是原生节点与当前信息cell，不是模型采样回答；这个比例不等于GRPO非零advantage比例。
S=0仍可能有Q或模型D价值，不能据S单独否定节点。计数也不证明49个就是49个独立训练题。
完整7627244个信息cell中7443896个为零CF，S按既有合同缺失，未赋0；
不能把模型self-play访问的这些离路径状态自动当成已有可靠S标签。

此外，26/31个游戏存在“最优报价的接受结果随对手类型变化且接受/拒绝收益不同”的节点，
旧基线同组为18/31；reference路径分别为20/31与14/31。
这证明有实际互动依赖，但不等于证明模型会犯错或信息利用标签已经充分。
[节点密度与覆盖](../../new/three_player_complexity_v1_20261023/local_H2_signal_density_v1/DENSITY.json)。

[首次COMPLETE](../../new/three_player_complexity_v1_20261023/local_H2_33_v1/COMPLETE.json)、
[原逐case结果](../../new/three_player_complexity_v1_20261023/local_H2_33_v1/results.json)、
[配对分析](../../new/three_player_complexity_v1_20261023/local_H2_initial_analysis_v1/ANALYSIS.json)、
[查询入口支持与交互概览](../../new/three_player_complexity_v1_20261023/local_H2_initial_overview_v1/OVERVIEW.json)。

## 第35局：调查有优势，但答案没有新增收益

该局两处调查严格最优节点的目标都是P1/G0。根据冻结reference的公共历史似然，
调查前已得到P1/G0=avoid的后验概率1；这是reference条件推断，不是任意对手下的逻辑必然。
合法菜单按已批准规则只排除公开或直接查过的偏好，未按推断删除，因此这个调查仍合法。

固定对手reference，单独重算调查后的完整最优策略，并在所有后续focal决策中屏蔽该答案：

| P0自身G0偏好 | 调查，保留答案 | 调查，始终不给答案 | PASS |
|---|---:|---:|---:|
| want | 1.7380952381 | 1.7380952381 | 1.2579365079 |
| neutral | 1.0 | 1.0 | 0.9603174603 |

两处私人答案增益均为0；调查相对PASS的收益差分别约0.480159和0.039683。
公开调查行为、额度状态与对手基于这些信息的策略均保留。差异来自公开动作分支及其reference反应，
不能解释为获取未知答案的收益，也不能由此直接证明该信号在其他均衡或目标模型下仍有效。

首次整批全部12个严格调查最优context中，只有这2个的所有最优调查目标在入口已推断确定；
reference实际路径上的6个此类context中占2个。其余目标入口仍有不确定性，
但“不确定”也不自动证明答案有用，不能与当前节点S混称。

[调查后答案屏蔽重算](../../new/three_player_complexity_v1_20261023/query35_channel_v1/DIAGNOSTIC.json)、
[入口后验与历史](../../new/three_player_complexity_v1_20261023/query35_entry_belief_v1/DIAGNOSTIC.json)。
两次诊断均有独立pipeline_snapshot与输入/source脚本hash；这是调查前诊断，不更换当前S标签。

## 两局重试与独立复核

重试仅包含首次缺失的研究index13/23，即原46/76。
候选预算120→600秒、硬限720→1200秒；其余CLI/默认保持首次设置。
单worker，认证180秒、Q/S300秒、构树/缩减各180秒、max_nodes600000、memory_gb0；
后台方法仍为inertia_then_joint，epsilon1e-8、tie tolerance1e-9等完整配置见snapshot。

[重试实际snapshot](../../new/three_player_complexity_v1_20261023/local_H2_retry_v1/pipeline_snapshot.json)。
原46较大预算下仍约64秒返回candidate_unavailable，不是用满预算或内存失败；
目前候选搜索路径不足，尚未证明无可认证profile。原76重试约135秒返回candidate_unavailable，
这次未以SearchLimit结束；仍没有可认证profile。因此重试未增加31/33的覆盖。

保存后逐局独立重载已31/31通过：workers2、构树/认证各180秒、每case硬限420秒、memory_gb0；
不重新搜索/修复候选或测量Q/S。新正S见证LP复核已完成，不将原小样复核冒充本批复核。
主运行最大own deviation约4.44e-16，最大局部支持收益偏离约5.55e-16，均低于既有1e-8认证阈值；
这是数值证据，不提升为解析精确/唯一或形式化序贯均衡证明。

[重载COMPLETE](../../new/three_player_complexity_v1_20261023/local_H2_reload_v1/COMPLETE.json)、
[合并统计](../../new/three_player_complexity_v1_20261023/local_H2_combined_overview_v1/OVERVIEW.json)。
重载工具的`missing_original_indices=[13,23]`实际沿用研究index，经jobs映射为原46/76；
该旧字段命名未回写修改。重载的`measured=0`表示没有重算Q/S，不能误读为主运行31局没有标签。
最终统计将优先保留首次已认证profile，仅对原缺失局使用重试结果，不按Q/S择优选profile。
模型D、新prompt、正式题库选择和训练均未执行；第25局继续保留挑战身份。

## 新见证LP结果及剩余问题

对每个存在正S的游戏/通道选取一个最大S见证，共10个，使用独立sequence LP验证：
全部与遗漏策略求值一致；保守S区间在数值精度内均为单点且严格为正。
LP放宽response的次级社会约束求上下界，因此这个结论也适用于满足原约束的遗漏策略。

| 原游戏 | 通道 | 当前S | 当前第一步regret |
|---:|---|---:|---:|
| 3 | 调查答案 | 0.5 | 0.25 |
| 7 | 调查答案 | 0.5 | 0.5 |
| 22 | 历史 | 1/12 | 1/12 |
| 35 | 历史 | 0.5 | 0.5 |
| 43 | 调查答案 | 0.5 | 0.5 |
| 49 | 调查答案 | 1 | 1 |
| 49 | 历史 | 0.5 | 0.5 |
| 65 | 历史 | 1/28 | 0 |
| 78 | 调查答案 | 2 | 2 |
| 96 | 调查答案 | 1/54 | 1/54 |

[LP完成记录](../../new/three_player_complexity_v1_20261023/local_H2_LP_review_v1/COMPLETE.json)、
[每个见证、区间与LP细节](../../new/three_player_complexity_v1_20261023/local_H2_LP_review_v1/REVIEW.json)。
这10个见证不依赖遗漏策略的剩余最优平局选择，但仍相对于同一冻结reference；
没有证明跨均衡不变，也没有逐一LP验证其余39个正S状态。

H2增加了真实的交互和信息利用案例，不只是扩大树；本地能够完成31局，但并未解决所有游戏的候选收敛。
目前主要限制是：46/76缺失、节点级信息信号仍少、许多零CF状态没有S，以及尚未测模型D。
不把9个正S游戏或49个状态直接冻结成正式训练选择，不由reference路径替代模型采样判断。
H3/A2H2完整整批仍未执行；本轮不追加新的游戏机制或修改prompt。

本次来源、完整运行参数、未解状态及验证hash已关闭为
[本地审计v1快照](versions/three_player_local_audit_v1_20261024/SNAPSHOT.json)。
