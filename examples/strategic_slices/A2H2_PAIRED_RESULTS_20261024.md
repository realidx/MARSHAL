# 三人 A2H2 与 H2 配对检查，2026-10-24/25

用户同意继续检验已冻结的 A2H2：相同33个三人父游戏，保留H2的两个隐藏偏好、2RR、调查1、报价1，
只给一名玩家增加第二个承诺选项，并让其一个原有目标改为需要该选项。
承诺仍可累计；本次没有引入互斥行动或新的资源约束。

## 实际运行

完整33局本地运行已完成：30局原生终局数值认证并测量Q/S；原10、49、76缺失。
使用现有 `three-player-complexity-study-v1` 求解和主Q/S合同，
没有修改solver或默认值。实际CLI覆盖为workers2、memory_gb0；macOS未施加内存硬限。
其余预算：max_nodes600000，构树/缩减各180s，候选600s，认证300s，Q/S1200s，单局硬限3600s；
epsilon1e-8、tie tolerance1e-9，inertia_then_joint、max_sweeps512、joint_evaluations400、repair_passes8。
每局保留首次通过完整原生终局数值认证的profile，不按Q/S选reference。
认证口径沿用自身效用epsilon-Nash、局部自身最优支持及仅回应阶段的社会平局检查；
epsilon为1e-8、离路径采用已声明的先验回退，不声称解析精确、唯一或形式化序贯均衡。

[实际snapshot](../../new/three_player_complexity_v1_20261023/local_A2H2_33_v1/pipeline_snapshot.json)、
[进度](../../new/three_player_complexity_v1_20261023/local_A2H2_33_v1/progress.json)、
[逐局结果](../../new/three_player_complexity_v1_20261023/local_A2H2_33_v1/results.json)。

输入A2H2.jsonl SHA256：`bf964e1c1de8f46db56691b2b526df1c46fcdc32195d707fae20e668331493ce`。
原研究index66–98映射原33个父游戏；不替换旧100或因失败删题。

## 同29局配对结果

H2可测31局、A2H2可测30局，两边均可测的交集为29局。H2缺失原46/76，A2H2缺失原10/49/76。
A2H2的原46已有认证与正S，但H2没有可比较标签，不能把它算进机制改善的配对证据。
三局失败均返回candidate_unavailable，不是超出600000树节点上限，未赋零或替换。

| 指标 | H2 | A2H2 |
|---|---:|---:|
| 任一种own S为正的父游戏 | 8/29 | 9/29 |
| 正own S状态／可测context | 43/172033 | 632/414853 |
| 有当前第一步损失的正S状态 | 39 | 585 |
| proposal正S且有当前行动损失 | 35 | 518 |
| reference路径上的正S状态 | 6 | 193 |
| 私有答案组没有共同当前own最优proposal，且私有S为正 | 17组 | 221组 |
| 正S的context计数比例 | 0.0250% | 0.1523% |
| 各父游戏正S比例等权平均 | 0.0348% | 0.0990% |
| reference决策占用权重中的正S比例 | 0.0244% | 0.1080% |

这些是不同公开节点/信息cell或遗漏组，不是632个独立训练题；两臂树和可测context数量不同。
reference权重按决策访问的概率质量归一化；它不等于模型self-play路径或GRPO有效advantage比例。
所有零counterfactual状态仍按原合同没有S，不混入零S分母。
两边使用的已认证reference可能不同；这些结论相对于各自冻结profile，不是跨均衡稳定性或隔离因果效应证明。
H2和A2H2的候选/测量预算也不同，不能由这批实际耗时宣称solver效率改善。

新增正S父游戏为21/54/62/88/89，原22/35/43/96在A2H2没有正S；保留3/7/65/78。
原62贡献501/632个正S，原78贡献98个，两者合计约94.8%。
reference路径193个正S中，原62有165个、原78有19个。
221个私有答案proposal变化组中，原62有180组、原78有39组。
说明新增行动产生了真实信息敏感决策，但提升集中，不能称整批游戏普遍更复杂。

仅S指标有所提高，其他互动指标并非都提高：最优报价接受结果随对手类型变化且有自身收益差的父游戏
从24/29变成22/29；自身Q全平的可测context占比约57.2%→65.3%。
严格调查最优context为10→73，其中入口已按reference推断所有最优目标答案的为2→5；
入口仍有不确定性不自动证明调查收益全部来自答案获取，不能与当前节点S混称。

[完整配对数据与逐局见证](../../new/A2H2_audit_runtime_v3_20261025/paired_v1/PAIRED.json)、
[报告运行snapshot](../../new/A2H2_audit_runtime_v3_20261025/paired_v1/pipeline_snapshot.json)。

## 标签与决策例子

