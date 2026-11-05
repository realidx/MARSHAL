# Q/S 行动分布定义审阅与原100补算

2026-11-04。用户授权审查“信息改变整个行动分布”的定义，并检查原100是否需要重算，再讨论800入口。
本轮采用新的独立描述版本，保留旧标量Q/S，不改游戏、prompt、奖励、advantage或生产训练。
方法合同见[DESIGN](versions/qs_action_profile_v1_20261104/DESIGN.md)。

## 核心判断

信息影响行动价值表、行动分布及决策后果，这是有成熟决策理论背景的研究方向。
但“分布变了多少”与“信息值多少终局效用”不是同一个量，也不存在由未正则化Q唯一决定的完整行动概率。
建议将每条信息的标签扩展为完整profile，保留损失摘要，不把S直接改成一个KL/JS数值。
模型相关性仍由目标模型D评估；Oracle profile用于描述和覆盖结构，不用于直接宣布难度排序。

## 信息、Q与策略分布

I表示玩家合法可见信息，不是上帝视角world。对手行为及其对私有信息的依赖固定为已保存reference。

| 字段 | 定义及解释 |
|---|---|
| `Q` | 旧完整信息行动Q；当前固定a，自己之后最优应对至原生终局 |
| `Q_omitted_subjective` | 在遗漏e的合并信息条件下，固定a并使用遗漏条件最优后续；按遗漏条件信念取期望 |
| `Q_omitted_evaluated_true` | 同样的遗漏后续策略和固定a，放回实际完整入口I评价 |
| `canonical_full_action_probabilities` | 完整Q允许的当前最优动作上均匀；response另执行社会次级规则 |
| `omitted_action_probabilities` | 合并forest中遗漏条件最优策略的当前分布，沿旧合同均匀剩余平局 |
| `relative_Q_change` | 两种信息下各自`maxQ-Q(a)`向量的差；记录整个相对行动结构 |
| `policy_total_variation` / `policy_JS_nats` | 上述明示Oracle策略分布的变化；不是目标模型概率、不是训练奖励 |

完整Q的后续自身最优平局仍沿旧`contingent_values`保留reference支持；本轮不重新选择对手或改变旧Q。
当前canonical均匀分布是便于比较的显式约定，不意味着游戏本身唯一要求该混合比例。
遗漏后每个动作Q不必都改变；同一动作的真实收益也不会因玩家忘记信息而物理变化。
主观Q改变可来自belief更新和后续策略约束，只有放回同一个真实入口评价才能解释为收益损失。
尤其不能直接以`max(Q_full(I))-max(Q_omitted_subjective(I-e))`定义实际入口的S：两项所用信念不同，
这个差可能只是条件世界收益基准不同。传统事前信息价值是对可能信息结果平均后的最优收益提升，
与我们在某个已发生完整入口上评价遗漏策略的S也要区分。

### 保留原S，补充精确分解

令p为遗漏后当前行动分布，q为完整信息Q，q-e-true为遗漏后续策略在真实入口下的行动Q。

```
S_total(I,e)  = max(q) - V_I(pi_omitted)
S_current     = sum_a p(a) [max(q) - q(a)]
S_future      = sum_a p(a) [q(a) - q-e-true(a)]
S_total       = S_current + S_future
```

因此旧S本来就计算了遗漏策略所有行动及后续分支的期望损失，并非只检查一个确定动作。
用户这次指出的缺口是：只输出这个摘要，隐藏了其他动作的价值变化以及分布怎样改变。
本轮补齐该描述，而不是宣称旧S的收益定义全盘错误。

`S_current`针对当前动作，终局Q仍假设此后恢复完整信息最优策略；`S_future`衡量继续遗漏造成的额外后果。
当前Q全平不排除未来S；自身Q/S平局也不排除response社会次级信息需求。

### 为什么不能只用分布距离定义价值

- 两个动作Q均为1，分布从[1,0]变成[0,1]：TV=1、JS=ln2，自身损失仍为0。
- 两个动作Q为1与0.999999，同样切换：TV/JS仍达到上述值，但损失只有0.000001。
- 全部动作Q同时加同一常数，收益基准改变，相对决策结构不应变化。
- Q未改变的最优动作之外，次优动作差距可能改变；Oracle均匀最优分布不变，但目标模型仍可能更容易/更难选对。

所以同时保存整张相对Q表、集合与分布，而不是将某一个距离当作所有信息价值。
TV/JS受剩余平局约定影响；本轮不声称对所有最优策略、所有reference或均衡都不变。
因此同时保留own/protocol最优集合的交集，帮助识别可兼容的当前选择；交集非空也不证明整段遗漏策略无损。
没有对所有入口逐一计算最优策略面上的S/分布距离上下界，不能将canonical分布变化称为平局无关的必然变化。
没有额外的softmax温度，也没有用新行为模型猜测LLM分布。