原62、node398290、P2最后一次proposal：自身三个目标均want，已调查知道P0/G0=want。
原生可选动作的Q为 `[0.5, 2.5, 1, 3, 1]`，完整信息最优收益3。
遗漏这条答案后的策略以各1/2选择两个Q=1的报价，当前regret与own S均为2；
该节点reference概率质量约0.000463。
这已经是当前报价选择与自身终局收益之差，不能归为只依赖回应时帮助别人的社会平局。
其所属游戏仍为两轮、两个隐藏偏好，并没有新增互斥行动规则。

原3、node522345也是proposal例子：完整信息收益2，遗漏调查答案后选择的报价被拒绝，收益1。
该节点不在reference路径上，不能据此说模型必然遇到或犯错。

两例均已独立LP通过，保守S区间分别为[2,2]与[1,1]（数值精度内），
不依赖该遗漏森林最优策略的剩余平局。原62完整/遗漏森林归一化平均收益差约0.243902，原3为1/3。
这是本次完整父游戏reference下的新验证，不是沿用之前的末轮子局结果。

## 检查口径与复核

主S继续只衡量逐条遗漏导致的自身最终效用损失；回应阶段的社会平局信息需求单列。
分别看proposal、response、当前第一步regret和reference路径。对于私有答案，比较同一public node、
own type和其他答案下的可兼容场景，检验它们是否还有共同的自身最优行动。
严格最优调查另查入口答案支持，不能把已推断答案的公开信号收益当成私人答案获取收益。

两臂33局的覆盖与失败全部保留；配对效果只用两边均有标签的交集。
context计数比例、父游戏等权比例和reference决策占用比例分列，均不替代模型D或模型训练暴露频率。
30个已认证reference逐局独立重载已30/30通过：workers2，构树/认证各300s，单case硬限900s，memory_gb0。
只重新加载与认证，不搜索/修复候选、不重新测Q/S，故重载结果的measured=0不代表主标签缺失。
旧helper的missing_original_indices=[68,80,89]实际是研究index，映射为原10/49/76；未回写修改该字段。
10个正S父游戏的最大通道见证和最大proposal见证已完成独立sequence LP复核：
共16个见证，32次完整信息/遗漏信息聚合最优值核对全部一致；
16个真实context的保守S区间均在数值精度内为正单点。
这不表示全部636个正状态均逐一LP验证，也不表示跨均衡不变。

原7的最大私有S见证当前Q全平、当前regret0，但后续策略的own S=1，LP同样验证；
原21的最大历史S=0.5，但该遗漏森林归一化的平均信息收益只有约6.07e-7。
两例分别说明不能只看当前一步差异，也不能只按最大的真实context S决定训练价值。
森林平均值也不是模型访问率；不据此删除离reference路径或低概率的节点，最终仍需模型D。

[独立重载完成记录](../../new/three_player_complexity_v1_20261023/local_A2H2_reload_v1/COMPLETE.json)、
[LP检查明细](../../new/A2H2_audit_runtime_v3_20261025/LP_v1/CHECKS.json)、
[LP完成记录](../../new/A2H2_audit_runtime_v3_20261025/LP_v1/COMPLETE.json)。

[报告方法运行前快照](versions/A2H2_paired_audit_v1_20261024/SNAPSHOT.json)、
[方法说明](versions/A2H2_paired_audit_v1_20261024/DESIGN.md)。

首个paired脚本直接启动在领域模块导入前缺少benac_p路径而失败，未测量、未生成分析结果。
该失败单独留档；v3启动器显式加入仓库依赖路径并保存实际sys.path/PYTHONPATH与数值库线程设置，
调用冻结的paired v1和LP v2计算函数，没有修改它们的标签或统计公式。
[运行环境v3](versions/A2H2_audit_runtime_v3_20261025/SNAPSHOT.json)、
[LP方法v2](versions/A2H2_witness_LP_v2_20261025/SNAPSHOT.json)。

## 当前判断

A2H2是有用的候选扩展：在不增加轮数或隐藏偏好数量的情况下，已出现经独立LP验证的、
信息影响当前报价与自身终局收益的决策。它并没有让全部游戏都产生密集S，且提升集中于62/78。
不能把正S数量增长等同于模型会犯错、GRPO必有advantage，或game slices已经优于SP。

下一步先审查62/78与零S局的行动—目标结构，确定规模与生成分布，再对齐prompt、测模型D。
现有证据不要求立刻再加轮数/隐藏偏好；继续保留不需要调查的游戏，也不单靠Q或S挑父游戏。
正式100题、prompt和训练合同仍需后续冻结，不能把本研究30个已测游戏当成新正式题库。

本轮执行与复核已完成，10月24日开始的研究延续至10月25日。
完整执行输入、source、运行输出及本报告hash关闭为
[EVIDENCE.json](versions/A2H2_audit_runtime_v3_20261025/EVIDENCE.json)。
关闭的方法快照及既有H2结果不覆盖；后续新结果另行记录。
生产active仍v8；新prompt、模型D、正式选题与训练均未运行。