## 与既有研究的对应

- [Blackwell, Comparison of Experiments (1951)](https://digicoll.lib.berkeley.edu/record/112749)：
  信息结构通过可实现决策风险比较，是成熟背景。原始档案可检索，本次PDF返回403，没有声称逐页核读。
- [Chen等，UAI 2017](https://proceedings.mlr.press/r15/chen17a.html)：
  顺序选择测试以低成本支持高质量决策；支持将信息评价与决策收益连接，而非只衡量不确定性下降。
- [Arumugam与Van Roy，NeurIPS 2021](https://proceedings.neurips.cc/paper_files/paper/2021/hash/517da335fd0ec2f4a25ea139d5494163-Abstract.html)：
  将学习目标的信息需求与performance shortfall相结合。与“既看分布/信息变化，也看行动后果”的方向相符。
- [Schulman等，Soft Q-Learning，§2–3](https://arxiv.org/html/1704.06440v4)：
  Boltzmann行动分布由正则化目标、温度与基准分布确定；不能把softmax(Q)当成当前游戏天然的唯一策略。
- [Fosgerau等，作者稿](https://www.its.caltech.edu/~mshum/papers/general_entropy.pdf)：
  离散选择概率与信息成本/随机效用假设有关；不同成本可以产生不同选择概率。

这些文献支持概念背景，不是对我们的特定历史遗漏forest、平局约定或选800方法的直接有效性证明。
本轮也不引入新GRPO方法。

## 原100与后来研究池必须分开

| 数据 | 当前已有产物 | 本轮范围 |
|---|---|---|
| 2026-10-21原100，67两人/33三人 | 99份终局reference和旧Q/S；25缺失 | 对99份保存reference补算完整profile，25继续missing |
| 原33三人H2/A2H2变体 | 各31/30份终局标签，独立身份 | 不混入原100；未在本轮整批补算 |
| 新24结构覆盖池 | 22份终局标签，缺4/11 | 只重建已走读index10的448节点子树验证新字段 |

原100 SHA256=`30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad`。
新24 SHA256=`b47f0568febbfc49aac7cf2e6977997338f95eb7376b990a452faa92ee589ba3`。
本轮没有凭研究结果替换原100三人局，亦未冻结一个新的混合100父游戏池。

### 为什么需要补算，但不需要重新求均衡

旧labels已有完整Q和多数非平凡遗漏分布，却没有未被选择动作的遗漏条件Q。
这些值不能仅从一个最优动作或最优分布恢复，必须重放遗漏forest。
已有reference仍适用：重构同一原生树、重载同一对手策略、复核原证书，重新运行标签DP即可。
在一次DP中保留各root child值便能输出全部动作Q，不用为每个动作单独重求均衡。

零CF及失败结果不作0。保留证据唯一确定入口的singleton沿旧定义复用自身Q，明确记录方法。
因此“所有可能decision point都是潜在入口”不等于当前reference已经为所有入口提供可用标签：
零counterfactual历史仍需另行规定合理的off-reference信念。本轮没有引入这项新规定，暂不能将其混入已测入口池。
这类节点旧Q字段仍带`legacy_global_BR_fallback_not_fresh_subtree_optimum`身份，不能仅见到数值就当成可靠新入口Q。
旧labels/reference保持字节原样，新输出独立目录；所有旧Q/S及保存的遗漏分布逐项比较。
CPU参数与source/input/hash见各次`pipeline_snapshot.json`；没有模型/GPU/训练或新prompt效果验证。
沿用原数值epsilon认证及非唯一reference限定，不提升为解析精确、形式序贯均衡或跨均衡稳定结论。
单例LP的own目标放松社会次级约束，适用范围仅为该固定reference下核对的行动值。

## 执行结果

原100全部纳入请求：2题pilot完成，剩余98题中97题完成；合并99题，25仍缺终局reference。
不重复计算pilot两题，不按测量结果改父池。99份旧labels及reference的hash均与原results记录一致。
所有旧Q、逐条S和已保存遗漏行动分布均逐项匹配；各例原生cutoff_leaves均为0，并重新通过保存reference认证。

| 指标（原100中可测99题） | 实测数量 |
|---|---:|
| 正counterfactual决策context | 260,971 |
| 零counterfactual、S不可测context | 3,278,829 |
| 可测逐条遗漏item | 845,079 |
| 至少一条信息使主S为正的context | 1,452 |
| 有正S、但所有逐条当前行动损失均为0的context | 225 |
| 至少一条信息使相对行动Q表改变的context | 17,614 |
| 至少一条信息使canonical Oracle分布改变的context | 8,786 |
| 分布改变但该条信息own S=0的item | 7,864 |
| 相对Q改变但该条信息own S=0的item | 18,821 |

context是入口历史/玩家信息场景，item是其中一条信息的遗漏；两种计数不能混用，表中各行也不是互斥类别。
这些是原100的结果，不与结构24的114个正S状态合并，也不声称已解决新三人题库质量或模型信号稀疏。

结论是：只按正S会漏掉大量行动结构变化；但8,786次分布变化也不能全部称为重要信息，
其中包含own等价动作的概率重分配及社会次级选择。D未测，尚不能宣称这些新覆盖会改善训练。
94/99父游戏存在相对Q表变化，89/99存在canonical分布变化，42/99存在正主S；不能把前三者解释成新的学习有效率。
逐条主S均为0、但至少一条信息改变相对Q表的context有16,204个；主S均为0但分布变化的有7,491个。
这两个集合也有重叠，不相加凑800；不同历史context仍不等于独立题目。

| 原100内分层 | 可测context | 正主S | 相对Q表变化 | canonical分布变化 |
|---|---:|---:|---:|---:|
| 两人66个可用父游戏 | 222,498 | 1,440 | 16,108 | 8,242 |
| 三人33个父游戏 | 38,473 | 12 | 1,506 | 544 |

原三人局依然是单隐藏偏好的旧规模；丰富描述没有增加其原有收益层面的信息价值。
下一步需要据此审查是否保留该三人来源，或采用独立H2/A2H2/结构池；不能仅因新描述非零就宣称扩复杂度已无必要。

### 已走读三人index10的独立验证

复用[原走读](THREE_PLAYER_WALKTHROUGH_20261029.md)中的448节点后续与同一reference，
对9个合法动作各做完整/遗漏两次强制当前动作的独立sequence-form LP，18项全部匹配。
三个调查答案context的Q、旧S和遗漏分布也匹配；无新增求均衡。

| P0已知P2想要G2的实际context | 动作4：向P1合同 | 动作8：向P2合同 |
|---|---:|---:|
| 完整信息Q | 2/3 | 17/18 |
| 遗漏答案后的主观Q | 2/3 | 25/54 |
| 同一遗漏后续策略放回真实context的行动Q | 2/3 | 17/18 |

遗漏使当前分布从只选8改成只选4；TV=1，JS=ln2，S_current=S_total=5/18、S_future=0。
信息改变判断，不改变同一报价在该实际context的物理后果；这说明两个遗漏Q字段确有区分必要。
在另两个答案context，主观Q也改变但最优动作仍为4，S和分布变化为0。
解析反例同时验证了：两个同收益动作之间完全切换也可JS=ln2而regret=0，微小regret也可对应同样JS。

### 可复核产物

- [原100合并统计](../../new/qs_action_profile_20261104_runs/summary_v1/SUMMARY.json)及
  [真实入口例子](../../new/qs_action_profile_20261104_runs/summary_v1/EXAMPLES.json)。
- [pilot实际snapshot](../../new/qs_action_profile_20261104_runs/pilot_v1/pipeline_snapshot.json)与
  [剩余98请求实际snapshot](../../new/qs_action_profile_20261104_runs/remaining_v1/pipeline_snapshot.json)。
- [三人例完整行动Q及18次LP](../../new/qs_action_profile_20261104_runs/witness_v1/REAL_CASE.json)。
- [方法及关闭证据](versions/qs_action_profile_v1_20261104/EVIDENCE.json)。

新版逐节点labels仍按`cases/<index>/labels.jsonl.gz`存放，pilot中0/17，其余97在remaining中；
合并snapshot逐一列出路径和hash，不覆盖旧输出。
首次实现启动有一处括号语法错误，在导入/读取题库前即退出；修复前source、注册及失败记录保留在
`versions/qs_action_profile_v1_20261104/preexecution/`。不将该启动失败算成任何标签、模型或solver运行成功。

## 对800入口的实际含义

本轮新增结果适合回答：哪些入口有行动相对价值变化、最优集合切换、当前损失、延迟损失或纯平局分布变化。
这些是结构属性，不等同难度。去重/限制同父游戏集中度之后，才讨论分层抽样800的具体配额。
最后100指训练slices，不能写成100父游戏；模型D尚未测量。
训练/验证/测试仍需按父游戏先隔离，不能用test的D挑训练题。

用户同意模型从入口持续控制该玩家至原生终局；这在本报告记录为新slice设计决定，尚未接入训练代码。
实际决策次数依路径变化，不沿用旧k=1/2/3比例，不新增固定长度配额。
prompt/response社会平局评分仍需对齐后才能测新D。
