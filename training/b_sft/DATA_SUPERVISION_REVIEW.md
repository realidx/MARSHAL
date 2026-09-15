# 数据集、监督质量与训练设计复审

日期：2026-09-11。审查对象：`new/local_data/social_generalization_v4`，包括 68 个 planning 样本、55 个 belief 样本，去重后 110 个。当前模型运行版本为 v6 prompt。本文记录本轮审查，不表示已修改数据、奖励或训练架构。

## 结论

现有数据适合作为流程回归测试材料，但不足以作为证明“B 推断帮助 P 规划”的主训练集。原生收益与保存标签的数值核验通过；主要问题是样本是否要求目标能力、教师假设的适用范围，以及奖励尺度。应区分“声明机制下的标签一致性”和“这些标签是否是训练目标能力的合适手段”。

## 核验范围与边界

- 核验全部 110 个 B 快照。
- 核验 1,980 条已有终局轨迹。
- 对 109 个 P 教师可用样本，完整核验 639 个动作价值、4,352 条世界分支的原生终局收益，未发现数值不一致。
- 一个样本 `evidence-430229-cbe6fecdd43fcf30` 的 P 参考续局不可用，已有标签正确保留 mask；其 B 标签核验通过。
- 伙伴策略重建仍使用当前 shared solver，因此这不是第二套独立均衡求解器的交叉证明。终局收益则从原生状态和偏好重新计算。
- 未调用新模型、未更新参数、未修改冻结数据或训练代码。

## 1. “有信息的 B + 有区分度的 P”没有保证 B 对 P 必要

规划集标记为信息后规划的 17 个样本中，保持当前物理局面、恢复初始 catalogue 先验后重新规划，首个先验最优动作在原题中仍然全部最优。全部 17 个样本在固定参考续局下，也存在对每个剩余世界都最优的共同动作。

另找到 27 对当前公开物理局面相同、B 标签不同的样本，最优动作集合均有交集，没有必须作出不同选择的对照对。

恢复先验也改变参考共同计划，是忘记历史证据的诊断，不是原历史下的合法后验，也不是模型 B 的因果干预。这些结果不证明模型永远不需要社会推理，但说明现有筛选门槛不足以检验“利用新获得的偏好信息改善当前动作”。

若保留这一验证目标，应构建公开局面匹配、历史证据不同、最优选择不相容的对照样本，并要求忽略证据有非零 regret。不能只检查 B 集合缩小和 P 存在一个坏动作。

## 2. 分布与简单策略基线

| 检查项 | 结果 |
|---|---:|
| planning 的 proposal / response | 38 / 30 |
| planning 的非终局 / 直接终局 | 52 / 16 |
| planning B 全集合且 favored 未定 | 110 / 131 个目标 |
| planning 全集合未定 B 基线的平均每题分数 | -0.0993，最优为 0 |
| belief 的多元素集合且 favored 非未定 | 2 / 108 个目标，来自一个样本 |
| planning 前三个 topology 样本数 | 44 / 68 |
| planning 剩余不超过三个 proposer 回合 | 64 / 68 |

不使用 B 的简单策略定义：proposal 选择 PASS；response 比较动作执行后的立即自身收益，平局选择首个原生合法动作。

| 范围 | 简单策略参考最优数 |
|---|---:|
| planning | 40 / 68 |
| belief 中 P 教师可用样本 | 53 / 54 |
| 两集合去重、P 教师可用样本 | 81 / 109 |

belief 集 55 个样本中，29 个 P 标签可用但所有合法动作同值，另一个 P 标签不可用。B 集能提供推断信号，不等于其 P 能提供动作选择信号。`cohort both` 是评估集合合并方式，不应自动成为均衡的训练采样策略。

## 3. B 标签的伙伴行为假设

belief 集的证据类别：17 题严格自身价值排除，28 题涉及利他平局规则排除，10 题无排除。

例如 `evidence-430225-early-05812a1c20968979`，伙伴 3 的一种候选类型下，PASS 的自身/其他人收益为 0/0，某 OFFER 为 0/1。观察到 PASS 后，教师依赖“自身收益平局时最大化他人收益”排除该类型。

这在声明的确定性伙伴机制下合理，但不等于任何仅追求自身利益的玩家都必须做出 OFFER。教师还依赖有限规划窗口、共同计划的初始化、更新次序、稳定点选择及残余动作顺序。当前屏蔽了依赖局部残余动作顺序的脆弱排除，不能据此推断对所有伙伴策略变化都稳健。

如果继续用 B 教师作为主监督，应把严格自身收益证据和利他规则条件下的证据分开验收。若改用多种伙伴行为，原机制的精确 B 标签不能未经重定义直接沿用。

## 4. B 评分权重

当前集合部分为 `-0.5 * 对称差成员数 / 3`；favored 部分为错误时 `-0.5`。一个 favored 错误的代价等于三个集合成员错误。

与此同时，多元素集合下需要判断 favored 的样本极少。这不是算分错误，但权重与覆盖未充分支持“主要训练兼容偏好的保留与排除”这一目标。应先决定集合推断和 favored 判断在目标能力中的地位，再定权重，而非默认更细的标签更有效。

## 5. 失败罚分与 P regret 尺度

当前每次截断或格式失败各自记 -1；截断不再叠加格式罚分，重试不会覆盖第一次分数，服务错误不罚。

但 P 的任务分数是未归一化的参考 regret。planning 中 5 题、去重全集中 6 题存在低于 -1 的合法动作分数，最低为 -2。例如 `menu-terminal-second-79ca516b4d64c4e1` 的最优收益为 2，REJECT 收益为 0，所以合法 REJECT 得 -2，而失败只得 -1。

这会造成失败优于某些合法错误答案的潜在激励；不是已观察到的主动利用行为。若使用这些逐次奖励训练，参数更新前应统一尺度，确保失败不会优于最差合法提交。若改用整局 outcome reward，需要重新定义失败、retry、终止和 token 成本对整局回报的影响，不能直接搬用此局部评分。

## 6. 教师行为与 P 训练标签并非同一个目标

发现 7 个样本中，当前 reference policy 的选择获得负 reference regret。伙伴行为优化有限的两个 proposer 回合窗口；P 的动作价值比较当前动作后、未来 learner 也使用参考策略时的全局终局收益。

例如 `heldout-four-small-early-545bdbb46cbf5a03`，参考策略当前选择 ACCEPT，但 P 参考价值为 ACCEPT=0、REJECT=1。

这一目标差异已在接口中声明，不是收益计算矛盾。但不能把教师轨迹动作直接视作每一步都正确的 P 示范。当前 reference regret 是相对于参考续局的诊断值，不是实际模型回报或 PPO advantage。

## 7. 原架构下的优先修复项

1. 增加真正要求使用偏好证据改变动作的样本与验收条件。
2. 分开 B/P 采样与权重，补足 B 标签和证据机制覆盖。
3. 统一任务与失败奖励尺度。

以上是保留原有细粒度监督架构时的建议，不预设该架构必须保留。

## 8. 待讨论的架构问题

用户提出重新审视设计：以整局 outcome reward 奖励完整轨迹，是否比为每个 B 判断和 P 动作制作细粒度标签更直接；是否可以采用多种行为的伙伴增强稳健性；是否应将每个决策点的推理和动作恢复为一次模型请求，而不强制拆成 B 和 P 两次请求。

这些是待验证的设计选择，本文不把任何方案写成已经获得实验支持的结论。需要区分最终能力、训练奖励、模型接口与离线诊断。细粒度 solver 标签可以用于分析和验证，不必必然成为训练奖励。一次请求也不自动保证模型会使用有效信念推理；整局奖励减少局部标签要求，但仍需可靠的环境收益、对手分布和失败处理。

## 可复现材料

审计目录：`new/local_data/social_runs/social_generalization_v4_quality_audit/`。

- `audit.py`：全部有效动作的世界分支回放、简单策略基线、忘记证据诊断。
- `additional_audit.py`：已有完整轨迹、匹配局面对照、参考策略与 P 目标差异。
- `summary.json`：P 教师可用子集的统计，明确 109 分母。
- `additional_checks.json`：完整 110 样本的核验与对照结果。
- `quality_findings.json`、`cases.jsonl`：逐项问题、基线及评分证据。
- 信息后规划样本的独立 JSON：题面事实、允许解释、排除比较、动作价值及终局分支。

## 9. 围绕 B/P 耦合的 previous work 复查

检索日期：2026-09-11。以下区分论文事实与对本项目的推断；不是完整新颖性证明。重点阅读原论文方法部分，未复现外部结果。

### 最接近的方法

**ToMA — Infusing Theory of Mind into Socially Intelligent LLM Agents（2025 arXiv）**：采样心理状态及条件话语，进行最多四个未来回合的模拟，以双方目标达成评分筛选组合，再对心理状态和话语分别做交叉熵训练。方法明确分解 `P(u,m|H)=P(u|m,H)P(m|H)`，并比较只训话语、只训心理状态和联合训练。它没有要求心理状态匹配唯一的符号后验。原文 §2–3：[ToMA](https://arxiv.org/html/2509.22887v1)。

对我们的意义：这是“用下游结果筛选 B/P 组合”的直接近邻。不能把该总体思想或 B/P 分解本身作为新贡献；也不能因为两阶段生成就认定无法联合优化。其话语模拟、评分目标与我们的原生游戏收益不同，但更换环境和评分器本身不足以保证方法创新。

**SocialRL（2026 arXiv）**：主 RL 使用终局 outcome-only reward；另有独立的 ExpToM SFT 实验，蒸馏 Infer→Act→Anticipate 完整轨迹，优于动作监督。该实验不使用 RL。论文报告下一动作预测与收益相关，而偏好识别相关性弱；这不是因果证明。原文 §4.2、§5.4：[SocialRL](https://arxiv.org/html/2608.13787v1)。

对我们的意义：不能把 previous work 统称为没有细粒度监督。它已覆盖显式社会推理监督及动作预测，普通 outcome RL 和 ExpToM 风格监督都应成为方法对照。

### 训练信念不一定依赖唯一偏好标签

**ToMnet（ICML 2018）**：从不同 agent 群体的行为观察学习预测其后续行为，涉及角色特征与当前心理状态；并非单独证明 observer 获得最优交互决策。[Machine Theory of Mind](https://proceedings.mlr.press/v80/rabinowitz18a.html)。

**SOM（ICML 2018）**：用自身策略模拟他人动作，通过观察动作在线调整他人隐藏目标的估计，再用该估计决策。依赖自我模型对他人的适用性。[Modeling Others using Oneself](https://arxiv.org/abs/1802.09640)。

**LIAM（NeurIPS 2021）**：用自身局部历史编码伙伴表示，训练时重建伙伴观察和动作，策略根据该表示进行 RL。原文明确阻断 actor-critic loss 向 encoder 的梯度，不能描述为 reward 对表示的端到端反传。[Agent Modelling under Partial Observability](https://proceedings.neurips.cc/paper_files/paper/2021/file/a03caec56cd82478bf197475b48c05f9-Paper.pdf)。

对我们的意义：可用真实后续行为为 B 提供可观测的约束，避免依赖一个确定性 solver 的精确心理状态标签。但行为预测本身已有先例，也存在可识别性与探索覆盖问题；单次随机动作不应成为排除全部其他信念的依据。

### 预测质量与决策质量的区别

**Task-based End-to-end Model Learning（NeurIPS 2017）**：在随机优化中按最终任务损失训练预测模型，处理预测训练目标与最终决策目标不一致的问题。[Donti et al.](https://proceedings.neurips.cc/paper/2017/hash/3fc2c60b5782f641f76bcefc39fb2392-Abstract.html)。

**Value Equivalence（NeurIPS 2020）**：研究相对于指定策略和价值函数集合，哪些模型差异不影响价值规划；不是任意错误信念均可接受。[Grimm et al.](https://papers.nips.cc/paper/2020/hash/3bb585ea00014b0e3ebe4c6dd165a358-Abstract.html)。

对我们的意义：应区分改变动作排序的 B 错误和当前决策无关的 B 差异。若改变自身目标或伙伴行为，原来等价的信念可能不再等价；不能只在一个收益函数下验证。

### 反向闭环：行动改变未来的信息与适应

**VariBAD（ICLR 2020；JMLR 2021）**：学习近似任务信念和基于信念的策略，把任务不确定性纳入动作选择，展示依赖不确定性的探索。[VariBAD](https://www.jmlr.org/papers/v22/21-0657.html)。

**A-ToM（2026 arXiv）**：研究伙伴推理层级不匹配造成协调下降，利用历史估计伙伴 ToM 层级并预测动作。[Adaptive Theory of Mind](https://arxiv.org/abs/2603.16264)。

**Learning Latent Representations to Influence Multi-Agent Interaction（CoRL 2020）**：学习自身行为与伙伴未来策略变化的关系，用于影响伙伴和共同适应。这个对象是伙伴策略变化，不应与仅改变自身对固定偏好的认知混淆。[Xie et al.](https://arxiv.org/abs/2011.06619)。

对我们的意义：伙伴类型应容纳行为方式，而非只有偏好向量。正文的 B→P→观察→B 闭环要求检验行动是否带来有决策价值的信息；“主动探测”本身已有理论和方法先例，LLM 实现并不自动构成新方法。

### 从结果构造细粒度信用，而不制作每步 gold answer

**COMA（AAAI 2018）**：用集中式 critic 和反事实基线，把团队回报归因到各 agent 的动作；基线边际化一个 agent 的动作、保持其他 agent 动作不变。[Counterfactual Multi-Agent Policy Gradients](https://ojs.aaai.org/index.php/AAAI/article/view/11794)。

**CVT-RL / Policy-Conditioned Counterfactual Credit（2026 arXiv）**：提出在冻结续局策略下比较中间步骤替换后的终局表现，明确这种贡献估计是策略条件下的代理量，不是任意后续策略下的精确因果效果。本次只核对预印本方法，未验证实验或代码。[原文](https://arxiv.org/html/2606.05263v1)。

对我们的意义：细粒度信用分配不等于细粒度正确答案监督。但不能直接把串行 B/P 当成 COMA 的并行 agent：替换 B 时必须让下游 P 重新生成，否则可能切断要测量的 B→P 路径。反事实文本还须检查分布外扰动、语义有效性和额外采样预算。

### 候选研究方向与最小验证

以下是本项目的待验证提案，不是上述论文已证明的结论，也不声称已确认新颖性。

候选问题：在社会交互中，局部信念准确率和最终结果奖励是否会掩盖“有决策后果的信念错误”与“信念利用失败”？利用 B/P 结构构造的信用分配，能否更有效地训练信息利用和信息获取？

推荐先做受控诊断再决定训练法：

1. 固定公开局面，改变有决策意义的信念与无关信念，分别测量动作和真实回报变化；加入同义改写控制。不把变化本身视为正确响应。
2. 区分 B 错误、P 未利用正确 B、单纯原生动作后果算错；最后一种需无伙伴不确定性的控制题。
3. 加入需要主动取得信息再行动的完整游戏，检验 P→观察→B→后续 P，而不只测试已有历史下的静态选择。
4. 对比普通 outcome RL、显式 B/P 且共享终局奖励、局部 B 标签辅助训练、结果筛选的 B/P 联合训练，以及候选耦合信用方法。控制模型、交互 token、训练数据和分支 rollout 总预算。
5. 推理时可以一次 completion 依次生成 B 内容与 P 动作；训练时为归因分支续写，可能增加请求和成本。逻辑分解、参数是否共享、请求次数、奖励来源是不同设计轴。

需要收紧的 claim：不是首次提出 B/P 依赖，也不是首次用结果训练心理状态，而是识别并解决一个明确、可复现的耦合失败，并证明收益来自该机制。若受控诊断未发现这种失败，则不应为保留创新叙事而强行加入方法。




我的建议是：**保留显式的 B→P，但取消“分别模仿 solver 正确答案”作为主训练目标，改为用真实游戏结果分别估计 B 和 P 的贡献。** 具体先做下面这一版，不同时引入其他复杂机制。

**一、每个决策点只生成一次，但内容明确分成 B 和 P。**

模型依次输出：

- **B**：根据已有历史，对伙伴偏好和行为方式的判断，以及仍然不确定的地方。
- **P**：基于上述判断选择行动，最后调用动作工具。

B 不再强制输出完整的偏好集合和 favored。它仍是可检查、可替换的中间表示；P 必须能够读取它。一次请求内先生成 B、再生成 P，就能保持这个顺序。

**二、环境只提供真实终局收益，不再提供每一步的“正确 B”和“正确 P”。**

伙伴可以采用不同的行为策略。游戏结束后，按实际结果计算自身收益。

这里的关键不是彻底取消细粒度信号，而是：**细粒度信号也来自游戏结果，而不是 solver 判断哪种思考才正确。**

**三、训练时，在少量选定决策点进行分支采样，区分 B 和 P 的贡献。**

例如，同一个历史下：

| 信念分支 | 基于该 B 采样的两个 P，其续局收益 | 平均收益 |
|---|---|---:|
| B₁ | 0、2 | 1 |
| B₂ | 2、2 | 2 |

每个分支都继续进行真实游戏，伙伴使用同样的策略配置，其他采样条件尽量匹配。

然后分开给学习信号：

- **训练 B**：比较每个 B 下多个 P 的平均收益。这里 B₂ 比 B₁ 更值得强化。
- **训练 P**：在相同 B 内比较行动及其续局收益。这里 B₁ 下收益为 2 的 P 比收益为 0 的 P 更值得强化。

这比“某条轨迹赢了，就同时强化其中所有 B 和 P”多做了一件事：**降低把偶然选对的动作归功于错误 B，或把执行失败全部归咎于 B 的风险。** 两个分支只是最小示意，正式估计需要考虑采样噪声。

训练时会增加分支请求；部署或普通测试时仍然每个决策点一次请求。PPO 的具体优势估计需要再推导，不能把这张表直接当成已经正确的 PPO 实现。

**四、先用一个小实验判断这种设计有没有价值，再扩训练。**

第一批环境必须满足：不同的伙伴证据确实要求不同动作。暂时不加入主动试探、动态改变伙伴偏好等新机制。

比较三组，使用相同模型、伙伴分布和总 rollout 预算：

1. 自由 reasoning＋行动，普通终局奖励。
2. 显式 B→P，仍然只用普通终局奖励。
3. 显式 B→P，采用上面的分支信用分配。

除了终局收益，还要检查：改变关键 B 是否会让 P 作出相应的正确调整；同义改写或改变无关 B 是否不会随意改变选择。否则，B 可能只是无意义的中间文本。

**我认为我们应该先验证的 claim 是：**

> **利用 B→P 的依赖结构进行信用分配，比给整条轨迹统一奖励，更有效地训练模型使用伙伴判断作出决策。**

这是一条具体、可证伪的方法假设，**还不是已经确认的新颖性或实验结论**。它保留了“发现耦合问题—分析错误归因—针对耦合训练”的主线，也让我们不必继续为每一步维护唯一的 solver 答案。

## 10. 已完成的最小信用分配原型（2026-09-11）

实现：`training/b_sft/social_coupled_credit.py`；测试：`test_social_coupled_credit.py`；样例结果：`new/local_data/social_runs/social_coupled_credit_prototype_r1/demo.json`。

本轮只验证采样与记账逻辑：使用脚本提供 B/P，在原生游戏中执行到终局，不调用语言模型、solver 标签或 optimizer。普通推理的一次请求接口尚未实现。现有 v6 评测流程不受影响。

固定同一公开历史，采样 K 个 B，每个 B 采样 J 个 P。同一个 B/P 行动在相同隐藏配置集合上续局；不同分支使用配对的 P 随机种子和续局随机种子，每局重新重放初始历史。模型侧回调只有公开信息、自身偏好和合法动作；隐藏配置只交给环境侧伙伴策略。配对种子不能保证语义轨迹一致。

记 `R[i,j]` 为该 B/P 在所选隐藏配置上的平均归一化终局自身收益，`m[i]` 为第 i 行均值。当前保存两个诊断量：

- B 信号：`m[i] - mean(m[k] for k != i)`。
- P 信号：`R[i,j] - mean(R[i,l] for l != j)`。

这些是留一基线下的采样回报差，**不是已接通的 PPO advantage，也不证明 B 内容真实**。B 分数取决于当前 P 策略是否能利用该 B。后续要推导 token 归属、基线和更新权重，尤其避免把同一个 B 因 J 个 P 分支重复计权。

六项测试通过，覆盖信用计算、平移不变性、缺失分支整体屏蔽、原生终局重放、无证据时的伙伴对称性、分支隔离、非法动作及收益归一化。脚本样例结果：

| 控制条件 | B₁ 下两个 P 的平均终局收益 | B₂ 下两个 P 的平均终局收益 | B 信号 |
|---|---|---|---|
| 固定伙伴 1 愿意、伙伴 2 不愿意 | `[0.5, 0]` | `[0, 0]` | `[0.25, -0.25]` |
| 四种对称隐藏配置均匀平均 | `[0.25, 0]` | `[0.25, 0]` | `[0, 0]` |

第一行只检验计算路径，不是“正确 B”标签：历史没有区分两位伙伴的证据。第二行验证对称不确定性下不会系统性奖励猜某一个伙伴。多个世界本身不能保证信号合理；正式任务必须按给定历史和真实伙伴生成机制确定评估分布，不能直接使用旧 solver 筛选出的世界，或把初始 catalogue 一律当成历史后的均匀后验。

当前续局失败不伪造终局收益，有缺失值则屏蔽整个比较；根节点采样异常直接停止。这里尚未实现线上一次 retry、1024 token 截断和格式失败的独立记账，不能拿此模块直接开始训练。下一步按顺序完成：

1. 构造有证据且最优动作确实随证据变化的配对小题，并保留无证据、无关 B 和同义改写控制。当前脚本只证明记账正确，没有证明模型会利用 B。
2. 接入一次 completion 内 B→P→动作的接口；训练时支持在 B 边界继续采样 P。共享 1024 token 总上限，P 续写扣除 B 已用 token，并继承一次 retry 与独立失败记账约定。
3. 冻结模型做小规模真实分支试验，记录生成 token、请求、续局成本和信号方差，再判断是否值得接参数更新。分支中的未来决策仍用完整 B→P 策略。
4. 在相同总 rollout/token 预算下比较普通 outcome、显式 B/P outcome、分支信用方法。当前原型不支持任何能力提升或方法新颖性的结论。

## 11. 三组实验入口与当前交付边界

当前主目标固定为：相同初始模型、伙伴分布和总 rollout 预算，对比 `free_outcome`、`bp_outcome`、`bp_branch`。前两组分别自由推理和显式 B→P，均采用终局回报；第三组保存由终局回报导出的 B/P 分支信用。主要比较终局收益，分别检验显式结构和结构化信用的增益。正式训练和独立测试集尚未就绪，不能用本轮冻结模型的小测代替三组训练对照。

新增入口 `training/b_sft/social_three_arm.py`，配套 `test_social_three_arm.py`。已实现：

- 共享英文题面、明确偏好归属和动作 ID；自由推理和 B→P 只改变推理结构要求。普通决策在一次 completion 中完成，B/P 不再分别输出偏好判断工具和动作工具。
- 三组统一使用 `<ACTION>{完整合法动作对象}</ACTION>`，由本地严格解析执行。这是本轮新接口约定，不是旧 v6 的原生 API tool call；不接受 action_index、额外字段、重复 JSON 键，也不修复答案。显式组的边界为 `<B>…</B><P>…</P>`。
- vLLM completions 返回实际 token ID 和 log probability。训练分支在 B 结束处暂停，P 使用原始 prompt IDs 加原始 B IDs 续写，不把 B 重新包装为 user 消息或重新分词。停止字符串可能截在 token 内，解析与续写使用完整 token 解码结果。接口参数依据 [vLLM 0.8.5 官方文档](https://docs.vllm.ai/en/v0.8.5/serving/openai_compatible_server.html#completions-api)。真实服务兼容性仍需线上预检。
- 一条完整 B/P 路径共享 1024 生成 token；P 上限扣除 B 已用 token。一条路径最多一次 retry：若 B 已 retry，P 不再 retry。失败尝试保留独立记录，不用 retry 的收益覆盖它；截断、格式和基础设施故障分别计数。
- 两道证据配对题在当前承诺、轮次等物理状态相同的情况下，拥有不同伙伴行为历史。穷举合法行动并按真实伙伴策略续局，确认两题最优动作集合不相交。第三道无证据题包含四个等概率隐藏配置。伙伴采用题面明确说明的简单行为规则，历史相容性由该行为规则重放确定，不依赖旧 solver。
- 每个 block、每组分配 24 个续局槽位：两道证据题各 4 个，无证据题 16 个。每条分支×隐藏配置续局均占预算；失败槽位照常消耗，另报实际启动数、终局数和失败数。该小测按世界组合加权，不宣称三类题均匀采样。后续正式数据必须重新确定任务分层权重。
- 保存模型标识、tokenizer/模板/源码哈希、固定题包、全部请求 token 与 log probability、原生历史、终局回报和分支信号。额外报告 token、请求与时间成本；相同 rollout 上限不意味着相同 token 成本。

本地脚本控制三组均完成 24/24 续局，请求数依次为 12、12、18。脚本按 UTF-8 字节模拟 token，仅验证控制流，不能用于模型 token 成本比较。测试覆盖同物理状态的决策差异、信息边界、严格动作解析、共享输出预算、路径级一次 retry、原始 token 前缀、失败预算与旧 v6 兼容性。

**尚未完成：**真实 vLLM 调用验证、丰富伙伴策略与独立训练/测试数据、三组参数更新及 checkpoint 评估。当前 `signals.jsonl` 明确标注 `training_ready=false`，不应直接喂给 PPO；基线、token 权重、共享 B 的去重以及后续决策的更新仍需统一接入。脚本不调用任何 optimizer。不要把冻结模型的三组均值解释为信用分配训练的效果。

远程状态：已只读确认 `social-base` 服务存在，根路径为 `/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507`。自动审批拒绝向 `/raid/chenjiahao/mas/training/b_sft/` 上传本轮四个实现/测试文件，理由是新增代码 payload 缺少明确目的地授权；因此尚未上传，也未运行本轮远程生成。用户明确授权该上传后，再按 `SOCIAL_SERVER_RUN.md` 的新入口执行小测。

## 12. 首次三 GPU 真实小测审查：生成协议尚未跑通

结果已从远程完整下载到 `new/local_data/social_runs/social_three_arm_remote_parallel_r1/`。可复查文件为该目录 `audit_run.py` 和 `audit.json`。审查没有修改原始请求或奖励，也没有启动新推理/训练。

| 组别 | 模型请求 | 动作尝试截断 | B 格式通过 | 实际启动/完成续局 | 输出 token |
|---|---:|---:|---:|---:|---:|
| free_outcome | 24 | 24 | 不适用 | 0 / 0 | 24,576 |
| bp_outcome | 24 | 24 | 不单独调用 | 0 / 0 | 24,576 |
| bp_branch | 30 | 24 | 6 / 6 | 0 / 0 | 24,276 |

总计 78 次请求、73,428 个输出 token；72 次动作尝试全部截断。三组各消耗 24 个预分配槽位，但**不是各完成了 24 次 rollout**。三组收益均为 null，分支组全部信用掩码为 false。不能把这次结果用于能力或三组训练效果比较；optimizer 更新仍为 0。各组生成耗时之和约 23.3、30.0、22.5 分钟，三个进程并行，不能把三者相加当墙钟耗时。

核对通过：三组源码/题包/配置一致，源码哈希也匹配本地；模型路径、tokenizer 和 chat template 标识一致（未独立对模型权重文件做哈希）。所有请求的 token ID/logprob 数量和 usage 一致，prompt 未超上下文上限；P 使用对应 B 的原始 token 前缀；B+P 合计上限 1024；retry 沿用同一 prompt/预算且失败记录独立。缺失动作没有执行 PASS 或伪造终局零收益。三组原生历史都停在初始 prefix。

### 12.1 新的 B 格式提示被当成标题照抄

`bp_branch` 六次 B 输出都只有 16–17 token，例如 call 0：

```text
<B>Judgment about partner preferences and behavior, its evidence and uncertainty</B>
```

其余只是添加 “My” 或空格。`bp_outcome` 的 24 次回复也全部先生成描述性 B 标题，其中 23 次为上述措辞的变体，1 次为 “Joint Preferences and Partner Behavior Judgment”。实际推断写在关闭 B 标签后。仅 1/24 个联合 BP 回复出现 `<P>` 开始标签，分支 P 的 24 次回复均没有出现 `<P>`。

直接证据支持 prompt 中 `<B>your judgment ...</B>` 的说明被解释为要输出的标题，而非在标签内填入实际判断。当前 B 校验只要求标签内非空，所以 `status=ok` 只代表结构通过，不能说六个有效信念已经生成。这个边界目前不能作为 B token 学习区间。修复应首先明确标签内应写实际推断，不靠新增 solver 标签判断 B 真伪，也不能用简单禁词代替真实生成验证。

### 12.2 所有动作都在形成提交前截断

72/72 次动作回复都没有 `<ACTION>` 或 `</ACTION>`，不是完整动作被 stop/解析器漏收。free 和 joint BP 每次生成 1024 token；branch P 根据 B 长度生成 1007/1008 token，全部返回 `finish_reason=length`。API 展示文本与实际 token 解码内容一致或为其前缀，B 的差异仅尾部空白。

回复大量重述目标、目录、规则、当前局面，再逐个展开动作；例如 free call 0 在“Step 4: Analyze the Rejected Offer”内部结束。也有算错后反复解释规则的片段，但不能据此把全部截断都归因为重复 loop。当前证据是输出冗长、边界指令未落实，以及夹杂推理回溯。按既定约定先保留 1024，不引入重复惩罚；应先修正精简作答要求，明确数值预算和动作提交的空间，再做极小真实请求预检。

### 12.3 能力错误存在，但这次不能由最终选择评分

例子来自原始文本，不能外推为所有回复的错误率：

- `bp_branch` call 11 先正确列出 Player 2 的 `(neutral, avoid, want)`，随后将它解释为“avoids Goal 2, wants Goal 1”，交换了归属。
- `bp_branch` call 1 将 Player 2 向 Player 0 提议双方承诺，与需要 Player 1、Player 2 承诺的 Goal 2 混淆，继而认为 Player 2 的 PASS 与策略矛盾。
- `free_outcome` call 7 在已经存在信息性历史的题里用未更新的两类各半概率计算 Player 1 接受提议的价值。

这些可以保留为能力诊断，但当前最先要解决的是可用 B/P 边界和动作输出。没有完成动作，无法评价最终决策正确率或 B 对 P 的实际影响。

### 12.4 下一轮必须先做真实生成预检

我此前在只有脚本控制通过的情况下就交付完整三组真实小测，未先用真实模型确认边界和提交行为，这是本轮验证流程的缺口。暂不原样重跑整个三组包。

1. 改清 B/P 标签指令，避免把标签内解释文字当输出模板；三组统一要求简洁、减少题面复述，为完整动作留出空间，仍共享 1024 token、最多一次 retry。
2. 对 free joint、BP joint、分支 B→P 三种调用路径各做一个真实预检，人工查看实际 B 内容和动作；这通常至少需要四次请求。先验证边界、token 前缀和合法动作，再跑整包。
3. 增加逐请求进度与预检失败退出，避免所有请求同样失败仍耗尽预算。预检与正式组间预算分别记录，不能拿预检成功率冒充实验分数。
4. 真实预检通过后再重跑三组小测；训练参数更新、独立数据集及 token 级信用仍属于后续未完成工作。


## 13. 根据原始 prompt 修订：自然段伙伴判断与定性行动依据

当前版本 `social-three-arm-pilot-v2` / `social-natural-paragraphs-v2`。此次只修改本地代码与验证，没有上传、生成远程新结果或更新模型参数。

已核对 [ToMA v1 附录 C、Figure 15–16](https://arxiv.org/pdf/2509.22887v1)：心理状态生成用一段自然语言，围绕证据形成可用于下一步行动的判断；行动 prompt 又有自己的 JSON 结构。这里借鉴其自然语言心理状态表达，不声称该工作完全没有格式要求，也不照搬其多维度覆盖约束。[SocialRL §5.4](https://arxiv.org/html/2608.13787v1) 的结构提示本身未改善基础模型表现，也说明不能把增加输出结构当成已验证的能力改进。

本轮修改：

- 移除 B/P XML 标签及标签内占位说明。显式组第一自然段写伙伴判断，空行后第二自然段写行动依据。分支采样在首个空行暂停；P 仍接收相同 prompt 加实际 B token IDs，没有另加 user 指令。自然段边界是本项目的工程选择，尚未证明真实模型能稳定遵守。
- 系统说明由最大化数值 utility 改为实现 wanted goals、避免 unwanted outcomes；移除 +1/0/-1、求和、期望 utility 等教学内容。明确不计算 utility、分数或期望值，不复述规则、目录、动作清单，不逐项枚举。三组同样要求最多 120 英文词的理由，动作 JSON 不计入该词数。这是 prompt 指令，不新增长度或重复惩罚。
- 伙伴规则改为在实现其想要的目标、且不导致其避免的目标时提议或接受。该定性描述适用于当前三道小题的可达状态；已穷举小题合法行动后的伙伴回应，与环境原规则一致。不能未经复查推广到存在多目标得失权衡的新任务。
- 游戏事实、偏好归属、不可逆承诺、最终回合规则保留；原生环境收益计算与归一化保持不变。模型侧不要求计算奖励。
- 最终动作继续使用三组统一的 ACTION 包装和完整合法对象；本次移除的是 B/P 标签。B 合法性仍只校验可切分的非空自然段，不用 solver、禁词或推理正确性标签充当格式判定。
- 添加 `--preflight`：free joint、BP joint、branch B、branch P，正常需四次请求，任一路径在既定 retry 后仍失败即停止。成功只表示结构通过，`semantic_review_required=true`；实际内容仍须检查。预检独立于实验 rollout 预算。
- 每次请求结束立即打印 case、阶段、retry、状态和 token 数，写入各组日志。

验证：44 项测试中 43 项通过、1 项跳过；脚本预检四条路径通过；三进程脚本小测仍各完成 24 个续局槽位。尚未做本轮真实模型预检，不能说标签照抄和冗长问题已在模型上解决。

完整 system/user 消息：`new/local_data/social_runs/social_prompt_v2_preflight_scripted/prompts.txt` 与 `prompts.json`。下面为代码中实际使用的公共 system 内容；每组再追加对应格式要求，user 消息包含实际游戏事实。

```text
You are the player identified in the input. Choose an available action that helps achieve your wanted goals while avoiding unwanted outcomes.
A goal is achieved only when all of its required actions are committed. Want, neutral, and avoid describe a player's attitude to the whole goal. Goal requirements do not reveal anyone's preferences. own_preferences belongs only to the identified player; each catalogue belongs to its named player.
Offers describe the complete commitments both parties would have after acceptance. A pending offer has not changed commitments. Acceptance makes commitments binding; rejection leaves them unchanged. PASS or resolving an offer consumes the current proposer turn. Resolving the last turn ends the game.
Use the observed partner behavior to judge what the partners want and how they may respond. Keep uncertainty where the evidence is insufficient. Use qualitative judgments about goals and responses. Do not calculate utility, scores, or expected values.
Give only the key grounds for your choice, in at most 120 words of reasoning. Do not restate the rules, catalogues, or action list. Do not enumerate every candidate or write a step-by-step calculation. Use plain prose without headings, lists, or tables.
Then submit one exact object from legal_actions between <ACTION> and </ACTION>. The JSON is separate from the reasoning word limit. Action IDs identify commitments, not positions in the action list. Complete the entire response within 1024 tokens.
```

自由组追加：

```text
Briefly explain the grounds for your choice in your own way, then submit the action.
```

显式两组追加：

```text
In the first short paragraph, state what you infer about the partners from their behavior, including what remains uncertain. After a blank line, write a second short paragraph explaining which action you choose and why those partner judgments support it. Then submit the action. Start directly with your actual judgment; use no section labels.
```

## 14. v2 真实预检失败定位与 v2.1 小修

`new/local_data/social_runs/social_prompt_v2_preflight_remote/` 已下载。free joint 两次请求分别生成 175、176 token，finish_reason 均为 stop，均以 `<ACTION>6</ACTION>` 结束。API 文本与 token 解码一致；失败来自把动作列表位置当提交内容，不是截断或终止 token 解析问题。其余三条生成路径尚未执行。

输出也有能力错误：将 Player 1 的偏好说成避免 goal_1，猜测自己此前拒绝的动机，或称已 PASS 的 Player 2 尚未行动。没有有效动作提交，不能计算本次动作收益或推断 B→P 成功。两次短输出不能证明所有局面的冗长问题已解决。

本地修订为 `social-natural-paragraphs-v2.1`：明确 ACTION 内必须复制 legal_actions 的完整 JSON 对象、包含全部字段，以花括号起止，不能提交数字、列表位置或 action_index。没有自动把 6 修复成合法动作，也没有提供偏好或最优动作答案。日志增加 `validation_error`，此类错误记录为 `action_must_be_object`，原有 format_failure 与 -1 失败评分不变。相关 13 项测试通过，包含本次数字动作回归测试。真实模型是否遵守仍待新目录预检；本次没有上传或启动远程任务。


## 15. 恢复原生动作工具，并验证固定 B 的续写

当前 `social-three-arm-pilot-v3` / `social-native-tools-v3`。接口不再使用 `<ACTION>` 或裸 JSON；原有三组文本协议是历史回退，不应继续使用。必须继承的约束：原生 SUBMIT_ACTION、完整合法对象、无 action index/自动修复、环境计算奖励、1024 总预算、一次 retry。分支实现适配这些约束，不能反过来替换动作协议。

本轮复用 `social_lm_eval.tool_for('P', ...)` 的 schema；通过 `/chat/completions` 发送 `tools`、`tool_choice=auto`、`parallel_tool_calls=false`。最终动作只从服务原生 `message.tool_calls` 读取。正文中的数字、裸 JSON、SUBMIT_ACTION(...) 和 tool_call 字样都不能补成动作。模型工具调用和日志中的原始生成 token 分开保存。

固定 B 续写：原始 messages 后追加未结束的 assistant 内容，使用模型原始工具模板生成的完整前缀作为精确渲染模板，不添加新 user 消息，不让默认 continuation 去掉 B 末尾的段落空行。本地 round-trip token IDs 和远程 CPU `/tokenize` 必须逐 token 等于原始 prompt+B，chat 返回 prompt token 数再次核对。任何不一致直接判接口失败，不静默换成重分词后的 B。原始模型 token、生成 logprobs、原生 tool_calls 都保存。其依据是 [vLLM 0.8.5 chat 实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.8.5/vllm/entrypoints/openai/serving_chat.py) 与 [tokenize 实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.8.5/vllm/entrypoints/openai/serving_tokenization.py)；实际运行验证比仅检查源码更关键。

真实验证在本地运行新客户端，通过 SSH 转发访问远程 8001，未向远程上传源文件。最终结果 `new/local_data/social_runs/social_native_tools_preflight_r4/`：

| 路径 | 生成 token | 原生工具 | 结果 |
|---|---:|---:|---|
| 自由 joint | 215 | 1 | 首次通过 |
| BP joint | 308 | 1 | 首次通过 |
| B | 133 | 0 | 首次通过，实际伙伴判断自然段 |
| 固定 B 后 P，seed 7 | 169 / 剩余891 | 1 | 首次通过 |
| 同一个 B 后第二个 P，seed 8 | 168 / 剩余891 | 1 | 首次通过 |

`branch_prefix_check.json` 和 `verification.json` 记录核对结果。BP joint 的前133 token 也与独立停止的 B 完全相同。两个 P 使用相同的 2200-token prompt 前缀，均通过服务端核对并返回原生 SUBMIT_ACTION。此结果证明当前服务可以保留原生工具实现 B 分支，不是实现不可能。

这些是接口可行性证据，不是能力结论。模型仍混淆偏好、拒绝者身份和目标条件；本地重放合法动作，自由组此例自身终局收益1，联合 BP 和两条 P 收益0。不能因接口通过声称 B 判断正确或方法优于基线。

本地46项相关测试中45通过、1跳过，包含真实 chat 请求工具字段、原始 B 前缀、原生响应读取，以及拒绝正文伪工具/数字动作的回归检查。

过程中发生过两类问题，保留记录而非覆盖：

- `r3` 的早期原生请求仍有正文伪工具调用；将每组任务结尾也明确为使用提供的工具后，最终 r4 五次调用均首次通过。
- `r1` 为核对前缀请求 prompt logprobs，在共享 GPU 显存紧张时触发8000 OOM退出（日志申请2.20 GiB、仅约500 MiB空闲）。最终实现取消该 GPU 校验，改用 CPU tokenize，生成部分 logprobs 保留。已按原设置在物理GPU2恢复8000，新PID570874，日志为 `outputs/logs/social_vllm_8000_recovery_native_tools.log`，PID文件已更新。

源代码上传再次被自动审批拒绝，理由为缺少明确代码 payload/目的地授权；采用本地执行客户端作为替代，未绕过审批向服务器写入实现文件。故远程 training/b_sft/social_three_arm.py 仍是用户此前上传的旧版，正式重跑前需同步本地新版。

## 16. v3 原生工具预检的 reasoning 逐项审查

范围严格限于 `social_native_tools_preflight_r4` 的一个局面、一条不同的 B 内容、联合 BP 和两个条件 P。联合 BP 的 B 与单独停止的 B token 相同，不能把它们当作两条独立 B 样本。不是对训练分布的能力准确率估计。

长度：B正文102英文词；P正文80、77词；联合BP178词；分支拼接分别182、179词。此前169/168个P生成token还包括原生工具序列，不全是reasoning。120词只是prompt中的软要求，实际联合BP未遵守；仍均远低于1024 token硬上限。不能把错误归为推理被截短，也不据此增加长度惩罚或调高上限。

本题事实与无数值计算的正确推断：Player 1向Player 0提议双方承诺，Player 0拒绝，Player 2随后PASS，当前是Player 0最后一次提议，所有承诺仍为空。Goal 0需Player 0+1，Goal 1需Player 0+2，Goal 2需Player 1+2。Player 1的Goal 1始终neutral、Goal 2始终want；Player 2的Goal 0始终neutral、Goal 2始终want。根据明确的伙伴行为规则，Player 1提议说明它想要Goal 0；Player 2在同样可提议时PASS说明它避免Goal 1。最终应向Player 1提议双方承诺，Player 1会接受；Player 2会拒绝相应提议。原生环境重放已核对。

| 文本位置 | 模型陈述 | 核对结论 |
|---|---|---|
| B call2 | Player 0+1的联合承诺会实现Goal 0和1 | 错；此时只实现Goal 0，Player 2没有承诺 |
| B call2 | Player 1想要Goal 1、避免Goal 2 | 与公开目录直接矛盾；分别是neutral和want |
| B call2 | Player 1拒绝了该提议，所以不愿合作 | 拒绝者是Player 0；从错误事件归因进一步推断伙伴意图 |
| B call2 | Player 2的PASS可能表示neutral或风险回避 | 其关键Goal 1候选只有want/avoid，且题面给定确定性行为规则；该PASS已能区分，不能凭空加入风险厌恶机制 |
| P call3 | Player 0+2联合承诺能实现Goal 1和2 | 错；Player 1没有承诺，Goal 2不能实现 |
| P call3/4 | Player 2想要Goal 1，因此会接受 | 忽略PASS证据；该局面中它避免Goal 1，会拒绝 |
| P call4 | Player 2避免Goal 0 | 与公开目录直接矛盾；始终neutral |
| free call0 | 自己避免Goal 2，并且Player 0+1会实现Goal 0和1 | 同样有偏好/目标条件错误，但最后选择Player 1碰巧是正确动作 |

B并非完全没读输入：它提到了提议、PASS及自身正确偏好。但这些事实没有组成可靠的伙伴解释。P也不是完全没有行为判断：它明确声称伙伴会因目标一致而接受；然而该理由依据错误事实。因此不能认定当前reasoning是合理的社会推断，只能认定结构和工具接口已跑通。

足够简短的合理文字示意（仅用于本次审查，不作为新增教师答案或few-shot示范注入）：

B: Player 1's proposal indicates that it wants the goal shared with me. Player 2 passed despite having the same opportunity, so under the stated policy it avoids the goal shared with me. My rejection of Player 1's earlier offer is not evidence that Player 1 was unwilling.

P: I will offer the joint commitment to Player 1. It is willing to accept and this achieves one of my wanted goals. Player 2 would reject the corresponding offer, and there is no later proposer turn.

后续工作分清层次：

- 当前明确的偏好归属、事件角色、目标联合条件及从证据推断伙伴响应错误，主要是该小题上的能力现象。不能不断把每道题的结论写进prompt，也不能在模型生成后用人工理由修正奖励。判断动作是否实现目标是任务理解，不等同于要求模型计算utility。
- free正确动作但理由错误，仍按真实终局奖励记账；这是outcome监督的局限/研究现象，不是环境奖励算错。BP错误动作得到对应失败结果也符合约定。
- 现有同B两个P选择完全相同，收益也相同，因此这两条P之间没有相对信用差；只有一条B，尚不能估计B之间的差异。还没有证明分支采样能提供有用的细粒度学习信号。下一步应在固定模型的小批次中记录不同B/动作比例、全零信用比例及信号方差，不因一例无差异就认定方法无效。
- 还缺完整多决策续局、更多伙伴策略、独立训练/测试分布、三组参数更新接口、token级信用归属与共享B去重。此次5次生成不是三组训练或完整数据审查。
- 结构成功不等于120词要求遵守，也不证明自然段是语义上纯B/纯P的分界。需要保留内容审查；不要把段落格式当作能力监督。

## 17. Expanded native-tool remote r1：覆盖扩大后未通过（2026-09-11）

结果：`new/local_data/social_runs/social_expanded_native_r1/`。逐项回放与汇总见该目录 `audit.json`。本轮仅下载、审查，未修改生成协议或启动新测试。三组均为 v4 / native-tools-v3，题包、tokenizer、chat template及所记录的五个源文件哈希一致，并与本地源码吻合；不是旧版 action-index 代码误跑。

| 组 | 终局 / 预算槽 | 请求 | 格式失败请求 | retry成功 / retry次数 | 多决策局终局 |
|---|---:|---:|---:|---:|---:|
| free_outcome | 31/48 | 55 | 31 | 7/19 | 0/8 |
| bp_outcome | 20/48 | 55 | 40 | 6/23 | 0/8 |
| bp_branch | 12/48 | 68 | 39 | 1/20 | 0/8 |

预算槽不是独立模型样本：同一根动作会在多个隐藏世界续局，一个根生成失败也会使其对应的多个世界槽失败。三组各7题、28个根动作位置；分支组另有14个B生成。总174次请求，110次格式失败，没有截断或基础设施失败，单请求最长308 tokens。不能把仅成功子集的平均收益用于三组能力比较，也不能声称多决策流程已经通过。

### 17.1 原生工具输出仍不稳定：首要阻塞

104次失败均为 `expected_one_native_tool_call`：返回 `tool_calls=[]`，原始生成也不含 `<tool_call>`，而是在普通正文输出 `SUBMIT_ACTION({...})` 或 `SUBMIT_ACTION{...}`。例如 free call6、bp_branch call4。这是模型没有按原生工具协议生成，不是解析器漏读有效工具标记；参数里也不再是 action index。现有prompt/模板/模型组合只证明了少数样例可用，不能据此视为接口稳定。

本轮保留严格原生工具接口，未通过解析正文抢救动作。下一步应先在已有失败请求上做小规模、固定样例的协议复现与修正验证，保持 reasoning＋native tool call 的目标。不能直接改成无reasoning的强制动作输出，也不能再换回自定义文本JSON协议。是否需要调整模板或工具调用约束，需要实际验证，当前审查尚未确定修复方案。

### 17.2 空行不是可靠的语义B/P边界

其余6次失败为 `invalid_BP_paragraph_boundary`：bp_outcome call14、16只有一个解释段，但已有合法native tool call；bp_branch call20–23的P正文为空，但均已有native tool call。

对应bp_branch B call19已经在第一段包含伙伴判断、动作比较及“I choose to offer...”的完整选择；在其后的空行截断后，续写直接调用工具，不能得到第二段P。B call3也已把“只有给P1的共同承诺可行”的规划结论写进第一段，call4–7随后直接输出文本形式动作。这说明14/14个B被格式接受，不等于得到了14条可独立归因的belief reasoning。若直接按第一段/第二段分配学习信号，会存在B token实际包含P分析的问题。

应先明确如何获得稳定且可解释的B/P切分，再构建token级信用归属；不能靠补一个空P、复制理由或仅放宽段落校验宣称问题解决。不引入新的人工reasoning正确性reward。

### 17.3 能力现象仍明显，不能与接口失败混为一谈

- bp_branch B call0将ego拒绝P1的offer说成P1拒绝，并把P1固定中立的goal1说成want、固定want的goal2说成avoid。
- B call14、19把明确标记为setup、与偏好独立的PASS解释为伙伴不愿合作的证据。
- B call28把pending offer描述为伙伴已经commit；题面明确pending不改变承诺。
- 多决策续局call46虽格式通过，却把共同承诺0+1误说为也实现其他目标，并以错误伙伴偏好拒绝offer。
- free call0选择了会被接受的正确共同承诺，但理由仍把ego neutral的goal2说成需要avoid，并错误声称该承诺同时实现goal0和goal1。正确outcome不等于正确reasoning。

这些实例的题面已有明确事实，主要属于希望训练改善的理解和推断能力，不应逐题把答案写进prompt或事后改终局奖励。此处为有定位的定性审查，没有给全部reasoning编造准确率。

### 17.4 已核对的正确部分与尚未验证的部分

- 全144条已记录历史可通过原生规则逐步合法回放；63个终局的utility和归一化reward复算一致。全部未完成槽的reward为null。
- 18次后续决策引用的request题面与各自实际历史前缀完全一致。确实进入过后续局面，但24个多决策槽全部未完成，其中15个进入后续模型决策，其余根调用已失败。
- 分支28个根P最终尝试的输入token均等于原始prompt+B token，剩余额度等于1024减B长度；全174次返回的token数/logprob数/usage一致，均记录server tokenization校验成功。
- 失败尝试仍单独记录，最多一次retry；14/62个retry恢复，48/62仍失败。当前重试只更换seed，没有针对失败反馈，不能视作已解决整局中断。
- outcome矩阵从各world的实际终局重新聚合一致；分支7个比较中6个因缺失结果整体mask，唯一完整的 `evidence_partner_2` 矩阵全0，B/P信用全0。14条B文本各题两条均不同，但文本多样性不证明行为差异或有效信用。本轮没有任何非零可用分支信用。
- 当前“7类覆盖”依然是同一3人/3目标小任务骨架及同一种确定性伙伴政策，变化是证据、ego偏好、决策阶段与轮数。未覆盖更丰富伙伴行为或证明robustness。三组预算槽相同，实际完成数、请求数和token成本不同；不是训练效果对照。

结论：先解决原生工具输出可靠性及B/P边界定义，用本轮保存的失败样例做回归，再重跑相同扩展题包。1024上限不是本轮瓶颈，不增加token限额或重复惩罚。多决策终局、可用非零分支信用和优化器更新仍未验证。

## 18. 原生前瞻拒绝实例：讨论用构造与精确核验

本轮构造而非随机挖掘；不调用 LM、不更新参数、不修改生成接口。复现脚本：`training/b_sft/debug/audit_forward_refusal.py`；结果：`new/local_data/social_runs/forward_refusal_discussion_v1.json`。

三人，P0 的 d 已通过公开 setup 承诺，P1 有 a/b 两个承诺，P2 有 c。轮序为 P0、P2、P1；当前 P2 提议 P1 承诺 a，自己不新增承诺，P1 响应后还剩最后一次自己的提议机会。整个 prefix 都是与私有类型独立的公开干预，不当作 oracle 生成证据。

| 目标 | 条件 | P0偏好 | P1偏好 | P2偏好 |
|---|---|---|---|---|
| G0 | d+a | want | want | neutral |
| G1 | b+c | neutral | want | want |
| G2 | d+b+c | want | want/neutral/avoid | neutral |
| G3 | a+c | neutral | neutral | avoid |
| G4 | a+b+c | neutral | neutral | avoid |

仅 P1 对 G2 未知，三种候选等先验。原生动作完整保留，max_changes=1，承诺不可撤回。复用 SharedWindow 精确有限窗口求解器，最多覆盖当前响应与下一提议/响应，恰好到真实终局；38个树节点。

P1 若先接受得 G0 的 +1。随后即使提议 b+c，P2 接受会同时实现 G1/G2/G3/G4，对 P2 为 +1-1-1=-1，因此严格拒绝；不合作为0。若先拒绝再提议 b+c，P2接受只实现G1/G2，对P2为+1，因此严格接受。不可逆a造成的是伙伴合作动机变化，不是凭空禁止后续动作。

| P1对G2 | REJECT续局自身/他人总收益 | ACCEPT续局自身/他人总收益 | 根部全部可接受动作 |
|---|---|---|---|
| want | 2 / 2 | 1 / 1 | REJECT |
| neutral | 1 / 2 | 1 / 1 | REJECT（利他平局） |
| avoid | 1 / 1 | 1 / 1 | REJECT、ACCEPT |

avoid类型可先拒绝，再向P0提议原来的a，从而仍得G0的+1；不能删掉这条合法替代路线。旧求解器选择REJECT作为残余平局代表，但讨论中的B兼容集合必须保留全部同值动作；因此只看到根REJECT仍保留三种偏好，不能错误排除avoid。完整B更新须另行核验后续动作在所有允许平局下的相容性，当前未导出训练标签。

截止对照改轮序为P0、P1、P2，以额外公开setup PASS使同一pending offer发生在最后提议回合，当前承诺及pending内容不变。无后续机会时，三种类型均严格ACCEPT（1>0）。该对照说明原例的want类型拒绝正收益提议确实依赖未来机会。

核验：六条根动作×类型分支原生重放到终局；全部叶子×世界共72项按ALL_OF条件独立复算收益；两条根路径下P2对b+c的接受/拒绝收益复算；截止对照三种类型均通过。自身信息约束与有限窗口稳定策略检查沿用旧SharedWindow。未证明任意一般和均衡唯一性，亦未解决长游戏截止估值。该例可作为前瞻与信息保持的讨论样本，不是随机生成覆盖、LM能力验证或完整形成/维持/更新数据集。

## 19. B oracle 首版原生机制审查（2026-09-12）

用户批准开始实现本地机制验证，不启动LM或训练。新增独立模块 `social_b_oracle.py` 复用 `shared_teacher.SharedWindow` 与原生规则；不替换既有B/P、三组测试或工具接口。审计入口 `debug/audit_bounded_b_oracle.py`，结果 `new/local_data/social_runs/bounded_b_oracle_v1/audit.json`，明确 `training_ready=false`。

### 可执行约定

- 枚举完整候选偏好配置，每个行动者只按自身偏好及公开相容世界做决策。未知伙伴收益按行动者的信息集求均值，绝不使用实际隐藏世界打破平局。
- 实验参数为1/2/3个完整proposal回合。截止评价使用当时已实现ALL_OF目标的原生收益；不会把pending视作承诺，不把未终局的窗口值叫终局收益。
- 复用有限窗口信息集最佳响应稳定点求解器，按自身价值、其他玩家总价值两级最大化。它不是全局均衡唯一性证明。
- 根部所有同值最优动作都可执行、都被逆推接受；生成/逆推使用同一根部动作集合。用于演示轨迹的first/last选择不成为排除偏好的依据。
- 每次动作之后更新相容集合并重新规划。窗口内价值仍按求解器的冻结参考续局计算，因此存在滚动重规划与参考续局不一致的可能；不能声称这些价值就是任意后续执行下的实际Q。
- setup和intervention只改变状态；partner事件才筛选候选。非法动作、零支持动作、求解失败不删除候选或重置先验，不伪造成功标签。
- 多候选时favored为undetermined，单候选时为该值。这没有定义相对支持强弱：未规定同值动作的概率，所以均匀剩余世界只是计算决策价值的公开参考规则，不声称是精确贝叶斯后验。没有沿用旧1.25阈值或擅自增加概率奖励。

### 实际结果

5个构造场景：前瞻拒绝、截止对照、延长到两轮的前瞻拒绝、旧捆绑拒绝、旧捆绑截止对照。每个根部比较三个视野及正反动作顺序；每个世界另用first/last两种同值选择在两回合视野下完整执行。

- 30项根部检查成功；30条完整路径合法重放到终局，无求解失败；所有生成路径上真实偏好始终保留、集合不扩张。
- 1686项叶子×世界收益独立复算一致，其中包含未终局截止叶子。
- 正反动作顺序的15组根部比较，全部同值动作集合与所有根动作的逆推支持集一致；不推广为所有游戏均与均衡选择无关。
- 1→2回合：前瞻拒绝和长局前瞻拒绝的动作/B支持改变。want类型的REJECT/ACCEPT估值由0/1变成2/1。
- 2→3回合：五个场景根部动作与逆推支持均一致。长局前瞻的两、三回合搜索均未到真正终局（分别38、209节点），所以这不是仅仅因为两者都搜到底。不过仍只有一个长局骨架，不能据此确定通用视野。
- 前瞻实例中：根REJECT保留三种类型，接着提出b+c排除avoid，P2的ACCEPT继续保留want/neutral；根ACCEPT只兼容avoid。所有残余平局保留，未将其解释为独立favored证据。
- 轨迹检查点含78次集合维持、24次缩小；8/30条路径最终单元素。计数含重复世界/选择器路径，不是独立均衡数据集；没有一条路径出现两次以上集合缩小，因此尚未覆盖充分的多次更新与长时记忆要求。
- 22项测试通过（8项新增oracle测试、8项shared teacher、6项既有social cases）。新增测试检查视野效应、利他平局、所有同值动作保留、后续证据更新、私有信息边界、干预不筛选、失败原子性与原生收益。

复现：

```bash
python -m unittest training.b_sft.test_social_b_oracle training.b_sft.test_shared_teacher training.b_sft.test_social_cases -v
PYTHONPATH=. python training/b_sft/debug/audit_bounded_b_oracle.py --out new/local_data/social_runs/bounded_b_oracle_v1_rerun
```

结论：首版作为可审查的有限理性逆推机制已经能执行；两回合是当前小场景的候选值，不是最终统一配置。尚未验证多次更新、伙伴/拓扑泛化、全树平局选择稳健性及滚动重规划价值的一致性；favored相对排序未定义。下一步应先针对这些缺口扩展原生实例，而不是将本轮结果转成大批训练标签或声称模型能力已验证。

### 长局中的具体反例：根部稳定不保证实际续局价值

`audit.json` 的 `paths` 中，`case=forward_long, world[1][2]=1, selector=last`：P1先拒绝，再提议P2单独承诺c；P2接受时窗口自身估值为+1。后续P0提议P1承诺a，P1接受，最后P1再承诺b；P2由于已承诺c不能撤回，最终同时得到G1和不喜欢的G3/G4，终局收益为-1，三人终局收益为[2,3,-1]。这些动作逐次均属于各自当时重新计算的最优集合，且使用合法信息。该单路径不等于估计器偏差的统计证明，但明确展示窗口估值不能当成实际终局收益，以及冻结参考续局/滚动重新规划可能导致预期机会失效。`selector=first`同一隐藏世界终局为[1,2,1]，也说明仅测试根部动作顺序未穷尽后续平局影响。

当时据此暂缓通用长局训练教师的判断，后经用户讨论修正：有限窗口向后移动及最终受损本身不是机制错误，也不要求通过无限扩大窗口消除。以下修订取代此前将滚动价值不一致视为必须修复缺陷的判断。小场景自洽仍不足以证明训练价值。

### B 定向修订 v2：历史决策依据与保留不确定性（2026-09-12）

用户明确接受有限理性：每次真实行动使用当时信息及新的完整有限窗口；不要求预测未来玩家重新规划后的所有行为。B仍只推断偏好；逆推调用的是历史行动者当时的决策机制，不是要求B输出未来预测。未实施此前讨论但未确定的“规划中冻结所有B”方案，保留SharedWindow窗口内的信息集参考策略。该求解器的固定点选择与有限窗口估值是具体机制假设，不是普适人类理性的定义。

`social_b_oracle.py` 版本更新为 `social-b-bounded-oracle-v2`。原有逐动作完整窗口和集合筛选算法已经符合上述滚动约定，因此保留其行为，改进B可审查性：

- 增加带明确事件来源的历史重放入口 `BeliefOracle.replay`，从初始候选逐步重建；不会用最终支持集、观察者私有真值或终局收益重新解释过去。未标注来源的事件拒绝处理。
- 每个事件保存行动前公开状态、pending、候选世界及行动后支持；每种行动者候选偏好保存决策回合、截止回合、自身最优动作和两级最优动作。
- 排除原因区分自身价值不足与利他平局规则；残余平局全部相容，不因演示选择器或并列动作数量排除候选。
- 保留 `possible_preferences` + `favored`：单元素时favored为该偏好，多元素为undetermined。不利用并列动作数量或候选世界数量产生相对偏好排序；undetermined不宣称真实概率相等。
- 新增长局回归：P2接受时窗口估值+1、终局-1，历史相容判断仍然有效。检查每次实际行动截止为当前proposal回合+2（受真实终局限制），每步保留真实候选，早期证据不会被后续结果覆盖。

验证：26项单元测试通过（新增4项），语法检查通过。重跑同一5场景审计：30根检查、30完整路径、0失败，1686叶子收益核验；30条完整带来源历史重新执行B推断，事件级证据及最终支持一致。78次维持、24次缩小、8条最终单元素，与v1行为一致，符合本轮未修改行动机制的预期。结果位于 `new/local_data/social_runs/bounded_b_oracle_v2/audit.json`，每个检查点附B证据。

这些是同一机制下的历史重放和回归检查，并非独立证明机制正确或数据高价值。仍需扩展多次有效更新、不同游戏结构和偏好配置，并检查固定点/内部平局选择敏感性；尚未形成均衡覆盖的数据集。无LM请求、无参数更新、无远程任务，`training_ready=false`。

## 20. B 数据集两路首批尝试（2026-09-12）

用户授权同时尝试手工setup和随机配置后筛选。实现 `social_b_dataset.py`，复用现有 `forward_fixture`、`bundle_fixture`、`compensated_fixture`、原生 `generator.generate_game` 与 v2 B oracle；没有复用旧MCTS/SFT标签，也没有改动LM提交工具。`debug/audit_social_b_dataset.py` 做历史依赖与参考策略选择敏感性审查。正式本轮开发包路径为 `new/local_data/social_runs/b_dataset_review_v2/`；v1为首次中间产物，保留不覆盖。

### 范围与筛选

- 4个手工来源：前瞻拒绝、两轮延长版、捆绑拒绝、补偿接受。随机尝试18个固定seed（920000–920017），抽样2/3/4玩家、每人2个commitment、玩家数+1至两倍玩家数的goals、两轮随机合法轮序。使用原生生成器采样偏好；查询伙伴的一个goal独立展开want/neutral/avoid，其余背景固定公开。当前不是多伙伴、多目标同时隐藏的数据。
- 随机commitment通过偏好无关的合法setup提议/响应获得，不直接篡改状态。全部setup不作证据；后续包括观察者在内的行动都属于声明的自主oracle机制。没有把旁观者自己选择行动误计为新伙伴证据。
- 在每个公开历史枚举当前所有候选类型允许的原生动作，以宽度8、最多80个扩展节点的有限搜索筛选；单个oracle窗口2个proposal回合、3000节点、2秒。每条采集历史都有剩余候选世界见证，真实动作序列合法。搜索剪枝和求解失败分别记录。这是相容历史挖掘，不是自然频率rollout抽样，也不要求每个B检查点之后完成终局。
- 形成严格指3项到2/1项，更新指已缩小后的再次缩小；维持暂选2项保持2项。3项保持3项单列无信息对照，已知单项重复不进入精选配对。每来源每主类别最多3对，无信息对照最多1对，不复制凑平衡。
- 输入与答案、证据分文件：`B_inputs.jsonl`只含观察者信息、原始完整公开目录、实际历史及任务约定；`B_labels.jsonl`保存集合/favored；`pairs.jsonl`保存前后ID及教师侧证据。无理由SFT目标、P动作金标或utility回归目标。Prompt说明使用英文。当前是数据上下文，不是已经接好LM协议的训练任务。

### 数量与验证

22个来源尝试中20个候选配置合法，其中3个随机来源根搜索超节点预算，最终17个来源贡献精选。另2个配置分别违反“每候选保留一个正目标”和“不能允许全neutral目标”的现有原生目录约束，未修补后偷偷纳入。详情见 `attempts.jsonl`。

| 来源 | 形成 | 维持 | 更新 | 无信息对照 |
|---|---:|---:|---:|---:|
| 手工 | 8 | 4 | 0 | 4 |
| 随机 | 24 | 20 | 3 | 12 |
| 合计 | 32 | 24 | 3 | 16 |

75对观测共119个去重问题；集合大小1/2/3分别为19/55/45。75对全部按实际历史重算前后B、逐事件证据和候选见证，并独立调用原生状态转移检查当前状态和pending。4对的后端是终局B检查点，其余不是。27组配对共享完全相同的前缀、随后不同动作导致不同标签；另找到1组当前commitment/轮序/pending及全部其他输入相同，仅历史不同、标签不同的配对。未把一般分支配对冒称为局面完全匹配的历史对照。

新增3项数据测试，连同既有测试共29项通过；包括标签污染能被重放检查发现、查询值独立于背景、setup不构成证据、不会把三项不变误计为形成后的维持。

### 必须保留的敏感性结果

针对119个精选问题，把求解器所有节点的合法动作枚举顺序反转，再从头逆推完整历史：80个标签相同、1个标签不同、38个历史在该另一个参考解下无相容类型。这不是基础设施失败，也不等于原标签在原机制下算错；它说明部分题目依赖求解器内部参考策略/平局代表的选择，仅根部保留全部平局不足以证明全树选择无关。没有修改oracle或把另一机制的标签冒充原标签。

`quality_audit.json`保存逐题状态；`screened_pairs.jsonl`及对应`screened_B_inputs.jsonl`、`screened_B_labels.jsonl`单列两个端点均通过此检查的47对：形成20、维持13、更新1、无信息对照13。这里只通过两种动作顺序检查，不是所有均衡或所有伙伴策略下稳健性的证明。未通过的样本仍留在原文件中，不能把原始75对全部宣称为已验证高价值训练样本。

3对二次更新均来自 `random-920009`，且其中只有1对通过上述顺序检查，绝不是3个独立更新机制。通过者的后端ID为 `3c2d9f174eab2925efee`。该例查询P2对G2的偏好，其他偏好相同：先合作实现P2喜欢的G1，尚不能判断G2；后来P2拒绝会实现G2的提议，排除want，剩neutral/avoid；最后P2自己提议实现G2，neutral不损失自身收益，而avoid会损失，所以只留neutral。中间保留无区分力的提议/拒绝。详细动作、每步支持与原因见审查JSON的`multiple_update_examples`；这些教师分析不进入模型题面。

全包仍为development、`training_ready=false`。所有同源历史、分支留在同组，没有建立train/test，也没有将旧手工骨架当新留出集。下一步应审查上述具体二次更新和内部参考选择敏感样本，再决定补什么结构；当前不支持大规模复制扩充或宣布训练有效。

复现：

```bash
python -m training.b_sft.social_b_dataset --out <new-directory> --seeds 18 --start-seed 920000
PYTHONPATH=. python training/b_sft/debug/audit_social_b_dataset.py <new-directory>
python -m unittest training.b_sft.test_social_b_dataset training.b_sft.test_social_b_oracle training.b_sft.test_shared_teacher training.b_sft.test_social_cases -q
```

## 21. 随机并列机制与 B 更新数据修订（2026-09-12）

用户批准并列最优时随机执行、保留相容偏好、不据随机选择产生favored，并授权继续改进数据集。

### Oracle v3：随机执行，逆推不依赖一次随机抽样

`social_b_random_window.RandomTieWindow`复用旧SharedWindow的原生公共树、窗口截止和私有信息分组；独立实现每个信息集上对残余并列最优动作均匀混合的参考策略。按自身期望收益最大、再按其他玩家期望总收益最大筛选，剩余动作全部获得相同正概率。窗口内续局价值用这些概率对全部分支求和；不抽一条随机续局来决定标签。初始参考表也均匀化，避免通过初始动作顺序选一个代表。

`social_b_oracle.py`升级为`social-b-bounded-oracle-v3`，实际执行经`sample_action(own, rng)`在允许集合中随机选取；逆推仍检查全部允许动作集合，不读取执行seed，也不根据并列动作数量或概率排序favored。多候选一律undetermined。实际行动后重新开完整有限窗口，截止评价及利他规则未改。

这定义了均匀随机伙伴机制下的期望决策，不是对任意伙伴策略/任意参考均衡的全量枚举。决策根部仍采用剩余候选世界均匀权重，作为公开的有限理性参考，不冒称由完整历史似然得到的精确后验。参考策略需达到稳定的信息集最佳响应并通过条件偏离检查；均匀并列策略可能循环或不存在这种稳定点，失败不输出标签，不伪装成undetermined，更不排除候选。

新增测试直接枚举窗口内路径、乘随机行动概率、独立复算叶子原生收益，与期望值核对；检查所有并列概率相同、私有信息组内策略一致、随机seed不改变逆推支持、整条滚动路径反转动作枚举顺序后支持一致、循环失败不污染历史和集合。连同数据/旧teacher/cases共33项测试通过。

### 挖掘与筛选

复用原4个手工场景，分两批尝试120个固定随机seed（920000–920119），未扩大单个窗口预算或改变游戏规则。全局精选上限改为形成/维持/更新各25对、无信息对照13对；按来源轮流选择，每来源主类别最多3对，缺项不复制补齐。

第一批60个随机配置找到8对二次更新，来自4个游戏：920030（3玩家6goals）、920031（4玩家6goals）、920033（2玩家4goals）、920057（3玩家4goals）。后续60个随机配置没有新增二次更新，说明当前随机配置分布对这种证据序列的产出较低。

增加历史消融：保持最后一次行动前的实际物理状态，把此前历史改作不提供偏好证据的外部setup，再仅逆推最后行动。这只是教师侧诊断，不替换真实训练标签。8对更新中6对确实需要早先证据，2对只看最后行动就能得到同样答案，因此后两对留在原候选中，不进入优先更新包。

必须保留的偏差：6对依赖历史的更新最终全部为neutral，路径为三项→want/neutral→neutral或三项→neutral/avoid→neutral。不能据数量增加宣称更新类别已经均衡，更不能通过重复这些分支凑20–30对。后续需要针对更新结果与证据结构设计情境，而不是继续无目标扩大随机seed。

第一批修订包`b_dataset_random_ties_v3`含130问题、71配对；130问题反转整个搜索树的动作枚举顺序后标签全部一致。它们是在v3机制下重新生成的，不是直接保留v2旧标签。该检查不证明所有可能参考解唯一。完整原生随机执行另保存为`sampled_rollouts.jsonl`，与相容历史搜索分开；随机执行失败也单独保存。

候选复用过程中修复了JSON反序列化把tuple变为list引起的证据误报：按规范化JSON比较事件，新增落盘再加载回归检查。这个失败属于数据核验实现，不是oracle推断改变。`b_dataset_random_ties_v4`为该检查中止的尝试，未形成可用包；修复后同一批seed重建为`b_dataset_random_ties_v5`，没有换seed掩盖失败。增加验证前候选检查点、机制版本与源文件哈希检查，后续可复用相同机制下已挖掘候选。

### 本轮最终产物与核验

最终开发包：`new/local_data/social_runs/b_dataset_random_ties_v5/`（oracle版本v3）。124次来源尝试为4手工+120随机；110个候选配置进入挖掘，14个因既有目录合法性约束拒绝。挖掘期间记录19次节点预算失败、11次参考策略循环，不为这些失败节点产标签。

- 原精选131问题、71对：形成25、维持25、更新8、无信息对照13。71对前后B与事件证据全部重放验证。
- 131个问题反转全树动作枚举顺序后标签全部一致。当前样本上的枚举顺序问题消失，不推广为任意参考均衡的唯一性证明。
- 再去掉2对仅凭最后行动即可作答的更新，优先审查包为**129问题、69对：形成25、维持25、历史依赖更新6、无信息对照13**。使用 `screened_B_inputs.jsonl`、`screened_B_labels.jsonl`、`screened_pairs.jsonl`；未优先选用的两对仍在原始配对中。
- 8组同前缀不同后续动作的不同标签配对；另1组当前物理状态和pending一致、历史不同、标签不同。全部仍为开发数据，不构造留出集。
- 实际随机执行共330条路径尝试，254条达到终局且重放B支持一致，76条失败单列（57次节点预算、19次循环）。实际世界始终保留在成功路径的相容集合。终局执行数不等于独立游戏数，不把失败路径伪造成完成。
- `quality_audit.json`保存逐题顺序检查、更新完整支持变化、最后行动消融。源文件哈希与当前代码一致；33项单元测试通过。

6对历史依赖更新仍全部以neutral结束，来自4种不同玩家数/goals规模。这是目前明确的数据分布缺口；没有宣布达到原先建议的20–30对更新规模或训练就绪。未启动LM请求、训练或远程任务。

复现本轮合并包（保留初批缓存，避免重复挖掘）：

```bash
python -m training.b_sft.social_b_dataset --out <first-new-directory> --seeds 60 --start-seed 920000
python -m training.b_sft.social_b_dataset --base <first-new-directory> --out <second-new-directory> --seeds 60 --start-seed 920060
PYTHONPATH=. python training/b_sft/debug/audit_social_b_dataset.py <second-new-directory>
python -m unittest training.b_sft.test_social_b_random_window training.b_sft.test_social_b_dataset training.b_sft.test_social_b_oracle training.b_sft.test_shared_teacher training.b_sft.test_social_cases -q
```

## 22. 两个隐藏偏好与收到 offer 后的 B 检查点（2026-09-12）

用户授权尝试两个隐藏preference，并明确响应阶段也应作为B决策点。延续oracle v3、2个proposal回合的规划窗口和均匀并列执行；没有改变游戏规则、奖励或LM工具接口。

### 实现

- `social_b_dataset.random_fixture`增加`hidden=2`，覆盖同一伙伴两个goal偏好、两个伙伴各一个偏好两种布局。两个槽位独立展开want/neutral/avoid；构造后穷举检查初始联合支持恰为全部9种组合。不能满足既有目录合法性约束的配置拒绝，不根据oracle答案修补游戏。
- 同一伙伴的两项形成9条完整候选偏好行；不同伙伴分别3条，通过原生联合世界笛卡尔积得到9种。观察历史时始终过滤完整世界，随后才取每个查询的边缘集合，不把两个边缘集合重新相乘恢复已经排除的组合。
- 新增回归例：两个单项仍各有want/neutral/avoid，但联合支持从9变8，排除的具体组合不再回来。这验证了关联保存，不能用两个单项答案不变来断言整个联合B没有获得信息。
- 问题明确标记proposal/response/terminal、观察者是否轮到行动、pending为awaiting_response_not_binding。收到他人offer后先更新B并保存检查点，此时尚未执行自己的ACCEPT/REJECT，也尚未添加offer中的承诺。观察他人已经做出的响应另行标记，不与收到offer的检查点混淆。
- 挖掘时优先选择观察者收到offer的检查点，但仍按证据筛分形成、维持、更新、单项无区分力，不把“新offer”自动等同“偏好更新”。在双隐藏情况下，单项无区分力是相对于被查询项而言，联合支持可能仍发生变化。

### 首批结果

开发包：`new/local_data/social_runs/b_dataset_two_hidden_v1/`。两种布局各尝试12个固定seed（930000–930011）；24次尝试中18个配置合法（每种布局9个），6个因现有正目标/全neutral约束拒绝。单次窗口预算未增加。两项分别挖掘的审计共记录4次节点预算失败、4次参考策略循环；这些记录可能来自同一历史的不同查询，不按独立游戏计数。

- 原精选90个单项问题、52对观测：形成20、维持17、更新2、无信息对照13。52对全部逐历史重放验证，90问题反转全树动作枚举顺序后标签一致。
- 38对发生在收到offer、尚未响应时：形成13、维持12、单项无区分力13；另有8对来自观察他人已经完成的响应。配对数不是独立上下文数。
- 2对更新均来自`random-930011-h2-different_partners`，查询P1.G3，分别neutral/avoid→avoid、neutral/avoid→neutral。历史消融显示前者只凭最后行动即可得到avoid，后者确实需要此前证据。因此优先保留1对历史依赖更新；仍不能声称更新结果偏neutral的问题已解决。
- 筛选后89个单项问题、51对（20/17/1/13）。当前两项有时各自不变但联合支持缩小，教师事件记录保留完整前后支持。
- 实际随机执行162条路径尝试，126条到达终局并重放B支持一致，36条失败单列（18节点预算、18参考策略循环）。失败未被当成完成或负面偏好证据。

### 同时询问两项的导出与表达限制

`joint_B_inputs.jsonl`把相同来源/历史/局面的单项上下文合并为**83道两查询题**，其中**36道是观察者收到offer后、即将响应的决策点**。`joint_B_labels.jsonl`沿用现有原生`SUBMIT_BELIEFS`的`judgments`列表，每项仍是player、goal、possible_preferences、favored。83条金标均通过`social_lm_eval.tool_for('B', context)`产生的原生schema校验；未进行LM请求，不能据此声称模型协议通过。

全部83个上下文重新计算联合支持，并与反转动作枚举顺序后的完整世界集合核对一致。教师侧`joint_support_audit.jsonl`保存两项联合候选，其中6题的联合候选不是两个边缘集合的笛卡尔积。现有两个单项set+favored只能监督边缘判断，不能完整表达/直接监督这些相关性；本轮未擅自新增联合输出字段或奖励。

37项测试通过，覆盖联合9组合、9→8且边缘不变的关联保存、pending未承诺、收到offer的响应检查点、既有原生两查询tool schema。源文件哈希与本轮代码一致。仍为development、`training_ready=false`，未启动训练或远程服务。

复现：

```bash
python -m training.b_sft.social_b_dataset --hidden 2 --layout both --seeds 12 --start-seed 930000 --out <new-directory>
PYTHONPATH=. python training/b_sft/debug/audit_social_b_dataset.py <new-directory>
python -m unittest training.b_sft.test_social_b_two_hidden training.b_sft.test_social_b_dataset training.b_sft.test_social_b_oracle training.b_sft.test_social_b_random_window training.b_sft.test_shared_teacher training.b_sft.test_social_cases -q
```

## 23. 定向变体、配对数据与两种 B 评估（2026-09-12）

用户批准定向补数据、按游戏骨架隔离以及独立/连续两种评估，明确不做“不读历史”“始终全部可能”的LM基线比较。本轮没有加入这两种基线；此前最后行动消融仅保留为教师侧样本筛选检查，不作为LM评估实验。

### 数据工作

`social_b_curriculum.py`复用已有两个开发包及当前oracle，选取5个包含历史依赖更新的原游戏，固定goals、偏好候选与初始setup，构造14个受控变体：只旋转后半轮序、反转后半轮序，或把游戏截止提前到第一完整轮。相同轮序去重；setup保持原生合法。没有修改oracle、窗口深度或游戏奖励。

这些变体中未出现求解失败；各分支按同一机制重新生成并验证，没有直接把原标签搬到改轮序的游戏上。例如双隐藏来源930011在两种后续轮序变化及提前截止后均未再找到原来的二次更新，说明轮序确实影响证据出现，而非只改变问题的表面排列。

在完全相同的公开前缀和查询下配对后续行为，得到16组“更新/维持”对照；两种分支都有合法历史和候选世界见证。最终保留18对历史依赖更新，来自5个骨架；3个最后行动已经足够作答的候选更新排除。18对仍全部收缩到neutral，未声称答案分布缺口已解决，也不把同骨架的轮序变体当成独立新游戏机制。

### 数据划分与产物

最终目录 `new/local_data/social_runs/b_curriculum_eval_v1/`。含59个来源、35个游戏骨架、384个B检查点、206条单项前后观测配对（形成77、维持85、更新18、无区分力26）；其中86条配对的后端为收到offer、尚未响应。B检查点统一询问该游戏全部隐藏项，沿用原生SUBMIT_BELIEFS的judgments列表。

骨架规范化对玩家/动作/goal重命名不敏感，且忽略偏好、setup、轮序与游戏长度；因此同骨架的不同偏好或截止变体也不能跨划分。旧`dataset_review.family_id`包含轮序，不适合本次用途，本轮使用更保守的拓扑分组。更新骨架分层分配到三份，其余骨架按固定hash分配，不参考任何LM成绩。

| 划分 | 检查点 | 骨架 | 连续轨迹 | 更新配对 |
|---|---:|---:|---:|---:|
| train | 226 | 19 | 6 | 9 |
| validation | 56 | 10 | 1 | 1 |
| test | 102 | 6 | 8 | 8 |

这是已审查游戏的开发划分，**不是全新盲测论文基准**。特别是validation只有1条连续轨迹、1对更新，不能据此形成稳健的更新能力结论。每个骨架只属于一份；全部变体、历史分支、独立检查点和连续序列均继承它的划分。

文件：`train/validation/test_inputs.jsonl`及对应`*_labels.jsonl`分离输入和金标；`pairs.jsonl`记录按查询定义的前后关系；`contrasts.jsonl`记录同前缀更新/维持分支；`sequences.jsonl`保存15条沿真实相容历史逐步增加信息的检查点链。为连续评估补入真实前缀检查点，所以384个检查点并不等于206对互相独立的问题。

### 评估实现与边界

`social_b_evaluation.py`提供原生请求构造和诊断评分，使用既有`social_lm_eval.tool_for`，评分兼容既有`raw_message`日志；不从普通正文解析JSON冒充工具调用。

- 独立模式只发送该检查点的公开上下文。
- 连续模式按同一实际历史严格递增，保留先前真实assistant消息与原生tool call。工具确认只说Recorded，不回传正确答案、分数或金标。前一次错误可以被后续真实证据纠正，后续金标始终不受模型此前输出影响。
- 指标：集合完全正确率、错误排除/额外保留的数量及有效答案上的比例、应维持时乱更新、应更新时未更新、先前错误是否持续或恢复。格式失败/截断计入检查点准确率的失败，基础设施失败单列；错误集合细分率同时报告有效查询数量，不能藏掉协议失败。先尝试与最终尝试应分别汇总，成功retry不抹掉先前失败。
- `evaluation_spec.json`保留每检查点路径1024 generated tokens、最多一次retry约定；请求构造器接受剩余token预算并检查上限。尚未接客户端执行循环或启动LM，因此真实请求的累计usage与retry执行仍需在运行阶段核验。
- 当前只有逐检查点诊断，不定义跨时advantage、额外重复惩罚或新RL奖励权重。

核验：384个金标全部通过现有原生schema；三份骨架交集为空；16个对照的共同前缀及对应更新/维持边、15条连续序列的时间递增与划分一致性通过；每个最终检查点的联合支持均与反转动作枚举顺序后相同。源文件哈希核对一致。41项测试通过，包括错误先答后改能恢复、前序金标不进入请求、两种更新错误分开记录、native-only解析与失败记账、骨架对轮序/重命名不敏感。未运行真实LM、未更新参数。

复现：

```bash
python -m training.b_sft.social_b_curriculum --out <new-directory> new/local_data/social_runs/b_dataset_random_ties_v5 new/local_data/social_runs/b_dataset_two_hidden_v1
python -m unittest training.b_sft.test_social_b_evaluation training.b_sft.test_social_b_two_hidden training.b_sft.test_social_b_dataset training.b_sft.test_social_b_oracle training.b_sft.test_social_b_random_window training.b_sft.test_shared_teacher training.b_sft.test_social_cases -q
```

## 24. B 冻结模型评估执行入口

新增 `run_social_b_eval.py`，沿用 `methods.vllm_client.OpenAICompatibleNegotiationClient.complete_with_tools` 的标准 `/chat/completions` 路径和服务器默认 chat template，原生 `SUBMIT_BELIEFS`、`tool_choice=auto`。不使用自定义模板、正文 JSON 回退或 prompt logprobs。旧客户端仅保留 role/content，会丢失历史原生工具调用；现改为保留完整 message 对象，使连续评估的 assistant.tool_calls 与 tool_call_id 回执实际送达服务。

一个端口一个线程，各端口并行取完整任务，同一连续历史始终由同一线程顺序执行。`--mode both` 分别运行独立点和连续历史，后者仅携带模型此前实际回答与 Recorded 回执，不传 gold。每个决策点最多两次请求，合计 1024 generated tokens；合法但错误不重试。格式失败带明确反馈重试，第一次失败完整保留。截断耗尽预算不重试。服务异常或 completion_tokens 缺失/越界时预算不可核验，记 infrastructure_failure，不盲重发；连续历史余下点记 blocked，进程结束返回 2。

保存 run_config（源码/数据哈希与配置）、jobs、每次 calls（完整请求、原始响应、usage、评分）、checkpoints（first/final）、transitions、blocked 和 summary。独立/连续与 first/final 分开统计，并按 family/split/phase 分组；类别统计单位为 pair 的后端点，可重复，具体 query 见 transitions。没有新增 reward、基线或参数更新。默认 temperature=0.7，真实模型协议稳定性仍须本次运行验证。本地测试使用模拟 HTTP 响应，不能代表模型表现。

## 25. B 原生评估 r1 下载审查：记账通过，题面接入有缺失

结果下载至 `new/local_data/social_runs/b_eval_native_r1/`。运行温度0.7、四端口、both/all。475个检查点（384独立，15条连续历史共91次判断）产生507次请求；475条checkpoint记录不等于475次成功生成。没有参数更新。审查脚本 `debug/audit_b_eval_native_r1.py`，核对输出 `audit.json`。

### 协议和准确率

|模式|首次格式合法|最终格式合法|最终截断|最终格式失败|基础设施失败|完整判断正确|
|---|---:|---:|---:|---:|---:|---:|
|独立|338/384|350/384|31|3|0|23/384（5.99%）|
|连续|87/91|87/91|1|0|3|18/88（20.45%，排除3个基础设施失败）|

独立首次另有15截断、31格式失败。31次retry中12恢复合法、16因剩余预算耗尽截断、3仍格式失败；连续唯一retry截断。全部507次请求有35次格式失败、32次截断、3次基础设施失败，失败尝试未被抹掉。格式失败中14次没有原生工具调用，另21次是回答的player/查询数量等schema不符。独立最终440个有效查询中427个保留三种偏好，13个给want/avoid；连续93个有效查询全部保留三种偏好。两模式都未输出任何单元素集合。多元素集合却给具体favored的查询分别371/440、44/93；这是违反任务favored_rule的答案错误，现有通用schema允许这种组合，未将其另算格式失败或重试。

按pair指定的那个query重算，独立形成0/77、维持0/85、更新0/18准确（有效提交分别71、78、16）；不能拿summary中所有query的均值替代此结果。无信息pair为5/26正确。连续历史中的更新pair为0/15，其中12有效、3基础设施失败。两模式题目分布不同、连续历史共享前缀，不可用5.99%与20.45%直接声称连续模式更好。15条连续历史中11条所有点最终格式合法；另3条最后一点上下文溢出、1条含截断。

### 已确认的接入问题（本轮助手责任）

新B请求保留了原生HTTP机制，但没有复用旧版可读题面和规则说明。实际只发送原始commitment bit vector、裸own_preferences数组和game字段，缺少向量各位表示哪些已承诺动作、目标需要全部required_actions、偏好数值映射与收益规则、承诺不可撤回及max_changes等关键解释。`social_lm_eval.py`旧SYSTEM中已存在这些规则与玩家归属说明，本轮新增SYSTEM漏掉了；复杂partner_model摘要不能替代基础游戏规则。不能据此将低分全部归因模型能力，也不应要求用户再盲跑整批。修复应沿用已有表示/规则，适配当前B上下文，不能照搬旧“learner事件非证据”的过时oracle语义。

样例 `004843c64f299b575497` 把 `[0,0]` 解读为采取action_0、把 `[1,0]` 解读为action_1，说明基本表示混淆已实际发生；它还把接受offer直接解释为喜欢goal。样例 `01c5cac15d2c1ba1a99b` 把player 0的REJECT归为player 1，声称排除到avoid却提交全三种+avoid，而oracle答案want/neutral+undetermined。前者表示缺说明，后者还含角色归属和推断/答案不一致；不能用逐题注入正确答案来修复。

连续请求每次重复全量静态规则和完整累计history，三个序列最后一点请求总上下文分别16858、16754、17339，超过服务器16384。对应checkpoint为 `cf2163f1db77a90774d8`、`ecd0e2ef9451f8dbf4dd`、`7d26960e9e995d4c296a`。这些是确定的HTTP400上下文容量失败，不是模型拒绝或GPU OOM。需无损整理重复信息或提供足够上下文预算；不能删证据或把这三条计为模型错误。

### 核对通过与下一步范围

记录的5个源码哈希、20个数据文件哈希均与本地一致。507次请求重评分的status/exact/逐query结果一致；21次jsonschema错误文本仅字典键渲染顺序不同，不影响判定。全部请求与本地重建输入完全一致，包括retry反馈、连续历史实际assistant/tool消息，未泄漏gold；验证了229次历史assistant消息出现。475条first/final与原始请求对应，所有有usage路径生成总额≤1024，最大1024。3次HTTP400没有usage且未重试。独立/连续的summary主要指标复算一致。

本轮只下载和审查，未改题面、未改oracle、未启动下一次评估。应先修复丢失的通用游戏表示/规则与连续上下文容量，保持原生tool和预算约定，再判断真实模型能力和B RL接入；不能宣布训练测试通过。

## 26. 可读题面与增量历史小测：35/35首次原生提交成功

用户运行后下载 `new/local_data/social_runs/b_eval_readable_smoke_r1/`。入口v2，prompt `social-b-readable-v2`，温度0.7。固定12个独立点覆盖不同类别及此前的表示/协议失败；另将此前3条溢出历史完整跑完，共23个连续检查点。该子集是针对已知缺陷选择的回归测试，不能代表总体数据分布或独立35条游戏。

本轮恢复复用了 `social_presentation.present` 和旧版 `social_lm_eval.SYSTEM/STAGE_INSTRUCTIONS` 的可读动作、玩家偏好归属和通用规则。只将旧版“learner动作非证据”替换为当前oracle的“所有post-setup动作自主产生”。保留当前partner_model，未改变oracle、答案或输出schema。连续模式首次完整题面、后续新增事件与当前状态，保留模型实际回答及原生tool回执，未删除历史证据。

|模式|首次原生格式合法|完整判断正确|逐query集合正确|
|---|---:|---:|---:|
|独立|12/12|1/12|2/17|
|连续|23/23|8/23|14/30|

35次请求全部首次成功，无retry、截断、格式失败或基础设施失败；3条连续序列完整结束。最大输入6887 tokens，最大生成792，均在预算内。47个有效query中，多元素集合/具体favored的违规组合为0；30个保留全部三种、7个neutral/avoid、7个单want、3个单avoid，说明模型已能按约定输出收缩集合，但不代表收缩正确。

核对同一子集的旧结果：独立首次9合法、2格式失败、1截断，完整判断0/12；连续20合法、3上下文失败，完整判断3/23。这一回归支持修复了已知请求与容量缺陷，但不能据35次成功宣布真实协议普遍稳定，也不能将准确率变化解释为严格因果实验（未固定seed和全部采样过滤参数，连续之前回答也发生改变）。

能力问题仍清楚存在。独立所选更新后端点0/2，连续更新0/3；连续三个更新转换中两个未收缩，一个从错误判断变成另一个错误判断，没有错误恢复。`004843c64f299b575497` 的题面已将player 0承诺显示为空，却仍称其承诺action_0，并把player 1的own_preferences归给player 0。`1730900c35e526599518` 已明确写Player 0拒绝，却推理成Player 1拒绝并猜avoid（gold neutral）。`42e85a653344d608faa6` 将含want/neutral/avoid的候选目录说成全部want。这些属于在明确输入下的读取/推断错误，不应逐题注入答案或新增reasoning正确性奖励。唯一独立完整答对的 `11957e408ee10a942090` 仍以“伙伴avoid所以自己不能want”等不成立的理由解释；答案正确不等于推理过程正确。

`debug/audit_b_readable_smoke.py` 生成同目录 `audit.json`：6个源码和20个数据文件哈希全部一致；35次输入重建、原始响应重评分、first/final、summary复算一致；所有连续消息的新增事件拼回后等于完整可读历史；当前承诺向量转action IDs核对无损，无gold注入。审查未更改任何任务/模型，也未启动追加评估。

结论：本次选定范围内，已知表示接入和上下文容量缺陷修复通过。判断能力弱本身不是继续阻止小规模RL的理由；下一步可明确B奖励与接入训练循环。当前运行器仍只评估，没有reward/优化器接入；多次采样能否产生足够的奖励差异尚未测定。数据更新标签仍偏neutral，不能把本小测当成完整训练有效性验证。

## 27. B-only RL准备：精确奖励、隔离数据与组内奖励检查

新增 `social_b_rl.py`，不改变oracle、可读prompt或原生SUBMIT_BELIEFS。任务reward版本 `social-b-exact-reward-v1`：每个query集合与favored都正确计1，否则0，同一检查点按query平均；合法答案范围0–1。格式失败-1，截断-1且不叠加格式惩罚，基础设施失败为null并屏蔽。不评价正文、不设置重复惩罚、不直接生成advantage。每次尝试独立评分；同题组仅使用首次尝试，因为retry带格式反馈后已不是同一个prompt，不能混入组内相对比较。

`b_rl_prepare_v1/`已导出226训练/56验证/102测试的requests与targets分离文件、manifest和reward_contract。分割骨架无交叉，不把gold放入模型请求。它是训练接入准备包，**不能直接交给现有RLVR入口启动优化**。现有`roll/pipeline/rlvr/rlvr_pipeline.py:get_encode_function`仅传messages给chat template，尚未转发工具schema；数学reward worker从解码正文取答案。这些必须适配原生工具协议和真实rollout token/logprob，不能用正文JSON回退、SFT或重新渲染的猜测token序列代替。

准备固定train子集12点（形成/维持/更新/无信息各3，覆盖7个骨架），不根据模型输出选题。同题默认8次独立采样，共96次首次请求，最多各一次retry且仍共享1024 token。沿用已验证HTTP客户端和checkpoint循环，一端口一worker；显式temperature=0.7、top_p=1、top_k=-1，每个task/sample固定hash seed。客户端新增可选参数，旧调用不传时保持原来行为。注意这明确了此前隐式的采样过滤设置，不声称与旧评估完整采样分布相同，也不保证跨GPU/版本逐token重现。

probe逐组记录reward分布、完整性、合法答案种类、正奖励样本数、所有reward差异与仅合法task reward差异；infra不填0，不删除全零组，不把不同query当作同题采样。所有请求、失败和retry保留。只有格式失败带来的差异不算B任务学习信号。先看此分布，再确定组内相对方法是否合适，不擅自改变reward以制造差异。

37项相关测试运行通过（1项原有skip），包含原生序列化、retry预算、语义reward、双query半分、截断/infra区别、无gold注入、显式seed与采样参数、retry不混组。现有smoke重新按新reward计算：独立12点为10个0、1个0.5、1个1；连续23点为10个0、5个0.5、8个1。这不是同题组内差异，不能据此选择GRPO。尚未运行96请求probe，也未更新参数；用户此前选择自己运行，保留此操作方式。

服务器同步新版social_b_rl.py、vllm_client.py及b_rl_prepare_v1后执行：

```bash
cd /raid/chenjiahao/mas
/raid/chenjiahao/conda_envs/mas/bin/python -u -m training.b_sft.social_b_rl probe \
  --data-dir new/local_data/social_runs/b_curriculum_eval_v1 \
  --prepared-dir new/local_data/social_runs/b_rl_prepare_v1 \
  --output-dir new/local_data/social_runs/b_rl_reward_probe_r1 \
  --samples 8 --temperature 0.7 --seed 20260912 --model social-base \
  --base-urls http://127.0.0.1:8000/v1 http://127.0.0.1:8001/v1 \
              http://127.0.0.1:8002/v1 http://127.0.0.1:8003/v1
```

## 28. B奖励分布probe：存在组内信号，但形成/更新查询尚无成功样本

用户运行后下载 `new/local_data/social_runs/b_rl_reward_probe_r1/`。train固定12点×8首次采样，共96条路径、99次请求；temperature0.7，显式top_p1/top_k-1，记录按task/sample生成的seed。首次93合法、3格式失败；3次retry恢复2次，1次截断。无基础设施失败，所有路径生成总token≤1024。独立请求最大输入3942、单次输出799。协议仍有少量错误：player/goal组合错误，以及把undetermined放进possible_preferences。

首次奖励分布：59个0、14个0.5、20个1、3个-1。12组全部完整，7组有正奖励，6组有合法答案间的task reward差异；另5组全部0、1组恒定0.5。不能把7组有正分等同7组可产生组内相对advantage，也不能把组内差异解释成生成前缀B/P的分支信用；这里是同题完整B答案的重复采样。

逐query拆开后，比总体指标更关键：

|该点所属类别的指定query|首次答对/采样数|有效提交|有正确/错误差异的组|
|---|---:|---:|---:|
|形成|0/24|23|0/3|
|维持|7/24|24|2/3|
|更新|0/24|22|0/3|
|无信息|22/24|24|1/3|

形成组 `0f90d94184421060a251` 的0.5都来自另一个仍保留全部偏好的query；真正形成的P1/G3一直答错。更新组 `7d26960e9e995d4c296a` 唯一首次0.5来自P2/G2，真正更新的P1/G3仍答错。因此形成/更新组有task reward variation，不等于该能力出现了正例。多query平均reward按既定定义计算正确，但单凭总reward会遮蔽能力缺口；本轮未擅改奖励或去掉其他query。

Reasoning抽查仍有“没有直接披露，所以无法排除”的倾向，或把接受/拒绝直接等同want/avoid。维持组 `0db712b7eaaf1d880802` sample1答案正确，却声称公开目录只有want/neutral（实际含avoid）；说明精确答案奖励仍可能奖励错误理由，不能直接声称监督了正确推理过程。不新增人工reasoning评分。

`debug/audit_b_reward_probe.py` 输出 `audit.json`：源码hash、tasks hash、固定选择、96个唯一task/sample、seed、99次原始响应重评分和reward、first/retry预算、输入重建无gold注入、summary复算均通过。格式失败详情仅按语义status核对，不比较jsonschema字典键显示顺序。额外逐query分析未覆盖或修改原始summary。

结论：可继续接入小规模优化，已有部分可用task reward差异；但当前数据/采样不能保证形成、更新获得直接正向学习信号。八次未成功不代表真实成功概率为零。首轮训练应把逐query类别指标作为必要观察项，不能以总奖励上涨宣布三类能力均改善，也不要静默过滤掉全零形成/更新题。是否补充更容易、仍需历史推断的形成/更新训练点，应作为数据课程设计讨论；不因本probe直接加密采样、改oracle或把正确答案塞入prompt。本轮仅下载审查，未运行额外生成或参数更新。

## 29. 首轮GRPO参数训练入口（尚未执行GPU模型更新）

实现接到现有ROLL GRPO，不复用probe日志做离线更新。`social_b_grpo.py`使用实际模型tokenizer原生template并传tools；训练输入messages/tools与ground_truth隔离。服务器CPU已对384题验证模板token逐个一致、原生Hermes parser对gold回环成功、普通正文函数调用被拒绝，最大prompt3942。训练数据保持226/56/102，独立B完整历史、所有未知query，原oracle与reward不变。

环境核对发现原mas是torch2.6.0+cu118、transformers4.57.3、vLLM0.8.5.post1+cu118、DeepSpeed0.16.3，driver470；仓库内置vLLM训练wrapper仅支持0.8.4/0.7.3，不能直接用于此服务版本。未降级或替换现有mas。新`.venv-b-grpo`使用system-site-packages继承已工作的torch/vLLM，隔离补充ROLL依赖：Ray2.46、tensordict0.7.2、hydra1.3.2、dacite1.9.2、codetiming1.4、TRL0.9.6（仅原有value-head帮助类依赖，不是SFT）、ninja1.11.1.4。TRL带入numpy1.26.4；基础环境的OpenCV/CuPy声明依赖numpy2，与隔离环境不一致，本B文本训练不使用它们，原mas不受影响。

首轮rollout采用ROLL已有HF推理strategy，增加其对现有请求队列/回调的串行支持，直接保留model.generate产生的token IDs。工具调用仍由vLLM Hermes parser识别原生工具标记，不从正文JSON恢复。HF的top_k=0与vLLM的top_k=-1都表示关闭top-k过滤；不宣称两种引擎同seed逐token一致。HF预计较慢，本轮先验证少量参数更新，不升级当前vLLM。

框架适配：RLVR编码转发tools且不重复加special tokens；工具题超长直接报错，不静默丢样本。生成停止符在有tools时只保留EOS，避免把原生工具标记当EOS提前结束。`functionals`仅用于类型标注的AgenticConfig改为TYPE_CHECKING，避免文本RLVR导入所有游戏和无关绘图库。`social_b_reward_worker`对真实response token解码、原生解析并调用已验证reward；截断单计-1，不叠加格式惩罚；异常终止整个请求/训练，不把基础设施问题伪造成0分。逐次保存token IDs、原文、原生调用、query评分、category查询及global_step。

配置`examples/social_b/grpo.yaml`：10个rollout/update步骤，每步4题×8回答=32样本；2张训练卡每卡microbatch1、accumulation16，全局32样本一次优化。学习率1e-6，PPO clip0.2，KL loss0.01，SFT/entropy额外loss为0，组内均值/标准差归一化沿用ROLL。关闭difficulty mask、query过滤和max_len mask，保留全零组；全零组没有任务advantage，但KL项仍可能作用。prompt4096+生成1024，训练不retry（满足最多一次上限），不把格式反馈后的采样混入同题组。验证温度仍0.7，定期验证与保存checkpoint。10步只验证链路，不声称足够判断方法有效。

实际现有端口8000–8003分别占物理GPU4–7，而不是0–3。启动脚本默认CUDA_VISIBLE_DEVICES/ROLL_ASSIGNED_CUDA_DEVICES=4,5,6,7，ROLL内部逻辑0/1训练、2/3采样；reference与训练卡分时使用，DeepSpeed ZeRO3+CPU optimizer offload。`stop_b_eval_servers.py`只在PID、owner、命令、model name、port和CUDA_VISIBLE_DEVICES都匹配记录时发SIGTERM，不误杀其他任务。助手未执行停止命令，也未执行训练；用户自己运行。launcher另检查选中GPU空闲和输出目录新建，并保存源文件hash、依赖版本、reward及数据manifest。

CPU预检处理了真实环境问题：系统默认nvcc10.1与torch11.8不匹配，显式使用现有`/home/chenjiahao/cuda-11.8`；tensordict需使用现有conda的新版libstdc++，显式LD_LIBRARY_PATH指向mas/lib；CPUAdam编译工具通过隔离环境PATH中的ninja提供。CPUAdam已成功编译并对单个CPU测试标量更新（不是模型参数训练）。13项本地相关测试通过，包括原生schema编码、实际生成token保留、奖励与retry隔离；服务器导入及typed配置解析通过。GPU初始化、真实GRPO backward、权重同步和checkpoint回读尚需首轮实际运行验证，不得把CPU检查当成已经训练成功。

服务器入口：`bash training/b_sft/run_b_grpo.sh`。运行前用户执行`.venv-b-grpo/bin/python training/b_sft/stop_b_eval_servers.py`释放自己的4个评估服务。结果根目录`outputs/social_b_grpo_r1`；旧输出不覆盖。基础mas的推理环境及原结果保留。

首次用户启动在 Ray head 初始化失败：launcher 指定 GCS 16379，与 Ray 默认 worker 端口范围10002–19999重叠；这不是 GPU 或生成后端错误。已将本地默认端口改为26379，支持 SOCIAL_GRPO_RAY_PORT 覆盖，并在创建输出目录前校验范围及尝试绑定。bash语法检查通过；未启动远程训练。重跑须保留并移走此次失败输出目录，避免覆盖；不执行全局 ray stop。


## 30. GRPO 回到原 mas/vLLM 路径与 NCCL 二进制冲突（2026-09-12）

用户要求停止新环境/HF采样路线，采用GRPO + vLLM采样 + DeepSpeed更新。使用原`/raid/chenjiahao/conda_envs/mas/bin/python`，torch2.6.0+cu118、vLLM0.8.5.post1+cu118、Ray2.58.0、DeepSpeed0.16.3、transformers4.57.3保持原版本。补充缺少的ROLL依赖时使用固定版本和`--no-deps`，不调整NumPy或CUDA包。移除此前增加的HF生成队列；reference仍使用原HF前向路径。GRPO无需TRL value head，缺少TRL时不再因通用offload模块的顶层导入而失败。

用户提供的CUDA错误发生在HF actor初始化的`dist.all_reduce(torch.zeros(1).cuda())`，不是生成本身。服务器同时安装nvidia-nccl-cu11和nvidia-nccl-cu12 2.21.5；二者RECORD指向同一个`nvidia/nccl/lib/libnccl.so.2`，但哈希不同。实际文件SHA256（URL-safe base64）为`eN8vMfbbgULsVGoeWjHLBm94ktEtL2ZbRI-AaaCO-Ac`，匹配cu12；cu11应为`Tejvap0n5F4OPQZ8gf3ApxA8sxjjRVfaJZSaQjCpyq8`。这解释了torch版本虽为cu118，NCCL通信仍报CUDA driver insufficient。此前单卡vLLM推理成功不能证明这条多卡通信路径正常。

修复不覆盖共享site-packages：下载原版本cu11 wheel，按已知哈希校验并只提取`new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2`，launcher及Ray actor配置显式LD_PRELOAD此文件。`check_b_grpo_cuda.py`核对进程实际加载路径后，在物理GPU4–7做四rank标量all_reduce；全部通过，诊断进程退出，未加载模型或训练。原cu12共享文件保持原样。

vLLM适配复用现有0.8.4 V0 wrapper，增加仅针对0.8.5/0.8.5.post1的入口，明确拒绝此入口下的V1；服务器实际EngineArgs、processed request签名、worker wake_up、Ray executor及weight RPC导入检查通过。VllmStrategy改用仓库已有RecvBucketManager，避免无关Megatron依赖。actor_infer为vllm、TP1、两张独立采样卡、max_model_len5120、eager、关闭prefix cache、memory utilization0.65。温度0.7、top_p1、top_k=-1、8样本、1024生成预算不变；原生工具、训练题面、reward及GRPO数学不变。

输出改为`outputs/social_b_grpo_vllm_r1`，不覆盖之前失败目录；保存driver.log、运行解释器、私有NCCL哈希及适配源文件hash。启动前检查指定Ray端口26379及GPU空闲；显式RAY_ADDRESS/MULTI_TENANT避免接入其他地址的集群，不执行全局ray stop。用户仍自行启动训练。13项本地测试通过，生成token回调测试改为vLLM路径。完整模型backward、跨进程权重同步及训练checkpoint尚未运行，不把通信/导入检查当作训练成功。

额外单卡vLLM冒烟使用同一V0 wrapper、原模型和训练题面，在GPU6生成真实原生SUBMIT_BELIEFS，记录实际token IDs及现有reward；并通过WorkerHelper RPC暂改一个q_norm参数后立即恢复、执行sleep/wake后再次生成。首轮这些步骤通过，但未显式销毁NCCL组导致解释器退出segfault；保留`vllm_smoke_first.log/json`，已改用vLLM自带`cleanup_dist_env_and_memory()`后复测。此诊断无梯度、优化器或checkpoint写入，不属于模型训练。

显式销毁NCCL后仍在Py_FinalizeEx出现`CUDAPluggableAllocator::raw_delete: Trying to free a pointer not allocated here`；第二次记录保留为`vllm_smoke_cleanup.log/json`。最终配置采用独占GPU常驻模型，关闭可选enable_sleep_mode；现有wrapper由强制开启改为允许显式配置，WorkerHelper在关闭时保留模型与KV cache，不进入自定义分配器。默认开启行为对其他配置不变。预检要求采样卡与训练/reference卡不重叠，避免把常驻模式误用于共享卡。新增常驻offload回归检查后14项本地测试通过。

最终关闭sleep mode的真实模型复测完整通过，进程exit_code=0；同一训练点原生调用合法，reward1.0，q_norm参数RPC写入并恢复成功，常驻offload/load hooks后可继续生成。这里只证明单次协议与接口工作，不据此宣称模型协议稳定或GRPO有效。最新typed配置检查通过，原mas依赖版本保持预期。尚未运行训练、启动Ray训练集群或测试跨进程模型权重同步；训练由用户执行最新入口。诊断日志和前两次退出失败均保留并下载。

用户下一次启动在Ray日志监听器构造时报`gcs_publisher`未知参数：Ray2.58实际接口为gcs_client，二者publish_logs(data)一致。LogMonitor子类按真实父类签名转发；原环境CPU测试实际创建worker日志、发现文件、读取并发布数据通过，未启动Ray或训练。该测试加入启动预检。另修复失败driver退出后Ray head仍占用显式端口时的重跑检查（确认该地址ray status成功才复用）；MULTI_TENANT模式禁止监听器退出钩子的host-wide ray stop --force，避免影响别的集群。训练输出仍不覆盖，保留失败目录后重跑。

用户后续运行在actor_train构造scheduler时报`get_linear_schedule_with_warmup() got an unexpected keyword argument min_lr`。根因是DeepSpeed strategy对所有HF scheduler硬编码传入min_lr=0；当前TrainingArguments默认linear不支持此参数。提取实际训练复用的create_train_scheduler，仅两种min-lr cosine调度器传入该默认值，linear等使用自身参数，不切换学习率策略。原服务器CPU真实scheduler回归（linear曲线、普通cosine与min-lr cosine）2项通过。启动预检现在调用RLVRConfig.set_max_steps并按DP数量计算实际optimizer steps，在CPU标量优化器上使用同一构造函数执行完整调度，无需加载模型或初始化分布式。当前10个optimizer steps；保留既有warmup配置（warmup_steps=0会回退warmup_ratio=0.03，因此实际warmup为1步，并非0步），本次不偷偷改变该参数。之前仅检查配置类型不够，不能用这项修复宣称完整训练链路已经通过。

初始化耗时只读排查：失败driver.log中17:59:29 Ray已就绪，18:05:08完成worker/scheduler准备（5分39秒），18:08:46两采样worker就绪（再3分38秒），18:09:58 reference就绪（再1分12秒），18:12:07训练scheduler报错（再2分9秒）。driver可见合计12分38秒；launcher预检不在driver.log中，不能据此精确还原用户报告的20多分钟总墙钟时间。Cluster创建中有同步ray.get，多个角色按次序创建，pipeline显式先infer、再reference/reward、再train初始化。checkpoint分片加载约15–18秒，cpu_adam缓存命中ninja no work，加载约7秒，不是20分钟主因。分布式初始化反复出现hostname lookup err=-3；只读实测服务器192.168.50.57的NI_NAMEREQD反向查询耗时10.009秒后报Temporary failure in name resolution，证实存在DNS等待，但尚未量化全部累计影响。本轮未改DNS、并行初始化或启动训练。

对照仓库已有GRPO/ROLL入口后修复generate_opt_level错配：examples/qwen2.5-vl-7B-math/rlvr_math_zero3.yaml的level0对应RLVRMathVLMPipeline/GenerateScheduler；当前B入口RLVRPipeline在训练及验证均使用DynamicSamplingScheduler，要求level>0，默认为1。仓库既有vLLM示例（qwen2.5-7B等）也有SGLang示例（qwen3-30BA3B）；不能仅按后端名称跨pipeline照抄配置。当前B配置改为1并显式is_num_return_sequences_expand=false，保留每题单请求包含训练8条/验证1条的行为；不改GRPO归一化、reward、原生工具或模型。原服务器CPU调用真实DynamicSamplingScheduler.expand_requests验证训练/验证两路，另测level0提前拒绝，2项通过；同样检查已加入启动预检。没有启动训练。

## 31. 首次 10-step B GRPO 结果审查（2026-09-12）

用户自行完成 `outputs/social_b_grpo_vllm_r1` 后，下载日志、原生请求及 checkpoint 元数据到 `new/local_data/social_runs/b_grpo_vllm_r1/`；大体积权重和优化器保留服务器，使用 CPU 只读检查。审查脚本 `training/b_sft/audit_social_b_grpo_run.py` 生成 `audit.json` 和逐请求 `audited_calls.jsonl`；另有服务器实测的 `native_token_audit.json`、`parameter_audit.json`、`checkpoint_audit.json`。本轮没有启动训练或最终模型评估，没有修改训练接口、prompt、reward 或采样配置。

### 训练实际执行与协议

日志完成 step 0–9，10 次 optimizer 调用，每步 4 题 × 8 条 = 32 条，共 320 条、40 个不同 checkpoint。既有 scheduler 的第一步学习率为 0，因此是 9 次非零学习率更新，不能把日志中 scheduler 更新后的 actor/lr 当作该步实际使用值。抽查最终 worker-local HF 权重的 18 个参数张量切片，13 个发生变化，全部检查值有限，最大绝对变化 7.62939453125e-6；证明实际更新过参数，不代表检查了全模型数值或验证了恢复训练。

训练 317/320 原生输出合法（99.06%），2 次格式失败、1 次截断，无基础设施失败和 retry。训练全题 exact 45/320，平均奖励 0.2046875。训练和两次验证共 432 次请求，重新解码 token IDs、执行现有 Hermes 原生解析，均与记录一致；本地复算 reward 和 score 语义字段一致，预算及 split 检查通过，记录源文件哈希与本地一致。3 条 schema 错误的诊断文字因本地校验器报错选择/顺序不同而不同，失败类型与计分一致，单独保留。没有发生早期普通文本伪装工具调用的大规模退化。

40 个组全部各 8 条；22 组奖励有差异，21 组在合法输出之间仍有差异，15 组全零。ROLL 的 mixed_groups_ratio 定义为既非全 0 又非全 1，常量 0.5 组也算 mixed，不能直接当作非零组内 advantage 比例；按源码定义逐步复算一致。

### 验证与 B 能力边界

| 时点 | 全题 exact | 平均奖励 | 合法输出 |
| --- | --- | --- | --- |
| 初始模型 | 16/56（28.57%） | 0.33036 | 55/56 |
| 第 5 次 optimizer 调用后 | 21/56（37.50%） | 0.37500 | 54/56 |

验证发生在 global step 0 和 5 的训练前；没有最终 step 9 后验证，也没有 test split 评估。两次是同一批 56 题，每题温度 0.7 单次采样；9 题错转对、4 题对转错，不能据此宣称稳定提升。

仅看标注的目标 query：训练 formation 8/88、maintain 5/64、update 0/16、uninformative 5/8；验证 formation 2/14→2/14、maintain 1/13→3/13、update 0/1→0/1、uninformative 3/4→4/4。类别指标只统计目标 query，不能与全题 exact 混用；训练 update 的 16 次是 2 个点各采样 8 次，并非 16 个独立更新局面。没有证据表明已经学会 belief 更新。

定性看仍有罗列三类偏好、以没有直接披露为由保留全集的回答，也有角色、行动与目标关系错误。更新验证点 a5bacdf5029f9c1399cf 两次均未从历史排除不符的偏好，而保留全部三种（gold 为 neutral）。自然语言解释流畅不等于完成逆推。

### 最终 checkpoint 保存不完整

汇总目录 checkpoints/checkpoint-9 中第一权重分片只有 629,616,640 字节（源文件应为 4,967,266,905），rank-1 优化器只有 726,470,656 字节（源应为 24,134,814,276），均无法读取 ZIP 目录，且缺少其他必要文件。检查时没有仍在运行的训练/复制进程，不能把它当作尚在正常复制。

actor_train-0/checkpoint-9 保留完整两片 HF 权重及配置/index/tokenizer、rank-0 状态；actor_train-1/checkpoint-9 保留 rank-1 状态。源权重可以通过 torch.load(weights_only=True, mmap=True) 实际读取，两 rank 状态 ZIP 目录可读；尚未做全量 CRC 或训练恢复实测。此前 checkpoint-4 汇总文件齐全。

代码默认异步 submit checkpoint upload；最终日志只有 upload 等待，没有各 actor 上传完成记录，但 driver 已报告 pipeline complete。证据与最后异步复制未等完、worker 退出的原因一致；尚未通过修复后复跑验证该因果。训练更新已执行，最终 checkpoint 汇总保存环节未通过，不能称完整交付链路通过。下一步应从保留源恢复最终 checkpoint、修正结束时等待保存，再由用户启动最终模型评估；不需要为恢复现有权重重新训练。

## 32. 六卡常驻 B GRPO 正式入口与保存修复（2026-09-12）

用户要求停止候选性能试验，确定最终实现，并以 paper-ready B 训练为目标；训练仍由用户启动。采用原 mas Python、ROLL/DeepSpeed/vLLM，不安装 Megatron、不改 B oracle、prompt、原生工具、reward 或数据 split。原文附录 B 明确使用 ROLL/vLLM/Megatron、8 H100；本仓库 multi_games 对应配置为 TP4/DP2、分布式优化器。服务器实查缺少 Megatron、Transformer Engine、Apex。六卡角色常驻的决策是沿用现有可运行环境的工程选择，没有做候选方案吞吐比较，不能宣称已实测最快。

配置 examples/social_b/grpo.yaml：物理0,1,4,5为训练，6为vLLM，7为reference；进程内逻辑映射0–3/4/5。训练DP4/TP1、ZeRO2、GPU FusedAdam；BF16、gradient checkpointing、micro1、gradient accumulation8，保持每步4题×8条=32条、PPO epoch1。新增 keep_states_on_device（默认false）在HF及DeepSpeed策略load/offload入口阻止搬运，覆盖初始化、模型同步前、每次optimizer step后及reference前向的既有调用。配置预检要求角色不重叠、ZeRO2没有CPU offload、常驻开启。通信桶降至5000万元素，留出40GB卡的临时内存余量；未实测本配置GPU峰值或吞吐。

启动器默认新Ray端口26380、新输出outputs/social_b_grpo_b_r2，拒绝覆盖已有输出；不停止旧集群或其他GPU任务。单机通信显式使用127.0.0.1及lo接口，涵盖ROLL worker rendezvous与vLLM分布式init URL，但保留Ray用于实际节点识别的IP。该选择绕开之前实测耗时10秒的LAN IP反向DNS查询，不修改系统hosts/DNS；未重新计时模型初始化。worker设备信息查询改为批量ray.get。去掉每次启动重复四卡NCCL冒烟，仍检查已验证cu11库哈希、配置和GPU占用。保留实际启动UTC、代码及数据文件哈希。

训练预算先定60步，240次题目抽取、1920条输出，约覆盖现有226训练点一遍后少量重复；不是2000个独立题目。temperature0.7、1024tokens、group8、lr1e-6、linear、KL0.01、clip0.2不变；warmup_steps显式1，warmup_ratio0，第一步实际lr0（59次非零LR调用）。初始验证及最后一次更新后的验证，关闭中途验证和周期checkpoint。最后保存不依赖步数整除，先保存再同步最终权重并验证，避免验证失败丢失训练成果；final_validation.json记录实际optimizer步数。原生请求记录增加evaluation_phase和evaluated_optimizer_steps，避免用日志位置猜测验证时点。没有使用test split选超参或宣称最终测试完成。

保存采用同步上传、异常向driver传播；同文件系统对已完成的文件建立硬链接后原子替换，跨文件系统回退先复制临时文件再替换，失败保留源文件。全部actor完成且pipeline状态发布后，检查HF索引分片、tokenizer、pipeline RNG、所有rank优化器和对应模型状态，校验torch文件ZIP目录，最后写COMPLETE.json。该标记是文件结构校验，不等价于实测恢复训练。默认行为对其他配置保持不变。

旧r1已在服务器恢复到 outputs/social_b_grpo_vllm_r1/checkpoints/checkpoint-9-recovered，使用worker-local源文件及原pipeline元数据，通过当时的必需文件和ZIP目录检查；未覆盖损坏目录或删除源文件，也未重新训练。repair_social_b_checkpoint.py提供相同恢复操作，新版检查额外要求tokenizer和pipeline RNG文件。

验证：本地原生适配/奖励/评估11项通过；服务器原环境在临时副本执行常驻策略、checkpoint失败传播及截断、scheduler、动态请求展开10项CPU测试通过；完整typed配置、真实linear scheduler与GRPO组归一化预检通过。FusedAdam现有扩展已在原工具链编译并导入（约103秒，一次性缓存），未运行GPU kernel或模型训练。临时检查最初清空CUDA可见性触发Triton缺少driver，改为保留驱动可见；补齐临时副本的benac_p搜索路径和正式VLLM_USE_V1/PATH后通过，未改环境包。没有做六卡模型性能试验。

当前只准备好这一轮正式B训练的实现和可审查记录，不能将其写成已完成paper-ready能力验证。现有数据更新类别的独立来源少、验证目标只有1个，这些研究覆盖限制仍在；正式结果需检查目标query、泛化和完整形成/维持/更新链，不能只报告全题均值。现有数据不在本轮静默扩充或重标。

## 33. 六卡 B r2 运行中进度快照（2026-09-12）

用户要求只读查看时间和训练效果。快照下载至 new/local_data/social_runs/b_grpo_b_r2_progress/，对应完成step0–13、step14正在采样。未更改或中断训练。launcher UTC05:49:52，driver日志使用UTC-4；driver首时间01:50:34，step0开始02:04:16，初始化含启动前检查14分24秒，driver可见13分42秒。前10步结束03:01:35，从启动约71分43秒；该总时间与旧r1的147分钟不能直接当纯计算加速比，验证/保存次数不同。

去掉含初始验证的step0，step1–13实际墙钟平均280.8秒。主要阶段均值：采样139.75秒、训练91.13秒、reference18.17秒、旧策略log-prob13.73秒、权重同步14.92秒；旧r1对应142.55、254.52、118.54、50.35、42.48秒。常规阶段合计约608秒→278秒，约2.2倍加速，采样成为最大开销；初始化虽缩短仍不理想。按当前速度完成剩余46步需约3小时35分钟，再加最终验证及尚未实测的新保存时间，粗估还需3.5–4小时，非保证。

已完成448训练调用444合法（99.11%）、2格式失败、2截断，exact62/448（13.84%）、平均reward0.194196；56组中28组合法输出间存在奖励差异。目标query formation7/120、maintain9/112、update0/16（只有2个独立更新点）、uninformative4/16。梯度和KL记录有限、每步1次optimizer调用，无已发现训练崩溃。不同step题目不同，不能将奖励波动当作能力学习曲线。

本次唯一验证是训练前24/56（42.86%）、55/56合法，平均reward0.473214；不是训练后提升，不能拿它与旧r1的16/56作学习增益比较。当前尚无训练后的独立验证，不能认定泛化改善或B更新能力学会。保持原定最终评估，不插入额外GPU任务。本地逐条复算已下载completion的reward，结果见progress_summary.json；尚未对本次token重新运行服务器Hermes解析，不冒称已完成最终审计。

## B v4 机制修订：累计证据权重、非确定 favored 与观察者私有偏好

用户指出：多元素集合强制 `favored=undetermined` 使 favored 冗余，偏离“仍有多个可能，但证据更支持其中一个”的研究目标。用户明确选择保留证据形成的权重并用于后续规划。本节取代前述 v2/v3 的 singleton-only favored 和每次重规划对剩余世界重新均匀赋权规则；旧章节、冻结数据和训练快照作为旧语义记录保留，不能当作新 B 目标的有效性证明。

### 新机制及实际修改

- `social_b_oracle.py` 升为 `social-b-bounded-oracle-v4`。初始独立公开目录的联合组合等权。每个自主行动先最大化自身窗口期望收益，再在自身同值动作中最大化其他玩家期望总收益，最后才在剩余动作间均匀随机。历史行动的似然是最终集合中该动作的执行概率；不能跳过两层收益比较，也不读取随机 seed。
- 公共联合权重逐事件乘似然并归一化，实际重规划保留累计权重。`RandomTieWindow` 的根部、信息集条件权重、根动作价值和条件偏离检查全部使用这些权重。概率为零的候选排除且不恢复；setup/intervention 不改变权重。循环、预算失败、数值下溢或全候选不相容仍失败，不伪造标签。
- `possible_preferences` 是正支持集合；`favored` 是唯一最高边缘支持者，即使集合含多个元素也可以有具体 favored。最高支持在数值容差 1e-9 内并列才 undetermined。这是声明机制下的后验，不宣称对任意 LM 伙伴已校准。LM 不输出概率、计数、utility 或搜索树。
- 教师单独保存 `preference_weights` 和 `joint_belief`，不把它们注入 B 题面。`joint_belief(observer=..., own=...)` 保留原联合候选及其权重，可供后续 P 明确信息输入使用；没有把边缘集合重新做笛卡尔积，也没有擅自扩展 `SUBMIT_BELIEFS`。因此直接监督联合相关性的接口问题仍保留，不能声称已训练完整联合 B。
- 公开目录现在只要求包含观察者真实偏好，不再要求只有该行。所有历史行动者使用其当时自己的私有行和公共加权信息；观察者的私有行仅在其查询处条件化。数据挖掘、配对验证和合并导出均相应修正，并排除与指定观察者私有行不相容的历史分支。
- 随机生成默认混合：3/4 玩家、不同 goal 数、合法 setup 后不同 commitment 数，以及全局一项、同一玩家两项、两个玩家各一项隐藏偏好。任意玩家包括观察者都可拥有隐藏项；观察者自己的项作为已知控制，不要求它推断自己。游戏/目录原生合法性失败如实记录，不通过改规则或改标签补救。报告筛选前后覆盖，随机生成不等于筛选后比例已均衡。

### 更新、题面与版本边界

形成表示从三元素且无 favored 的判断得到集合缩小或唯一倾向；已经形成非平凡判断后，集合或 favored 再变化记更新。集合和 favored 都不变但权重变化单列 `strength_change`，是教师审计事件，不冒充模型已被监督输出概率。连续评估的应更新/漏更新同时检查集合与 favored，不再只看集合。

更新候选先通过最后行动充分性检查，再按来源筛选，避免先取满早期简单题后才删光更新。该检查比较实际 LM 输出目标，不因为未监督的小数权重不同就声称必须读历史。它仍是教师侧的限定诊断，并非新增 LM 基线或通用的历史必要性证明。

`social_b_evaluation.py` 使用新 favored 题面；明确公开目录与观察者私有偏好的边界。旧 v2/v3 冻结题可按原规则只读评估，新训练准备和 GRPO 导出则拒绝非 v4 题，不能直接给旧轨迹换 gold。奖励仍是每项集合和 favored 同时正确得 1、多项平均，未添加概率奖励或自然语言评分。未上传代码、未启动/停止远程训练，未调整 MENU、self-play 或训练预算。

### 验证与开发数据

新增 `test_social_b_weighted.py`：原生 REJECT 例在 want/avoid 两种候选下分别具有 1 和 1/2 的似然，观察后仍保留两种候选但 favored=want、权重 2:1；核验累计似然、后续加权价值、私有观察者信息、失败原子性、favored 更新评分和三种隐藏布局。更新旧测试中已过时的固定随机种子及分类预期，不改变原生游戏规则。

本轮开发数据位于 `new/local_data/social_runs/b_weighted_v4_pilot/` 与 `b_weighted_v4_reviewed/`。后者复用同一 v4 机制下的首批候选并扩展随机来源，不复用 v3 gold；所有数据保持 `training_ready=false`，未替换现有 split。独立审计入口 `debug/audit_social_b_weighted.py` 使用精确分数累计行动似然，检查正反动作枚举重放、边缘 gold、原生工具评分及题面分离，并将重置为均匀权重的对照严格限于教师诊断。

最终本地验证：98项测试，97通过、1跳过。开发审计的165个检查点全部通过，累计971次历史事件后验检查，正反动作枚举下支持、权重和favored一致；其中27个检查点是多元素集合且有具体favored。源文件hash核对一致，详细结果见 `b_weighted_v4_reviewed/weighted_audit.json` 和 `weighted_examples.json`。

60个随机seed加4个手工来源，54个来源完成候选挖掘，筛选后26个来源、165题、93对：形成25、维持25、历史依赖更新9、无信息13、仅强度变化13、已知控制8。筛选后覆盖3/4玩家（21/5个来源）、1/2隐藏项（13/13）、一个/两个隐藏玩家（20/6）、观察者有隐藏项5个来源。这里“来源”含相关变体，不是独立骨架数或自然频率分布。更新9对的最终favored为neutral 8、want 1，仍缺avoid及集合不变的倾向反转的充分原生样本，不能宣布更新覆盖已完成。22个更新候选因最后动作足够回答被排除，1个历史依赖检查未解决被排除。

162条抽样续局完成，48条失败明确保留（40节点预算、8循环），没有把失败重置成全集或输出标签。已验证的当前检查点不保证其任意未来滚动续局都可求解。40个非均匀根部的教师重置权重诊断中，未找到最优动作集合改变，另有1个对照求解循环；不能据此声称这批数据已经检验了“权重变化必须改变行动”。另一个原生终局OFFER单元例明确比较给定等权与0.4/0.4/0.2两种信息条件：自身收益均为0，通过第二层他人期望收益比较使可选集合由ACCEPT/REJECT变为仅ACCEPT。该例验证加权决策实现，不冒充某段setup产生了这些后验，也不作为已通过筛选的自然历史见证。

## 34. 六卡 B r2 最终结果审查（2026-09-12）

用户训练结束后要求下载检查。本地完整小文件结果位于 new/local_data/social_runs/b_grpo_b_r2_final/，含driver日志、1920训练及112验证调用、manifest、final_validation.json、checkpoint完成清单与pipeline状态；大体积模型和优化器未下载，服务器CPU只读核查。没有启动新评估、更新参数或修改训练目标。

60步全部完成，launcher UTC05:49:52到driver UTC10:57:43，总5小时7分51秒（driver日志UTC-4的01:49:52→06:57:43）。主要累计耗时：训练采样132.62分钟、更新88.16分钟、reference18.34分钟、旧策略log-prob14.20分钟、权重同步15.01分钟、初始验证9.44分钟、最终验证9.25分钟、最终保存3.27分钟。初始化约14分钟。不能用这些总耗时承诺其他数据长度或配置的吞吐。

训练1920条：1884合法、6格式失败、30截断，合法率98.125%；全题557/1920，平均reward0.333594。每10步平均reward为0.1703、0.2922、0.3656、0.3922、0.4156、0.3656；各段题目不同，不能直接当固定测试学习曲线。目标query累计形成28/384、维持41/392、更新0/72（9个独立目标检查点）、无区分力116/152；未得到更新目标的正确训练样本，不能用另一个query的半分声称更新学会。

固定同一批56个validation检查点，初始和最终各一次温度0.7采样，最终标记evaluated_optimizer_steps=60。全题exact24/56（42.86%）→21/56（37.50%）；平均reward0.473214→0.428571；集合query正确32/68→33/68；合法输出55/56→56/56。配对7题错转对、10题对转错、14题始终正确、25题始终错误。一次训练种子和单次采样不足以确认统计意义上的退化，但本轮没有测到验证提升；没有test split或连续序列的训练后评估。

按指定目标query、只看集合是否正确：形成5/14→3/14；维持2/13→1/13；更新0/1→0/1；无区分力3/4→4/4。按gold集合大小统计所有68项：单元素0/7→1/7、双元素11/29→4/29、三元素21/32→28/32。输出全集的数量38→54（固定68查询；初始一次截断导致有效原生答案仅66项，最终68项全部有效）。因此改善主要表现为保留全集的正确率提高，双元素支持识别反而变差。不能将集合层面的表现当作favored相对可信度学习：该字段仍由集合确定，不提供独立标签信息。

最终更新点 a5bacdf5029f9c1399cf 仍回答全部三种，以“没有直接证据排除”为依据；正文虽提到历史拒绝及goal所需动作，但没有按声明机制完成排除。这里的现象支持模型偏向不收缩集合的描述，尚不能证明具体由冗余favored、奖励平均、数据分布或优化超参哪一个因素造成。能力定义与相容集合目标的差距需要先澄清，不宜仅因为训练reward上涨直接延长训练或声称paper-ready B提升。

审计：2032次completion的reward与诊断score语义字段本地复算一致，训练每步32条且reward均值对齐日志，输入split及1024输出预算检查通过，记录源文件hash与当前本地一致。服务器重新解码全部token IDs、执行原Hermes解析，2032次一致，三份实际训练/验证/测试导出文件hash与运行manifest一致。截断文本触发的JSON解析报错属于已记录失败，未被当作新增基础设施错误。

最终 checkpoints/checkpoint-59 的COMPLETE.json存在，13个要求文件的实际大小与清单一致，torch归档ZIP目录可读；HF两片权重可由torch.load(weights_only=True,mmap=True,map_location='cpu')读取。抽查8个张量切片均相对初始模型变化且检查值有限，最大差3.0517578125e-5，证明实际权重更新。尚未实测恢复优化器训练，不把文件/切片检查等同完整resume验证。ZeRO2保存包含复制的模型state和HF共享权重展开，文件大小不要求等于旧ZeRO3产物。本轮保存环节不再出现上次的异步复制截断。

## 35. r2 保留全集倾向：reasoning与实际奖励信号抽查

用户要求区分难题奖励稀疏与全集题较容易。仅分析既有输出，未请求LM或修改奖励。详细样本保存在 b_grpo_b_r2_final/reasoning_spotcheck.json。

训练全部2600个目标query（含多query题的其他项，失败计错），按gold集合大小：全集824/1056（78.0%），两元素105/1184（8.9%），单元素15/360（4.2%）。全集目标只占40.6%，不是数据数量压倒性多数；但按每项1/query_count贡献的正任务分计算，全集贡献584，两元素84，单元素8.5，全集占正分86.3%（不含失败-1，也不是梯度份额）。按每题每query的8次采样组成组，全集132组都有至少一个正确答案；单元素45组中34组全错，两元素148组中86组全错。这里分解的是诊断query组，实际GRPO仍使用整题reward。

实际step24、checkpoint64c6b07a9930ed1473b9：gold P0.G1={want,neutral}、P0.G2={want,neutral,avoid}。8次奖励[-1,0.5,0,0.5,0.5,0.5,0.5,0.5]，均值0.25，没有一条整题正确。两项均回答全集的0.5回答获得正的组相对advantage；reasoning包含“所有目录profile均相容/没有直接证据”，同时出现角色和goal所需动作读取错误。全训练102条回答同时满足：信息性query错误保留全集、另一全集query正确、整题reward高于组均值。因此存在整段回答获正向信号而其中推断未正确的实际机制，不只是推测“模型可能偷懒”。不能据此量化它对最终行为变化的因果贡献。

同题验证前后：3ef75d6c3fee324d79db从错误声称目录全want、输出两个单want，变为正确识别三种候选并保留全集；属于真实的读取纠正。8b2d853da569bf12232f训练前输出正确{want,neutral}，但理由错误地声称原目录只有两种（核查目录实际含三种）；训练后目录读取准确，却直接认为目录里的三种都与历史相容，输出错误全集。不能把训练前的正确答案当成已掌握逆推、然后遗忘。更新点a5bacdf5029f9c1399cf前后都没有完成历史排除，输出从错误两元素扩大到错误全集，gold为neutral。

证据支持：全集回答更容易获得奖励，真正排除候选的正确样本稀疏，同时整题平均reward把易query的成功与难query的错误绑定。表现为学会/强化“读出目录→没有直接证据→保留全集”，部分纠正了原来的胡乱排除，却没有学会根据有限理性行为完成排除。该解释有样本和奖励机制支持，但不是因果消融结论；不能归咎于favored字段本身，也不能把全部全集题都说成无需推理的简单题。

## 待办与当前优先级：先分析 B 的有效训练信号

用户要求先记录以下 v4 缺口，暂缓继续扩展，优先讨论训练为何强化“目录有三种→没有直接披露→全部保留”，以及仅初始/60步后验证导致发现问题太晚。当前先思考和分析，尚未批准新的奖励、采样课程或验证间隔；未修改训练配置或启动训练。

后续待办：

1. 补充历史依赖更新的答案多样性，特别是集合不变时favored改变、消失或反转；当前9对仍有8对neutral。
2. 构造累计证据权重确实改变最优动作的完整原生历史；现有给定权重单元例不等于已获得这样的历史数据。
3. 明确P-only题面如何提供足够的联合候选与支持强度；set+favored无法完整表达教师信息，B的联合输出监督也未解决。
4. 审查求解循环/预算失败是否系统性排除某些游戏结构，量化筛选偏差。
5. 新机制下正式数据划分与训练效果尚未验证；MENU去留及self-play鲁棒性按用户安排后续讨论。

当前训练问题应区分：奖励/数据允许的通用捷径、GRPO依赖组内奖励差异的学习信号限制、以及多query合并奖励使容易项成功与困难项错误获得同一个整段advantage。正任务分占比不等于梯度份额；生成更长reasoning不等于执行了区分候选的推断。验证频率影响发现问题的时间，不能替代对训练信号的修正。先分析机制，不据此自动过滤全零组、加入自然语言评分或恢复SFT。

## B 训练信号修订：单查询、行为课程与每10步验证（2026-09-13）

用户同意优先落实讨论中的前三项：打破默认全集捷径、提供简单但必须使用行为证据的推断题、解除多查询平均奖励的干扰；明确要求 validation interval=10。本轮只修改本地数据与代码，没有服务器上传、LM请求或训练启动。之前记录的P信息接口、MENU、复杂更新覆盖和self-play事项仍待后续处理。

新增 `social_b_training_data.py`：以v4教师候选为来源，每条任务只含一个查询，保留完整公共历史、目录、观察者自己的偏好和原生SUBMIT_BELIEFS接口。全集/目录先验答案仍正确的题作为控制题；答案偏离观察者初始先验的题作为行为推断题。其中最多两条自主事件、观察者仅有一个未知偏好槽的题归入短历史层，其余为长历史层。这是结构难度代理，不代表已经测得模型能答对，也不把集合大小直接当作难度。额外保存同一前置历史及查询下、不同行动导致控制/推断答案不同的真实分支对照。只使用实际合法、教师相容分支，不修改gold来凑分布。

新开发数据 `new/local_data/social_runs/b_behavior_curriculum_v2/`：198个单查询检查点，全部通过教师重放、精确分数后验检查、反向动作枚举gold检查、原生工具schema计分与题面隔离检查，0失败；6组同历史的行动对照（train/validation/test为3/1/2）。划分按游戏拓扑整体隔离：train121题/23个family，validation28题/5个family，test49题/11个family。为覆盖稀少的短历史行为题，对新的开发包进行family级分层；这些都是已经检查过的开发来源，不是盲测基准，不能与旧r2验证成绩直接比较。最初v1尝试因训练短历史题仅2条而未通过课程覆盖检查，已标记不可训练并由v2替代。

训练池含短历史行为8、长历史行为41、控制72题。运行时不按池大小均匀采样：每4题保留1道控制题，其余3题为行为推断；短历史占核心题的比例随60步从75%线性降到25%，小batch采用可复现的随机取整。每个层内先选family，再选集合大小/favored组合，再选检查点；同一步不重复检查点。按默认seed的60步预览，每20步短/长/控制抽样数依次为40/20/20、31/29/20、18/42/20。采样直接接入DynamicSamplingScheduler，按optimizer step决定，验证不应用课程。全零奖励组仍保留，不按模型输出筛题，不添加reasoning文字评分或SFT。

数据审计同时报告默认全集、目录先验及最佳常量答案的准确率。默认全集和目录先验在两类行为题上的exact均为0，这是当前选题定义所保证的性质，不是学习效果证据；训练短历史层中最佳常量答案仍可达到4/8，且只覆盖少量family，因此这里只能作为小规模训练信号验证包，不能声称已消除所有捷径或完成覆盖。最终是否产生正确的行为逆推样本，要由实际rollout及独立验证检查。

新optimizer导出按query拆分，teacher增加single_query标记，并在scheduler/reward入口拒绝多查询训练输入。历史多查询reward仍可只读复算，不改写旧实验结果。export保留原Hermes解析器往返核验，增加文件hash、训练单位和family隔离检查；已有旧manifest不能跳过这些检查。启动脚本和配置使用新的r3输出目录、b_grpo_data_v2导出目录和上述v2开发输入，保护旧r2产物。没有实际在GPU/vLLM环境导出或启动端到端训练；本地缺少vLLM包，服务器导出仍须通过原生Hermes检查。

`examples/social_b/grpo.yaml`顶层及validation.eval_steps均改为10，保留初始与最终验证：完成optimizer调用次数0、10、20、30、40、50、60后评估同一28题。reward worker提供逐项诊断计数，validation按实际分子/分母聚合：集合/favored exact、格式合法率、预测全集率、需要排除时错误全集率、应保留全集时误排率、多元素favored正确率、短/长行为题正确率和formation/maintain/update等目标类别正确率；空类别显示计数0，不伪造0%准确率。update类别只纳入已通过历史依赖检查的目标（train6、validation2、test1）。这些诊断不参与奖励。

本地检查：104项测试，103通过、1项旧开发数据缺失跳过。覆盖单查询阻止易查询替难查询拿分、结构课程选择、实际scheduler训练/验证分流、损坏导出与跨split family拒绝、错误全集与格式失败诊断，以及既有教师/评估回归。真实本地tokenizer检查198题模板与直接tokenize一致，最长3653 tokens，低于4096输入预算，无截断或静默删题。可检查请求位于 `b_behavior_requests_v3/`；其早期v2请求记录因任务诊断metadata更新而过时，hash校验会拒绝混用。标签重放之后只扩展诊断类别/常量基线及文件hash封装，输入与gold未改变，保留原重放代码hash及后处理代码hash。

## 将三项B/P缺口与MENU去留共同评估（2026-09-13）

用户要求在解决favored动态更新覆盖、累计证据改变行动的原生见证、P信息输入充分性这三项时，同时考虑MENU去留。本轮检查原生规则与当前加权教师，未启用/删除MENU或修改训练配置。

已核实：MenuOffer是面向同一伙伴的两份不同合法报价，回复为REJECT/CHOOSE_1/CHOOSE_2；选择后对应报价立即绑定，并且整个MENU只推进一个提案回合。因此其价值可能来自当场匹配偏好/扩大成交选项，也可能来自后续信息使用；“MENU最优”本身不能证明主动信息获取。普通OFFER的接受/拒绝也是潜在行为证据，应作为候选信息获取行动一起比较。

拟采用共同验收链：已有不完全信息→选择行动→观察原生回复→更新联合支持/权重→利用新信息选择后续行动→改善声明窗口内的期望收益（保持自身优先、相同自身收益再利他、最终并列随机）。检查MENU前必须确认窗口内存在可利用该信号的后续决策；当前窗口仅两次提案回合，3–4玩家局面中未必再次轮到learner提案，但可能有后续回应机会。尚未覆盖受益决策的样本不能用来宣告MENU无用，也不据此擅自扩大教师窗口。

三项工作需要分别验收：

1. 从实际合法自主历史补齐集合不变时favored形成、消失、反转；检查want/neutral/avoid的覆盖及累积证据必要性。MENU和普通OFFER均允许成为证据来源，不预设哪一种更好。只改变教师内部权重但不改变当前B输出的样本仍是审计用途。
2. 将“当前权重不同会改变动作”与“现在主动取得未来信息值得付出机会成本”分开证明。前者保持当前公共物理状态、支持及目标固定，比较原生累计权重与明确标记的教师等权对照，报告完整最优动作集合/价值差。后者要求行动选择预见后续回复及决策，并评估普通OFFER、MENU和其他合法行动。信息诊断应固定其他玩家策略、真实分支概率及物理转移，只限制后续策略使用新增信号；若物理状态本身泄露同一信息，不能通过假装隐藏回复构造虚假的无信息对照。仅有动作并列集合变化也要与严格收益改进区分。
3. P-only建议直接获得联合候选与明确相对权重；例中两个三值隐藏槽最多9个初始组合，可用紧凑候选表提供。同时保留公共/私有信息边界：其他玩家依据公共联合分布和各自偏好行动，不能把按learner私有信息条件化后的分布当成大家的共同信息。给模型完成的当前belief，不要求它从历史重推B；未来假设回复的更新属于planning。正式B→P若仍只输出边缘set+favored，仍须解决信息表达缺口，不能默认把边缘相乘或任意给favored一个概率。

MENU建议先保留为可关闭的待评估机制。若其增加稳定、可解释的高价值决策（无论即时偏好匹配还是后续信息使用），且有跨游戏结构覆盖和可接受的教师求解成本，再保留进入正式分布；若只重复普通报价已有的能力、引入近乎免费的默认优势，或主要增加组合分支/求解失败，则考虑移除或重设成本/规则。现阶段没有依据宣布保留或删除，不将旧不同伙伴机制下的MENU例当作新v4见证。

用户随后支持先用MENU/OFFER调查前两项，并询问联合组合相对权重的具体表达。P输入当前仅讨论候选组合表+非负相对质量，概率为该行权重除以全表权重总和；整表统一缩放等价，只有正权重行属于possible set，favored由边缘求和唯一最大值导出。必须保留联合组合而不能默认边缘独立；可展示百分比作为读表辅助，但teacher使用未舍入权重，不把正的小概率舍入成不可能。这里权重来自声明机制的累积行动似然，是给P的当前条件信息，不是额外要求P估计的B输出。此格式尚未写入正式P接口，也未自动修改B的输出schema。

首次微型教师可行性调查保存在 `new/local_data/social_runs/menu_offer_weighted_probe_v1/probe.json`：forward、bundle、information三个手工结构各比较禁用/启用MENU，仍用新v4两回合教师，每个配置仅访问4个节点，不是自然频率或信息价值评估。六个配置均无记录的求解失败。information结构中发现普通OFFER被ACCEPT后，目标集合仍为want/neutral/avoid，favored由undetermined变为want，边缘质量由各1/3变为3/7、5/14、3/14；该事件在MENU开关两种机制下均出现，不能将其归为MENU特有证据，也不是favored反转。其真实联合后验保留8个组合，相对质量为六行2、两行1，已通过精确分数后验重放检查。在这两个事件之后的当前行动根部，累计权重与相同支持等权重对照尚未改变最优动作集合。后续仍须调查倾向消失/反转、对行动产生严格影响以及主动信息获取价值。

## 用户修正：定性不确定性输入与MENU保留条件（2026-09-13）

用户指出，显式联合概率/数字权重可能使P训练依赖实际迁移场景不常出现的输入；更贴近目标使用的是likely、very likely、almost certain、unlikely、impossible等自然语言倾向。主P输入设计转向定性表达，不再以数值组合表作为默认方案。迁移影响目前是合理风险判断，尚无实验结论。教师内部仍可保留联合权重以计算与审计；给P的输入不自动暴露精确权重，不把自然语言等级悄悄等同于某个精确概率。

需要保留三类信息：仍可能/已排除的候选，支持强弱，以及影响决策的联合约束（可用条件句表达）。impossible对应排除；unlikely/almost certain仍保留可能的例外。未来P-only输入可以直接给这些判断，无需模型从历史重新完成当前B推断；自然语言同义表达和语序变换是后续迁移检查方向，不把固定词表背诵作为能力目标。现有B输出schema尚未因此变更。

评分约束：不能用模型看不到的精确概率决定唯一gold。先检查同一公开定性描述所涵盖的不同教师belief下，最优动作集合是否存在共同解；无共同解的题不能直接使用单个隐藏数值教师的exact动作标签，需要明确额外决策准则、补充可见信息或改变监督方式。并非因此永久排除所有模糊决策任务。重要对照是同一游戏局面下，弱倾向与强倾向导致不同合理动作，同时各自描述涵盖的权重变化不轻易颠倒对应标签；不能只训练完全忽略支持强弱也可答对的题。

用户明确收紧MENU标准，覆盖前述“即时偏好匹配也可成为保留理由”的建议：如果MENU的优势仅来自更好的即时成交，就删除MENU并寻找更合适机制。保留需要新v4原生实例表明后续利用获得的信息产生决策收益。当前小调查尚未证明仅有即时收益，因此未执行删除。后续比较需分别记录成交优势、后续信息收益及其机会成本；普通OFFER自身的试探能力是首选对照，若不足，再考虑有明确机会/资源成本、允许后续行动利用结果的信息获取机制。未新增机制、未修改训练配置或启动训练。

## 定性P接口首版与MENU/OFFER信息使用调查（2026-09-13）

本轮落实两个方向的本地实现与开发验证，没有LM调用、服务器上传或训练启动。新增 `social_p_qualitative.py`：P直接获得当前可能情形、联合约束、已知偏好及自然语言支持强弱，不展示历史、数字后验或教师评分信息；仍使用原生SUBMIT_ACTION。联合情形完整列举，明确不能跨情形拼接，避免默认边缘独立。unlikely与almost certain保留例外，只有明确impossible/certain才据此排除候选。

教师通过线性规划检查一个定性描述下整族belief是否有共同最优动作，自身期望收益优先，在自身并列的可行面上再检查其他玩家总收益；没有共同解时标记ambiguous_information，不使用隐藏点概率强加gold。语言的数值区间仅是私有的宽范围压力测试假设，并非英语词语的普遍含义；证书只对声明区间成立，不能据此宣称迁移性已获验证。当前只覆盖最后一回合响应，以及伙伴响应策略在整个区间稳定的最后一回合报价。报价证书还要求learner偏好公开、所给判断为公共信息；伙伴残余并列集合若随belief改变则拒绝证书。多回合、一般私有信息及动态伙伴策略仍未完成，不能用终局代理标签替代。

开发产物为 `new/local_data/social_runs/p_qualitative_examples_v4/`：两个原生游戏结构、八种信息强度、两种措辞/顺序，共32个变体，22个有证书，10个信息不足而不评分；明确标记training_ready=false，不当作32个独立游戏或正式训练集。报价对照在相同物理状态下，弱倾向选择确定收益3的报价，高确信度选择收益可能为4或0的报价；另一个响应对照在自身收益相同的情况下检验利他选择随支持强弱改变。这里belief是直接给定的P输入，不声称这些强弱已由真实自主历史产生。

新增 `debug/audit_menu_information.py`，产物 `new/local_data/social_runs/menu_information_audit_v3/`。固定其他玩家策略、实际分支概率和物理转移，对比正常更新与后续learner决策冻结根部类型权重。冻结策略仍看到当前物理状态，因此该差值只是信息使用诊断，不是最优无信息策略对照，也不是纯信息价值的因果分解。重要分支另用原生状态转移与手算目标满足收益重放，未仅复用缓存Q值。所有收益限于教师声明的两次提案窗口；实际后续重新规划可能与根部窗口延续不同，不能称为完整对局收益。

调查共44个配置记录：28成功、14求解失败、2生成约束失败。后两条来自同一个无正偏好候选的无效随机源在两个开关下的记录。14次求解失败均在MENU开启时：11次节点预算、2次时间预算、1次并列策略迭代循环。成功根部为21个普通OFFER配置、7个MENU配置；随机源中17个合法普通配置都成功，MENU仅3个成功，筛选偏差很大，不能推断自然频率或全局无用。

已得到三个可核验结论：

1. two_types原生结构中，普通OFFER后的回复会改变后续选择，正常更新的窗口自身期望收益为1.5，冻结权重为1.0；这是现有OFFER可承载主动试探训练的开发见证。
2. 两个成功MENU根部存在最优MENU行动使用后续信息的候选，MENU自身期望收益由冻结的1.25变为1.5，但都与最佳普通OFFER的1.5并列。它们没有证明MENU相对OFFER提供了额外价值；另一结构中还有无需该信息更新也达到1.5的普通行动，不能把某条行动改善等同于整体最优值改善。
3. 另造的最终回合原生反例中，MENU把最佳普通OFFER的0.5提高到1，回复后游戏立即结束，信息更新收益为0。这是即时成交匹配，不能作为保留MENU的信息收集证据。

当前处理：正式训练仍维持MENU默认关闭，保留原生可选机制供诊断，优先沿普通OFFER扩充信息获取实例。尚未证明MENU优势全都仅来自即时成交，因此未删除兼容代码，也未添加新机制。如果后续充分调查仍无法给出超过普通行动的后续信息贡献，再按用户标准移除。已有证据不支持把MENU最优本身当作信息收集能力标签。

新增13项针对性测试（定性P 9、MENU调查4），连同加权教师、随机并列窗口和GRPO回归共29项通过。检查了LP自身优先/利他并列、区间内部新增伙伴并列导致拒绝、无教师数据泄露、原生动作计分、终局范围限制，以及信息诊断的原生重放。原待办中favored消失/反转的历史覆盖、累计历史权重相对等权确实改变行动的完整见证，并未被上述给定belief或冻结未来更新对照替代，仍需补齐。

## MENU替代的首要目标与候选机制（2026-09-13）

用户明确将替换MENU作为当前首要目标：行动应能主动取得信息，以改善后续规划，让P影响B所获得的证据。这一目标不能由“行动本身多给一个成交选项”替代。需要检验完整链条：当前belief→选择调查对象/内容→得到信号→更新belief→按不同信号采取不同后续行动→收益覆盖调查成本。真实偏好不因调查被改写。

当前代码的关键限制：SharedWindow按全体玩家完成的提案回合计数，默认两次，并非learner的两个决策。正常3–4玩家轮转中，调查之后可能尚未再次轮到learner，教师就已到达窗口终点。之前正例使用连续learner提案，只能作为开发见证。替代机制必须同时调整被评估的时间范围，至少覆盖调查后可利用信息的决策及其相关结果；不能只加动作名，也不能将非终局窗口收益宣称为完整长程价值。

候选设计（本轮提出，尚未实现或视为用户已选定）：有限的INVESTIGATE(player, record_id)动作，花费当前提案机会，公开一条预先存在、可核验的相关行为记录，不在当前局面创建/撤销承诺或直接增加目标收益。记录包含当时的可选行为、局面及实际选择，生成时固定其原生行为机制；对方不能临时自报偏好。隐藏偏好与当前局面保持一致，但记录不要求完全辨识类型；多个类型可产生同一行为，允许只改变支持强弱。每份记录最多获取一次，调查对象/记录少量枚举，先保持公开信号以兼容现有公共历史教师。它增加了证据来源，是新游戏规则假设，不能把事后伪造的说明文字当作原生证据。

先建立有限、可枚举的观察分支和短终局原型，再考虑接入一般历史。记录生成的选择策略必须在调查之前定义并固定，不能根据当前希望得到的gold倒推记录；同一偏好下相关记录也不能未经证明按独立似然相乘。不要直接增加无约束的“询问偏好”动作：现有自身优先/利他/随机并列规则不保证自由回答真实，若所有回答对收益相同，残余随机会让回答与类型无关。要训练战略交流则是另一项机制设计。

候选验收：同局面中有必要查、没有必要查、查错对象、成本过高不查等对照；取得信号后续动作需实际依信号改变；与最佳普通OFFER及直接行动比较净收益。纯信息贡献的对照保持调查成本、物理状态和外生时序一致，改变可观察信号的精细程度并重新求解允许的后续策略；明确公开信号会同时影响伙伴belief及策略，不把固定伙伴诊断自动当作整体因果效果。P-only可给出未来各信号对应的定性belief分支以隔离当前B推断；联合B/P版本再从真实记录产生这些更新。数值教师的标签仍须通过可见定性信息充分性检查。此次只记录设计方向，未改原生动作、教师窗口或训练配置。

## 公开history纠正与相关工作启发（2026-09-13）

用户指出现有history已公开，检索真实历史不产生新的信息。接受这一纠正：撤回“查询行为记录”作为当前首选替代方案；若另造隐藏档案才使该动作成立，就额外改变了信息来源，不能当作已有规则自然支持。新的重点是选择行动主动产生尚未发生的行为证据，或明确引入新的偏好反馈渠道。以下是查阅原论文后的设计启发，不是文献已验证MARSHAL机制有效。

- Sadigh等，Information Gathering Actions over Human Internal State，IROS 2016：https://iliad.stanford.edu/pdfs/publications/sadigh2016information.pdf 。机器人选择会引起不同人类反应的动作，并用反应推断隐藏内部状态；观测过去的动作与主动产生新反应不同。论文的信息收集目标使用熵下降，并与任务奖励组合，不能直接当作我们净长期收益教师的最优性证明。对本项目的启发是设计试探报价/邀请新报价，而非取回已经公开的历史。
- Sadigh等，Active Preference-Based Learning of Reward Functions，RSS 2017：https://www.roboticsproceedings.org/rss13/p53.pdf 。主动选择两条轨迹供人比较，根据相对偏好反馈学习奖励。可以启发有成本的方案比较查询，反馈不直接执行方案，从而避免MENU自动成交优势；但必须明确反馈生成规则，不能默认自利玩家会如实回答假设问题。
- Wilde等，Active Preference Learning using Maximum Regret，IROS 2020：https://arxiv.org/abs/2005.04067 。不同奖励参数可能对应同一最优行为，作者据此在解空间使用regret选择查询。启发：不能把减少候选/熵当作P训练目的；信息需要降低后续选错行动的损失。本项目仍保留原期望自身收益优先/并列利他目标，不自动改为minimax regret。
- Hadfield-Menell等，Cooperative Inverse Reinforcement Learning，NeurIPS 2016：https://papers.neurips.cc/paper/6420-cooperative-inverse-reinforcement-learning.pdf 。共享奖励下，行动可以同时服务任务与沟通，最优示范可能牺牲即时收益来改善另一方后续行动；不能直接移植其合作/诚实动机到本项目各自收益优先的玩家。需让伙伴完整规划其披露或保留信息的后果，而不是强制类型与回答一一对应。
- Bellinger等，Active Measure Reinforcement Learning for Observation Cost Minimization，2020：https://arxiv.org/abs/2005.12697 。对获取观测收取成本，在任务回报与观测成本之间取舍。可作为纯信息通道的对照设计，但当前公开历史本身不能充当付费才可见的观测。

候选优先级调整：先比较基于真实互动的“邀请报价/请求反报价”与纯偏好比较查询。前者可令learner花费当前主动提案机会，让指定伙伴给出一份可执行报价或拒绝，learner再决定是否接受；其具体回合/到期规则仍待定，尚未实现。这种动作能产生新的类型相关行为，但也可能只改善即时匹配，因此必须沿用MENU的信息贡献验收，不能仅凭名字接受。后者可更清楚分开信息与成交，但需额外声明一个可靠或有已知误差机制的比较反馈渠道；若不作该假设而保留战略回答，就必须求解真实激励，可能出现不同类型给同一回答。不要通过修改公开history来人为制造查询价值。

## 简化核验动作的捷径风险与教师时间范围前置条件（2026-09-13）

用户认为邀请报价过于复杂，讨论转向最小INSPECT(player, goal)：占用当前提案机会，由环境公开一个真实偏好，不改变承诺、不成交。这是新增可核验偏好的游戏假设，尚未实施；不再以查询公开历史为信息来源，也暂不增加货币、噪声或战略回答。用户强调“一上来就问”的风险，并再次指出默认两个全体提案回合不覆盖正常轮转后learner再次提案。

核查确认：SharedWindow的end是root.turn_index + turns（受真实终局上限约束）；BeliefOracle及现有B数据入口默认turns=2。它可能包含learner提前作为响应者使用信息的机会，但一般不保证再次提案，更不保证后续收益在截断前实现。不能仅将固定数字改为3/4，或将截止改为learner第2次决策：行动效果仍可能在更晚实现，且不同玩家/候选行动不能使用不可比的截止点。非终局满足目标分不能作为严格长程P金标准。

拟定前置路线：先在规模小、正常3–4玩家轮转的有限短局上，以共同真实终局为评价点，保留中间伙伴决策、响应和信息更新，比较“先核验再按结果行动”与最佳直接行动的净终局收益。保留原效用及并列规则，不给信息增益额外奖励。求解失败不回退为两回合标签。对完整长局的泛化与计算可行性仍需另验，短终局原型不等于长局问题已解决。

同时解决规划/执行一致性：现有BeliefOracle每个实际动作重新求一个完整窗口，根部预测的延续与后续实际策略可能不同；即使将窗口延至终局，一般和博弈重新选择策略也不自动保证一致。原型应明确执行根部已核验的整套条件策略，并按同一策略计算行为似然与belief；若要每步重新求解，则必须验证新策略与预测延续一致，否则不能把根部价值当作执行收益。新的教师机制与旧v4短窗B标签需要分版本，不能只在P端扩大窗口后混用旧行为似然。

INSPECT的首项验收是防止无条件查询捷径：在一致游戏结构的对照中改变可见belief、剩余机会或承诺状态，分别得到严格值得核验、严格直接行动更优、问错对象等原生见证；只统计并列动作变化不够。占用一回合必须实际造成可计算的机会损失，否则查询可能近乎免费且总问确为最优。记录无条件查询基线以及该问不问、不该问乱问、对象选择错误，不人为惩罚一切查询或按比例改gold。本轮记录并核查设计约束，未改教师默认值、动作schema或现有训练数据。

## 当前统一问题清单：暂停机制推进，先讨论监督信号的研究定位（2026-09-13）

用户要求先汇总记录，再转向general问题：目标是让LM学习social reasoning，主要障碍是如何构建可验证、且确实对应所需能力的B/P细粒度监督信号，而非仅把游戏终局reward接入RL。以下集中清单覆盖此前尚未完成的事项；后文研究方向是讨论建议，不是新增实施授权。

1. B标签语义：多元素集合允许favored的v4修订已实现；favored仍由声明先验及行为似然确定，不是隐藏真实偏好的别名。旧错误定义的数据/训练结果不能与v4混用。历史中favored形成、消失、反转及want/neutral/avoid覆盖仍不充分。
2. B训练捷径：已实现单查询、行为课程、相关诊断和每10步验证，尚未通过新一轮实际训练证明解决。短行为题与family覆盖仍少，不能让默认全集/常量答案或某种行为模板提供主要奖励。完美信息样本是需要的覆盖部分；3–4玩家、goal/commitment数量、隐藏槽数量及归属仍需系统覆盖。
3. B→P证据：需真实累计历史导致支持强弱改变，进而严格影响决策的完整原生见证。给定belief的动作翻转、冻结未来更新的价值差和真实历史权重相对等权差异是不同检查，不可互相替代。
4. P输入与标签：定性信息首版只覆盖终局报价/响应；不向LM暴露数字belief，不以隐藏精确概率强加唯一gold。联合约束、公共/私有视角、定性描述的校准假设及多回合标签充分性仍需解决。现有32个变体仅来自两个结构，未验证迁移。
5. MENU与替代：正式训练MENU仍关闭，保留诊断兼容代码；已见即时成交优势，但尚未证明额外信息贡献优于OFFER，且求解失败偏差明显。查询公开历史无信息价值，旧档案方案撤回；邀请报价被认为复杂；最小INSPECT仍为未实现候选。INSPECT必须有真实机会成本及“该查/不该查/查谁”的严格对照，避免无条件查询。它也会增加直接观测偏好的规则，需与论文现有MNO假设核对，不能悄悄视为原框架不变。
6. 教师时间与执行：默认两个全体提案回合不足以保证观察后续信息收益；拟先研究正常轮转、小规模短局的终局教师。根部延续与实际重新求解策略需一致；求解失败不降级短窗gold，改变机制须分版本并重建对应行为似然。
7. 规模与泛化：节点预算、循环和时间失败可能系统性筛掉复杂社会互动。已检查的开发样本不能当盲测；新拓扑、新伙伴行为规则、自然语言表达和跨任务迁移仍未验。B/P作为能力起步、self-play扩充复杂性是路线设想，不能指望self-play自动修正错误中间监督。

本轮只更新记录、只读代码并查阅论文；不继续添加INSPECT、替换MENU或启动训练，优先讨论如何构造社会推理监督信号。

## 细粒度社会推理监督：相关工作与待讨论的构造原则（2026-09-13）

相关工作核查（初步定向检索，不构成完整新颖性结论）：

- DEL-ToM: Inference-Time Scaling for Theory-of-Mind Reasoning via Dynamic Epistemic Logic（2025），https://arxiv.org/abs/2505.17348 。DEL模拟器根据事件及公共/私有观测更新可达关系，产生逐步belief标签，用来训练Process Belief Model验证器并在推理时选择候选轨迹。它是已有belief过程监督的直接例子，但主要解决形式化故事中的信念跟踪/嵌套信念；并非本项目从战略行动逆推隐藏偏好，也不是直接用该标签训练行为LM的同一方案。
- Process Reward Models for LLM Agents: Practical Framework and Directions（Choudhury，2025），https://arxiv.org/abs/2502.10325 。AgentPRM用Monte Carlo rollout回报构造动作级价值目标；这提供细粒度决策监督，但目标仍来自未来结果，不能自动判断模型是否正确建模他人。
- Infusing Theory of Mind into Socially Intelligent LLM Agents（ToMAgent，2025），https://arxiv.org/abs/2509.22887 。采样心理状态与话语，模拟后续对话，根据目标分筛选后监督训练心理状态及话语。它将显式ToM与交互效果结合，直接相关；筛选的“对目标有用”不等于已独立核验心理判断符合证据，二者应分开评价。
- Machine Theory of Mind（Rabinowitz等，ICML 2018），https://proceedings.mlr.press/v80/rabinowitz18a.html 。从行为观察学习其他agent模型并预测其行为，包含不同agent群体和false-belief测试。说明对他人的建模也可通过可检验预测学习，而不必拥有每句内心独白的唯一文字gold。

研究定位建议：把“更密集的奖励”“中间判断的语义正确性”“这些判断对交互的作用”分开。B/P是一种功能分解，不能仅因输出分成两个字段就认定实现了社会推理或发现了两个内部神经模块。当前B主要是自身关于他人偏好的belief，尚不等于完整监督对方所持信念、意图和递归ToM。作为本项目的可操作能力目标，可考察：根据他人的目标、所知信息及其选择空间解释/预测行为，并据此调整自己的行动与信息获取；这不声称覆盖全部social reasoning。

标签构造原则：知道隐藏真值不等于知道观察者应当确信什么；同一可见历史兼容多个偏好时，要保留相应不确定性。后验gold依赖先验、伙伴策略/信息及求解范围，需明确这些生成假设并与题面匹配。按“证据→他人状态判断→条件反应预测→自身行动”构造能独立核验的小任务，不必把任意自然语言CoT逐句当作唯一正确证明。可增加用于区分候选的条件行为预测检查，但这仍属于B/P相关计算的监督视角，不另立能力分类，亦不自动把多个答案平均为一个训练reward。

验证原则：在合法、信息充分的配对局面中，改变他人目标/所见信息/可选替代行动应引发相应判断或计划变化；不相关人物改名、动作枚举顺序等语义等价变化应保持答案。故意构造行为不足以辨识偏好、拒绝由更好替代机会而非avoid导致等控制，不能把单个“拒绝”机械标为反感。伙伴新策略/信息结构及新任务机制需留出测试，以区分拟合固定oracle与可迁移他人建模。只改变显式输入/输出所得到的效果是功能证据，不等于证明内部CoT忠实或真实心理机制。

可能的研究贡献应通过实验检验：在相同游戏、相近训练计算和数据预算下，对比outcome-only、单独B、单独P及B/P监督，分别报告belief证据一致性、条件行为预测、社会因素干预下的行动适应、终局收益与迁移。局部可核验任务可先建立有效监督，不必把所有进展阻塞于完整长程全局求解；但局部标签不可冒称全局最优。提出这些比较不代表已决定恢复SFT、训练PRM或改变现有GRPO奖励。

## 现有游戏的社会语义审查：发现teacher玩家编号依赖（2026-09-13）

用户同意沿可核验社会推理对照推进，先检查已有游戏，强调teacher逻辑必须对应所需社会逻辑。本轮新增只读诊断 `debug/audit_social_semantics.py` 与 `debug/audit_teacher_selection.py`；未修改teacher、游戏规则、训练数据或奖励，未调用LM或启动训练。当前数据包之前的training_ready仅表示其原有构建检查通过，不代表通过本轮新增的社会语义验收。以下新问题解决前，不应把原包当作已通过这一验收而开始新训练。

审查产物：`new/local_data/social_runs/social_semantics_audit_v1/`（summary、原生fixture见证、198道题重放及54个源的重命名结果）；因发现差异追加 `new/local_data/social_runs/teacher_selection_audit_v1/`（4个源的因果定位及26道题受影响情况）。文件保存运行源代码和数据hash。

已有正例，不必推倒重建游戏：

- forward与已有deadline变体保持当前承诺和待回应报价相同，改变后续提案机会。目标偏好为want时，forward中REJECT/ACCEPT自身终局收益为2/1；deadline中为0/1。因此拒绝可以来自更好后续机会，而非avoid。
- forward中ACCEPT的相容目标类型只有avoid；相同报价在deadline中被三种类型全部接受，后验仍是三元素全集。这是“同样接受行为，信息含义取决于后续机会”的原生对照。deadline是已有fixture变体，未声称已包含在当前54个源或198道训练检查点中。
- bundle与compensated保持承诺、当前报价、目标槽为avoid不变，改变其他goal上的偏好。bundle中REJECT/ACCEPT自身终局收益为0/-3，compensated中为0/1；因此接受不意味着喜欢该目标，须考虑组合收益。两侧目标槽三类候选对观察到的相应回复均相容，全集答案在这里有实质理由。
- 私有信息控制：切换observer实际私有偏好（公共目录不变）不会改变伙伴在相同自身类型下的策略或公共后验；observer自己的判断则按其所知偏好条件化。通过这个检查不代表已有“偏好不变、只有对方看见的信息改变”的正对照。

上述4个原生fixture的全部根动作、全部当前行动者类型都以原生状态转移和独立目标满足计算重放，收益核验通过。它们在本次检查点的窗口恰好到真实终局；不把这一事实推广到所有B源。

当前B开发包198道题全部按v4重放并通过精确分数后验/标签检查。覆盖41个源，分为短行为15、长行为63、控制120；45道题在observer视角已无剩余联合不确定性，这属于覆盖占比问题，不是这些样本本身错误。12道多元素集合具有具体favored。去重后691个自主历史事件中，记录到144次候选行动者类型因自身收益被排除、31次因并列利他被排除，另有22次保持公共支持但改变权重的事件。这些计数是历史事件/类型层面，不能冒充对每道查询的因果归因或模型学习效果。

只按最后自主动作类别预测训练多数答案的基线，在所有类别上都退化为默认全集；训练/验证/测试总正确率分别为56/121、14/28、19/49，在行为子集均为0。这只证明该简单基线过不了这些行为题，不证明已消除更复杂捷径。现有显式同前缀行为分支对照仍只有6组（train3/validation1/test2）。

新确认问题：teacher不满足玩家编号置换不变性。对54个源的起点，只反转玩家编号，并同步搬运各玩家目标偏好、动作、轮转、承诺建立prefix与报价对象。42对在两侧均成功求解，12对均超出3000节点预算而不能比较。成功的42对中38对根部动作价值及动作集合不变，4对价值变化：random-940008-mixed、random-940013-mixed、random-940018-mixed、random-940042-mixed。其中后3个源至少一个行动者类型的可接受动作集合也变化；940008本次仅非最优动作价值变化。

定位方式：保持生产RandomTieWindow.solve函数其余代码原样，只在独立诊断类中将两处玩家遍历顺序替换为重命名前顺序的映射。4个源均复现原差异，且映射顺序全部恢复原根价值和动作集合；原版、重命名默认版、映射顺序版的全部根动作价值均经独立原生执行核验，三套策略都通过现有稳定策略证书。诊断类未接入生产oracle。这证明问题来自多套自洽条件策略之间的求解选择受玩家编号顺序影响；不是终局收益算术错误，也不是此前已修正的“最终并列按动作枚举顺序执行”问题。

这4个源在198道包中对应26道题：重命名后15道B标签不变、4道改变、7道历史在新选策略下变为零似然而被拒绝。其中训练17道里8道不变、2道改变、7道不相容；测试9道里7道不变、2道改变。举例：test的6eedba8ddc7f1ada3fdd由单want变为三元素、favored仍want；train的bca6c2924ff27b352525由单want变为三元素undetermined。这是沿检测到的4个源进行的局部追查，不是所有198道题或所有玩家置换的完整审计。

语义结论：每个玩家“自身期望收益优先、并列再最大化他人总收益、残余并列均匀随机”并不总能唯一指定整套互动策略。现有稳定性证书证明相对于所选延续无有利单方偏离，不能证明唯一社会解释或编号不变。若把额外求解次序当作任意隐藏约定，gold可能监督了该约定，而非用户希望的社会逻辑。仅通过固定/规范化编号让测试通过也不充分，仍需说明多解选择的行为依据，或对未被声明规则唯一支持的标签保留不确定性。多初始值/次序一致只能作为敏感性筛查，不能宣称穷尽所有合理策略。

当前优先级：先明确teacher的行为契约、处理多解选择及其对历史逆推的影响，再扩充社会对照或新机制。保留现有正例与受影响原始样本作回归，不静默删题或修改gold。另两个已知边界仍在：默认两回合及每步重规划不适于直接证明长程信息收益；当前独立私有信息仅为自身偏好，尚无同偏好不同私有观察的正向覆盖，不能宣称已覆盖完整信念视角推理。

本轮26项相关回归测试通过；新审查脚本的原生执行/精确后验/置换对照断言通过，编译及git diff --check通过。测试通过与发现语义缺口并不矛盾：原回归验证的是原声明实现，本轮增加了此前未覆盖的编号不变性标准。

## 任务设计与teacher行为契约草案v0.1（2026-09-13）

用户确定推进顺序：先设计任务与teacher行为规则，再修改验证solver，迭代几个回合后才生成正式监督数据与讨论训练。本节是这一轮的具体设计草案，区分既定偏好、拟议契约和未解决项；不构成solver已实现或新gold已获认证的声明。只使用现有原生游戏作起点，MENU关闭，INSPECT等新动作暂不加入。

### 一、任务究竟要求什么

本阶段的操作目标：模型根据行为发生时的选择空间、行动者目标及其掌握的信息，对他人偏好形成有证据支持的判断；模型能够使用给定判断，预测相关互动并选择自身行动。B和P仍是两个功能方向，不新增必须同时输出的能力分类。

B题面提供完整相关游戏规则、公开偏好目录、真实公开历史、observer自己的偏好及明确标记的初始布置。回答指定player/goal的完整possible set与favored；既包括确有排除的题，也包括行为无法区分候选的题。环境真实偏好仅用于生成合法轨迹与审计，不能直接充当observer答案。初始布置是干预，不反推其选择；自主事件则按声明机制解释。阶段一继续以指定单查询审查，不把模型自行选一个最容易判断的目标当作完成监督任务。

P-only题面直接提供已形成的当前判断，包括完整/不完整信息、定性支持强弱和必要联合约束，以及规则、当前状态和原生合法动作。不要用隐藏精确权重决定可见信息无法支持的唯一动作。条件行为预测可作为单独的小检查点，用于核验B/P之间的连接；不要求模型每题输出概率、全部策略树或固定CoT。自然语言推理可自由表述，首版不逐句评分。

每个设计单元是一组有明确变化因素的局面，必须记录：保持什么、改变什么、观察者能看见哪些变化、预期哪些答案改变或不变、机械捷径为何会失败、预期结论的独立依据。对照成员不是任意改写标签；必须在各自机制下合法且可能发生。不同场景不强求完全相同完整history，但要说明物理状态、时间范围或公开目录中究竟改变了什么。

### 二、首轮使用的设计单元

| 编号 | 现有起点与变化因素 | 要求的判断/决策 | 目前证据与下一项验收 |
| --- | --- | --- | --- |
| D1 后续机会 | forward / deadline；保持当前承诺、报价、偏好目录，改变后续提案机会 | 对want行动者，有后续机会时拒绝，无机会时接受；观察到ACCEPT后的B分别为单avoid与三元素undetermined | v4下终局价值已原生核验；新契约下重新做独立推导与策略唯一性/结论唯一性检查 |
| D2 组合收益 | bundle / compensated；固定目标槽及当前报价，改变其他goal偏好 | 同为avoid，可以拒绝也可以接受；相应回复不自动排除目标槽三种候选 | v4下拒绝/接受终局价值为0/-3与0/1；复核补偿因果，保留无法区分候选的控制 |
| D3 目标判断用于行动 | 已有qualitative-risky-proposal；同一物理局面分别提供伙伴want/avoid的确定信息 | 在高收益但需要该伙伴配合的报价与稳妥报价之间严格切换 | 现有原生风险报价收益4或0，稳妥报价3；按完整信息两端人工核验所有合法替代，不能只比较预选两项 |
| D4 强弱判断用于行动 | 同一risky-proposal及已有confidence-response；支持不变，只改变可见支持强弱 | 弱倾向与高确信度下作不同合理选择；自身并列时遵循利他目标 | 当前已有宽区间LP证书，但区间只是校准假设；新契约须检查措辞的充分性，信息不足标待定 |
| D5 行为只改变支持强弱 | forward的已有二候选变体，公开目录只有want/avoid；观察REJECT | 两种都仍可能，但want更受支持；不能把favored等同于确定 | 在当前声明策略下两类型REJECT似然1与1/2；此数值只供审查，模型不输出概率。先核验该似然是否独立于求解多解选择；消失/反转历史仍是缺口 |
| D6 信息视角与泄露控制 | 已有private_visibility控制；公共目录不变，改变observer实际私有偏好 | 伙伴不能读取observer私有真值；observer可用自己知道的偏好条件化 | 已通过现有核查；仅是私有信息边界控制，不声称覆盖同偏好、不同所见事件的正向推理 |
| D7 语义等价变化 | 对以上单元置换玩家、goal、动作编号，重排目录/合法动作展示；保持实际语义 | 对应B标签、行为似然及P价值/动作集合按映射一致 | 首先保留现有4个玩家编号失败源作反例；不能只检查选中动作，非最优动作价值也影响反事实推理 |
| D8 规则不足与不可能证据 | 当前多策略选择失败源、定性信息不足题，以及给定teacher下零似然事件 | 规则不足不强给唯一gold；零似然历史不得重置全集后继续打标签 | 先作为teacher拒绝/待定验收，不强制添加到LM输出schema；不将所有多解局面一律标全集或undetermined |

这些是审查用的设计单元，不是固定的能力taxonomy，也不是每题必须通过全部内容。每个单元都有明确用途：有些检查决策变化，有些检查应该保持不变，有些检查应当拒绝打标签。表中已有数字表示之前v4原生检查的结果，不能因为已写入草案就变成新teacher的gold。

D1的人工推导起点：当前接受让行动者获得一个目标的收益，但建立的承诺会阻止之后与另一玩家达成更优组合；拒绝保留后续选择。want类型在后续能获得两个正收益目标，因此有机会时偏好拒绝；终局当前回合则拒绝什么也得不到。neutral类型的自身收益可能并列，必须继续检查其他玩家收益；avoid类型可能存在残余并列。推导须枚举可行后续报价与伙伴按自身信息的响应，不能仅凭“有未来”推断拒绝。以原生状态转移计算收益可独立检查算术，但沿同一solver策略重放本身不证明这套策略是规则唯一支持的结果。

分布设计：随后在3–4玩家、goal数、commitment状态、隐藏偏好数及归属上扩展，包括全局一个隐藏、同一玩家两个隐藏、不同玩家各一个隐藏，隐藏者可包含observer。完整信息与不完整信息均保留。第一轮不设训练比例或追求数量；先确认每组对照成立，再检查是否只集中在一个拓扑。不能把“没有用到隐藏偏好”与“样本无效”画等号，前者可作为控制，但不能垄断有效学习信号。

### 三、teacher应满足的行为契约

T1 信息边界（既定原则）：每个玩家知道自己的偏好、公开规则/目录及当时公开历史；不读取其他玩家真实偏好，也不使用未来实际发生的事件。第一轮没有额外私有消息，不能声称已覆盖完整false-belief或高阶ToM。以后若扩展私人观察，必须独立定义每个玩家的观察规则，不能只在prompt里说“他不知道”。

T2 偏好与效用（既定原则）：偏好在一局内固定；按照原生goal/commitment规则计算效用。每个玩家先最大化在自身信息下的期望自身收益，自身严格并列时再最大化其他玩家期望收益之和，两层仍并列才在相应原生动作之间均匀随机。learner与伙伴遵循相同目标。没有额外合作、信息量、披露或迎合observer的奖励，也不根据已实现的隐藏世界事后挑“最优”动作。

T3 时间与条件计划（拟议首版）：审查用小局或剩余短局统一计算到共同真实终局，计划必须允许根据随后观察到的回复改变行动。轮转、中间玩家选择及其收益都保留；不因为当前题的learner身份而给不同玩家不同截止点。成本来自原生机会损失，不把同一可完成交易只是推迟一轮当作已证明存在成本。较大的完整长局暂不承诺可求解。

T4 先验与事件更新（既有v4约定，需显式保留范围）：首轮从公开目录的不同联合组合等权出发，保留各玩家内部目录约束，并按完整合法历史累计更新。只有声明为自主行为的事件贡献行动似然；setup干预不贡献。过去事件始终用当时行动者的信息及当时规定的策略解释，不能用observer事后知道的信息倒推。这里的favored是给定先验和行为模型下的支持强弱，不是普遍人类概率语义。

T5 多解不能由隐藏程序顺序裁决（新的硬验收原则）：T1–T4不保证整套互动策略唯一。编号、动作枚举、初始化、遍历顺序不是额外社会动机。先从结论能够被独立证明的简单局面建立首版teacher；复杂多解样本保留作研究/回归，暂不生成强制唯一标签。首轮不默认在多个策略间均匀混合，因为这等于增加了尚未声明的先验；也不默认把各策略下的possible set取并集、favored设undetermined，这会改变B标签语义。

对多解的处理还需下一轮具体设计：如果要覆盖多套策略，必须明确哪些行为模型被允许、参与者如何认识这些模型，并证明所给B/P结论在该范围成立；若规则与可见信息不足以支持确定标签，就返回teacher级别的待定。只跑若干初始化/次序并得到一致结果，属于敏感性检查，不能称为全范围证书。玩家重命名后恢复原程序更新顺序只是本轮定位手段，不是最终解决方案。

T6 推演、执行、逆推使用同一行为机制（拟议首版）：一次审查episode使用同一套经过核验、基于各自信息的完整条件策略；不同回复进入不同分支，不等于执行固定动作序列。每一步行为似然使用这套策略。若后续改为重新求解，须重新定义并验证其真实延续，不能把原根部Q值当作重新求解后的执行收益。强制行动对照须明确do(action)及后续离轨信念规则，不得把强制动作当作关于行动者类型的自主证据。

T7 标签边界（既定原则）：B保留有证据支持的全部可能偏好，favored仅在声明模型下有唯一最高支持时给出具体值；P使用可见belief信息允许的最优动作集合，不强选某个残余并列动作。自然语言定性判断不足以唯一支持动作时不能利用私有数字gold判错。格式错误、求解失败、模型不确定性是不同情况，求解失败不能转成负奖励。没有强制给每个局面生成标签的要求。

T8 不把证明范围扩大（硬验收原则）：原生执行核验收益、独立逆推核验标签、语义变换核验不变性分开记录。稳定最优响应证书不等于唯一解；有信息增益不等于有决策价值；短局终局正确不等于完整长程或人类行为模型已验证。所有teacher机制改动需新版本，原v4轨迹与gold不得混用。

### 四、接下来几轮怎样迭代

第一轮（当前）：审查D1–D8及T1–T8的含义和依据，确定首版能证明的任务范围，尤其讨论多解与信息充分性的处理。产物是此草案和已有例子的依据，不是训练集。

第二轮：根据定下来的契约修改solver；先用D1/D2的人工收益推导、D3/D4的独立终局比较、D6的信息隔离以及D7现有失败源检查。多解尚无语义依据时明确拒绝强标签；不为了提高通过率静默删除反例。对3–4玩家小局可枚举全部玩家置换，不只抽一种反转。

第三轮：将同样的社会关系移到其他现有拓扑和信息布局，补充“变化应影响答案”及“变化不应影响答案”的控制，检查多解拒绝/资源失败造成的覆盖损失，以及B/P之间的连接。若失败暴露任务或契约缺陷，就返回前面修改，不规定必须三轮结束。

进入正式生成的条件：拟纳入的单元有独立依据、solver实现契约且通过针对性反例、未解决样本明确隔离并报告覆盖损失、输入足以支持标签、同语义重命名不改变结论。达成之后再讨论生成规模、划分、奖励、采样与训练实验。当前没有修改solver、启动生成或训练。

## 任务设计与teacher行为契约修订v0.2（2026-09-13）

本节记录用户最新任务定义，并提出teacher与监督精度的讨论方案。与v0.1冲突处以本节为准；“建议/待定”不代表用户已经批准具体实现。本轮仅修改设计记录，不修改游戏、solver、gold或训练配置。

### 一、B与P分别设计（用户确定）

B只有三个任务，不再把证据类型、推演深度或支持强度单独划为任务：

| B任务 | 输入与输出 | 必须覆盖的变化 |
| --- | --- | --- |
| 形成 | 给出相关公开history、公开偏好/候选目录、观察者自己的已知信息，输出指定隐藏preference的possible set与favored | 三、二、一元素；多元素下有favored或undetermined；有区分力与无区分力的行为 |
| 维持 | 已有belief后增加合法history，输出新的set与favored，两字段均不变 | 信息重复、与目标无关、不同候选同样会采取该行为；不能把history变长视为必须改答案 |
| 更新 | 已有belief后增加合法history，输出新的set与favored，至少一字段改变 | 集合缩小；集合不变但favored出现、消失、反转；集合与favored同时改变 |

维持/更新先做辅助式单步题：旧history + 正确旧set/favored + 新增history → 新答案。之后增加连续decision point，由模型先形成，再维持或更新。保留旧history非常必要：set/favored一般不是完整联合后验的充分统计量，仅凭两个旧字段未必能正确累计证据。旧、新history须明确前缀/增量边界，避免重复计入证据。连续题的gold仍由完整证据决定，不能因模型上一步答错而把错误belief当成真值。

若累计权重改变而set/favored均不变，在当前输出定义下仍属于“维持”；支持强度变化可以作为内部审查属性，不能偷偷算作第四类B任务。固定偏好、固定行为模型、精确零概率排除的设置下，新增证据只能维持或缩小possible set；不能为了凑“更新”而设计候选凭空恢复。若以后允许纠正不可靠旧证据或改变行为模型，须另行定义语义。

P题面直接给belief，包括完整/不完整信息、必要联合约束及自然语言支持强弱；不要求先逆推历史才能拿P分。未来investigate产生新观察时，孤立P题也应提供该分支的正确belief更新或明确定义的直接揭示结果；自主B更新与P决策合并留到后续组合评测。

P覆盖一个提案回合、两个提案回合、完整round内的高价值决策。明确一个提案回合包含提案与回复；正常3–4玩家轮转下一个round包含各玩家的提案机会。另行记录learner还剩几次决策，不能把“全体玩家两个提案回合”称为“learner两次决策”。跨度是覆盖维度，不是社会推理价值的充分证据。

需要保留的P场景：即时收益与未来机会的取舍；不可逆commitment/剩余容量；换伙伴或等待；组合补偿；自身收益并列时利他；相同possible set但支持强弱不同；联合约束影响行动；信息变化但最优行为无需变化的控制；何时调查、调查谁/哪个goal及如何使用结果。它们是场景属性，不增设P能力taxonomy。

B/P共同分布维度继续保留3–4玩家、goal数、commitment数量及状态、一个或两个隐藏preference、同一玩家两个隐藏或不同玩家各一个隐藏，隐藏者可以是observer。只能在原生约束允许的组合中取样；存在完美信息题本身没有问题。

### 二、heuristic与teacher的关系（本轮建议，尚未实施）

后续决定：用户已明确排除新增heuristic、有限前瞻伙伴类型及随机非最优行为，见v0.3。以下关于比较有限前瞻伙伴的文字仅保留为讨论历史，不是待执行计划。

社会推理不等于穷举推演。根据对方目标、选择空间及信息采取简洁规则，可能就是正确行为。例如“对方拒绝当前有利报价，可能在保留更好的后续机会”有社会内容；“没有直接披露就一律全集”则忽略了可区分的行为证据。验收应检查关键条件改变时能否调整判断，而不是推理文字长短或是否显式展开全部树。

资源理性研究为“有限计算下使用有效heuristic”提供理论依据，但不能据此断言我们游戏里的两步teacher准确模拟真实人类，也不能从当前难例稀少推断真实社会中高价值推理稀少。生成分布、截止点、行为模型、精确最优筛选、多解和预算失败都可能影响当前样本命中率。

建议拆开teacher的三种职责：

1. 行为生成机制：伙伴在各自信息下如何行动，决定B中的行为证据与P中的互动环境。
2. 标签/评估机制：在上述机制和题面信息下，什么belief有依据，什么决策价值更高。
3. 求解算法：通过枚举、动态规划等计算并核验标签，不要求LM复现同样算法。

“teacher行为就是想教给LM的行为”适用于learner的目标行为，不能直接推广为“所有伙伴必须和标注器一样强”或“LM必须学习solver内部的全树搜索”。若采用有限前瞻或heuristic伙伴，必须声明其决策规则及玩家能知道的内容，并相应重算轨迹、似然及评估。对伙伴的行为建模与learner追求收益的标准可分开。首轮不把多种未声明风格混在同一题，也不把无法解释的solver结果称为人类随机性。

建议先用一套信息边界清楚、可独立核验、覆盖简单有效策略及其必要例外的行为机制建立基线，再比较有限前瞻伙伴。现有“自身收益优先、严格并列后利他、仍并列再随机”的目标顺序保留；搜索深度和行为模型是另外需要讨论的选择。v0.1的统一终局求解是审查方案，不再被当作唯一的社会行为定义。玩家编号依赖、多策略选择、推演与执行不一致等已发现问题仍须解决。

### 三、B硬排除与P精确最优的边界（必须一起讨论）

B的集合形式不自动保证鲁棒。当前possible意味着在声明先验与行为机制下具有正支持；如果假设每种偏好对每个合法动作都有非零概率，则单靠行为通常无法排除任何原本可能的偏好，只能改变favored/支持强弱。贸然给teacher加入全支持随机噪声，可能再次让“总答全集”成为正确默认。反过来，若teacher假设绝对最优而真实伙伴偶尔偏离，硬排除又可能排掉真偏好。

因此首轮保留明确行为契约，在契约下设计成立的排除题；后续扩展有限理性时检查哪些排除仍被支持。不能把低概率无声明地改成impossible，也不能声称局内硬排除可直接迁移到所有真实人类行为。favored负责表达“仍可能但支持不同”，不能恢复成singleton的冗余字段。

P需要区分精确计算价值、要求唯一动作、采用严格最优集合、允许近优动作、提供精确概率这五件事。精确oracle可用于验证差距，并不要求LM输出概率或模仿唯一动作。当前集合奖励方向仍可保留；本轮新增建议是先选择可见信息足以支持、价值差距稳健的局面，再讨论对微小差距采用近优集合或按损失分级的监督。近优阈值及利他次级目标如何保留尚未确定，不能用容差默许牺牲明显他人收益。

自然语言likely等没有跨场景固定的数字含义；现有内部区间只是设计假设，不是人类语言定律。可先使用在较宽合理解释范围内仍有共同好动作的题，或给出更多相关定性条件。若措辞容许的belief会导向实质不同决策，不能用未展示的精确权重强判一个答案；标为需要补足信息/评估标准。不能通过只保留与不确定性无关的简单题来规避全部问题。

动作分布随机性与迁移鲁棒性分别评估。存在多个同样合理的动作时应接受多样选择；给明确差动作加入概率并不自动产生鲁棒性。未来检查语义等价改写、局面结构变化、轻微belief变化及声明范围内伙伴策略变化，才能支撑相应的迁移结论。

### 四、MENU与investigate（设计方向，尚未修改原生动作）

用户要求考虑删除MENU、加入有策略价值的investigate。建议将MENU退出下一版候选机制，旧实验保留作历史证据；不把目前未找到独立信息优势写成MENU在所有局面中都无用的定理。

首个调查候选仍是最小形式：investigate(player, goal)占用当前提案机会，由环境公开揭示一个原本未知的偏好槽，不同时成交，不引入额外的信息奖励。目标合法性、公开/私有观察及次数限制必须进入正式游戏规则；这属于新机制，不能假装已有公开history里原本藏着一条未读记录。环境可核验揭示避免同时引入说谎回复和邀请报价的复杂协议，但它本身只是主动获取信息机制；社会价值需由所获取的他人偏好如何影响后续互动来体现。

调查价值必须在正常3–4玩家轮转及足够真实剩余机会下验收，不能依赖连续安排learner提案。保留中间玩家的全部行动与状态变化。应找到以下合法对照：

- 值得调查：不同结果会改变后续行动，调查后的最优条件计划在计入机会成本后严格更好。
- 不值得调查：不同结果对应同一最佳行动，或虽有收益改善却不足以抵消错过当前交易/终局机会。
- 目标选择：同一局面有多个合法调查对象/goal，其中只有部分信息与当前后续决策相关。
- 结果利用：分别揭示不同结果，正确后续动作随之变化；只调查但忽略结果的策略不能拿到同等收益。

比较应覆盖全部合法不调查行动，不能只拿调查与某个弱OFFER比较。除“有/无信息”对照，还需区分延迟或公开披露本身改变伙伴行为的作用；完整计划价值不能全部归因于learner更新belief。若最小形式不能同时形成有成本的正例与反例，再调整机制，不靠直接奖励调查或筛出大量“一上来就问”的题保留它。

### 五、训练失败对当前设计的约束

避免重演“难题没有有效改善，容易奖励的全集模式主导学习”。这不等于让全部题变成难例，也不能仅用既有失败断言唯一原因是任务太难。首轮从简短但确需利用行为证据的形成题、给正确旧belief的单步维持/更新、给belief且收益差距明确的P题开始，再逐步增加关联偏好、中间玩家及时间跨度。

每个核心例子配关键条件改变的合法对照：能排除/不能排除，需要更新/应当维持，值得调查/不值得调查。容易题也要提供所需核心能力的学习信号；不能只靠公开披露和目录复述拿分。首轮不预定复杂题占比、近优阈值或新训练算法；后续再用实际采样正确率和分任务验证检查学习是否发生。validation interval=10步的既有决定保留。

下一轮先定行为机制及标签语义，再改solver并用上述对照验证。当前未新增gold，未宣称investigate已有正例，也未启动训练。

参考依据：Lieder & Griffiths (2020), Resource-rational analysis, https://cocosci.princeton.edu/papers/lieder_resource.pdf （有限计算与合理heuristic）；Skalse & Abate (2023), Misspecification in Inverse Reinforcement Learning, https://ojs.aaai.org/index.php/AAAI/article/view/26766 （偏好逆推对行为模型错设的敏感性）。文中对本游戏的具体判断为本轮设计分析，不是上述论文的实验证明。

## 设计决定补充v0.3（2026-09-13）

用户基本认可v0.2，并明确以下约束；冲突处以本节为准。本轮只更新设计记录。

1. **统一伙伴行为规则。** heuristic只是对社会推理的概念讨论，本阶段不设计heuristic伙伴、不引入有限前瞻伙伴类型，也不加入随机非最优动作或其他新增behavior/player type。撤回v0.2“随后比较有限前瞻伙伴”的计划。继续保留既定目标顺序：自身期望收益优先，自身严格并列后最大化其他玩家期望收益之和，两层仍并列才均匀随机。这里沿用已有的残余并列规则，不把它扩展为犯错噪声。solver的时间范围仍需修正并验证，不能把已有截断错误当成允许的伙伴风格。
2. **P接受近优动作集合。** 用户同意对价值非常接近的动作放宽答案集合，以缓和难度曲线。具体容差、收益尺度和利他次级判定仍待用原生例子确定。本决定放宽的是learner答案验收，不自动改变生成B历史的伙伴策略或其动作似然；也不要求teacher在近优集合中随机执行。若以后将learner近优行为用于新历史，必须另外定义相应生成机制，不能直接沿用严格teacher似然。
3. **定性belief采用较宽合理解释范围。** 用户同意放宽likely等表达的合理解释；不要求LM恢复隐藏精确权重。解释范围和动作近优容差需一起审查，避免某动作只在范围内一个便利权重下好、在其他合理权重下损失很大，却仍被作为无条件正确答案。首批优先采用共同近优动作明确的局面；具体区间及容差尚未设定。
4. **investigate每局最多一次。** 在已有“占用当前提案机会、揭示一个未知偏好”的最小候选上增加次数限制。本记录暂按字面理解为整局总计一次，属于机制解释，尚未实现；不默认为每位玩家各一次。该限制应在正式规则、可见状态和合法动作中一致体现。四类对照（值得调查、不值得调查、目标选择、结果利用）保留，并在其中加入“现在使用还是留到后续”的时机对照。一次性额度增加机会取舍，但本身不证明不会一开始就调查；仍需原生收益证明晚用或不用更好的局面。正常轮转下其他玩家的行动及对共享额度的使用也必须按同一规则进入计划，不能为learner隐去竞争。
5. **首批例子验收标准确定。** 短、合法、收益关系清楚，并确实需要利用他人目标或行为证据。降低长度和同时相关因素数量，保留关键社会关系；与公开披露/目录读取控制分开统计。B继续只有形成、维持、更新；P直接给belief。先建立少量可独立推导的合法对照，修改并验证solver、迭代后再生成正式监督与训练。

MENU退出下一版候选机制、investigate替代的设计方向保留；当前没有删除或新增原生动作，没有修改solver、gold或训练。

## 实现进展与双层近优评分决定（2026-09-14）

本节补记上一轮实现与本轮用户决定，更新v0.3中的历史实现状态。用户已明确允许：learner在自身收益并列时，对其他玩家收益之和的小幅损失也可以采用评分容差。允许这一机制不等于已选定某个数值阈值。

### 评分含义与实现

- 自身期望收益容差与他人期望收益之和的容差分别设置，不把两者相加为一个总分。对每种允许的belief都检查自身收益损失；在自身收益严格并列的比较上，再检查他人收益损失。
- 例：自己的期望收益都为2，其他人收益分别为1.00、0.98、0.50。若利他容差为0.05，前两个动作可以都算对，第三个仍错。0.05为解释和审查用的示例值，尚未被指定为正式训练阈值。
- 放宽learner答案验收，不改变teacher/伙伴严格的自身优先、并列后利他、仍并列后均匀随机规则，也不改变B历史的行为似然。
- `social_p_qualitative.robust_actions`与`terminal_task`已有两层参数；本轮将其接入`planning_review_task`及两份设计审查脚本的参数扫描。保留零容差以重放原严格评分和作对照，正式非零阈值仍待由原生决策差距确定。

### 本轮验证

`new/local_data/social_runs/p_dual_tolerance_audit_v1/`保存完整审查任务、变化项与摘要。使用2个原生fixture、4档定性表达、4档自身容差及4档利他容差，共128种审查配置，不是128个独立游戏。利他容差扫描0、0.05、0.1、0.25：前三档各有16/32配置获得共同可接受动作，0.25时为21/32。5项答案集合扩大，所有配置的伙伴策略和原生收益表均与利他零容差时相同，原可接受动作集合没有因放宽而缩小。

这里0.05和0.1未改变这两类fixture的答案，不代表小容差没有价值；0.25扩大集合也不自动意味着应采用0.25。当前只是对收益差距的敏感性检查，不能靠提高容差来替代高价值决策题的设计。

12项P相关测试通过，包括允许小幅利他损失、拒绝明显利他损失、拒绝用大量他人收益补偿超出容差的自身损失、检查整个belief解释范围，以及伙伴行为不随learner容差变化。

### 上一轮实现及仍待解决项

新增`social_terminal_teacher.py`作为版本化审查实现：新变体不接受MENU，investigate由所有玩家共享整局一次额度，占用当前提案回合并公开揭示一个偏好；普通动作沿用原生状态转移。求解计算到真实终局，执行同一条件策略。默认同步更新避免玩家依次更新带来的编号优先；显式有序更新只用于诊断，不作为失败后的静默回退。

`social_design_followup_v1/`中的9个审查配置有8个求解成功、1个失败；成功局面已逐边重放原生转移并核验全部终局价值。包含B形成、维持、集合更新、集合不变但favored更新的条件标签，以及P直接给定belief的审查输入。审查覆盖了同一玩家两个隐藏偏好、两个玩家各一个隐藏偏好的配置；包含observer隐藏偏好的该次配置求解失败，不能算作覆盖成功。

已发现的调查优势候选在遮去learner直接读取的揭示结果、保留其观察后续伙伴行为的能力后，仍能得到相同收益。这尚未证明直接读取结果有必要，也不排除通过伙伴后续行为间接获得信息；不能把这些候选当成已完成“learner利用新增信息”的证明。更长且动作更多的局面还遇到了公共树节点预算不足。

策略唯一性仍未证明，一些初始化会不收敛；这些失败被保留，不生成正式gold。上述产物均为`training_ready=False`，尚未接入生产runner、生成正式训练集或启动LM训练。

## Teacher选择语义澄清与并行outcome计划交接（2026-09-14）

用户明确：我们要用求解过程中选中的某套策略作为teacher，不把声明的理性规则视为能唯一决定所有行为的真理。因此撤销“必须证明策略唯一、或所有初始化均成功且一致才能接受默认teacher标签”的要求。之前记录中的唯一性缺口不再作为独立阻塞项。

### 当前验收标准与实现

新版本`social-terminal-selected-policy-v2`将固定选择过程作为teacher定义的一部分：默认从均匀选择开始，同步更新所有玩家，得到稳定的完整终局条件策略；之后整局按这套策略执行并据此计算行为似然和B/P标签。重复运行应得到相同选择；不能根据观察到的真实隐藏偏好、题目的目标答案或事后收益挑选策略。

证书新增`label_reference=selected_contingent_policy`、`uniqueness_required=False`、完整上下文与策略的`policy_sha256`及逐信息集隔离检查数。不同初始化/有序更新被标为诊断策略；B/P审查题生成器禁止将这些策略混入默认teacher标签。替代初始化不收敛不再否定默认teacher已验证的标签；默认程序本身不收敛、预算不足、信息泄露或执行/似然不一致仍然不给标签。

`new/local_data/social_runs/selected_teacher_contract_v2/audit.json`核验了favored更新、微小调查优势、延迟目标调查三个已有局面：各自重复求解的完整策略指纹一致；相对v1，根部动作、概率和收益不变；原生逐边执行及终局价值核验通过。本次改变的是teacher定义与验收边界，没有靠更换目标动作改掉已有结论。标签仍只说明所选teacher的行为，不声称适用于所有理性策略或真实人类。

### Investigate继续调查

`new/local_data/social_runs/investigation_mixed_selected_v2/`增加了16个配置：另一个玩家的即时目标隐藏偏好与延迟多人目标隐藏偏好组合，并比较短局及learner还有下次提案机会的跨度。4个求解成功，没有新增严格调查优势；12个失败，其中较长的8个均超过30000节点预算。失败不等于调查无价值。调查结果仍保持公开、整局共享一次，未引入私有揭示或新伙伴behavior。

下一步仍需检验调查→新增信息→learner后续决策改善的因果路径，区分直接读取结果与从后续伙伴行为间接推断；同时处理长局完整树的规模问题。正式样本生成和训练仍未启动。

### 可复制到独立outcome self-play对话的背景

项目在`/Users/bruce/MARSHAL`。现有社会推理游戏使用原生多人协商、不可逆commitment和由偏好/目标达成情况计算的收益。B/P细粒度监督正在另一对话迭代：B为形成、维持、更新，输出possible set与favored；P直接给belief，允许自身与利他收益的独立小幅评分容差。目标顺序为自身收益优先、严格并列后利他；这些监督评分容差不自动定义self-play的outcome reward。

新版审查原型禁用MENU，加入整局共享一次、消耗提案回合并公开揭示一个偏好的investigate；信息价值尚未验证充分，也未接入生产runner。Teacher采用固定求解流程选出的条件策略，监督不要求博弈解唯一。原B训练曾过度学会“无直接披露就保留全集”的模式；不能把当前审查产物或旧gold直接视为新环境的可用训练标签。

新对话单独制定outcome reward self-play训练计划，先检查实际训练入口、可用环境版本、奖励实现、对手配置、资源和评估，不依赖B/P gold。两条工作线分开命名实验与输出目录。B/P线程正在修改`training/b_sft/social_terminal_teacher.py`、`social_p_qualitative.py`、`debug/audit_social_design_*.py`及本记录；另一线程可读这些文件，但应协调任何重叠修改。当前仅要求制定outcome计划，未授权启动训练或上传数据。

## Investigate信息价值证明与self-play机制交接（2026-09-14）

用户要求重点解释所选teacher语义，并至少证明investigate具有实际策略意义，以便独立outcome self-play工作线推进。

### Teacher答案的含义

环境规则定义合法动作、信息公开方式、承诺变化和终局收益。Teacher则定义参考玩家面对各自信息时怎样行动；固定求解流程选出的是完整条件策略，不同观察进入不同分支。生成历史、计算行为似然和评判P行动都使用同一个版本与策略实例。因此B的possible set表示“在该teacher机制下仍能解释观察的偏好”，P的gold表示“在给定belief及该伙伴机制下的最优/允许近优动作”。它们不宣称覆盖所有理性策略，也不能直接作为自由LM self-play历史的gold。

自身收益优先、并列后利他、仍并列后均匀随机，以及信息隔离和求解稳定性要求仍保留。允许teacher选择一套策略，不意味着任意未验证的策略都可打标签。默认模型失败仍不生成监督；其他初始化的失败属于模型敏感性诊断。

环境版本现在独立标记为`social-public-investigate-v1`，teacher版本为`social-terminal-selected-policy-v2`。调整teacher不等于改变游戏物理规则或self-play的合法动作集合。

### 已核验的原生对照

脚本：`training/b_sft/debug/audit_investigation_value.py`。
产物：`new/local_data/social_runs/investigation_value_proof_v2/`（v1保留为本轮中间记录）。

| 对照 | P0调查的期望终局收益 | 对照收益 | 说明 |
| --- | --- | --- | --- |
| 有用调查 | 1/3 | 所有普通动作最高0 | 计入被占用的当前提案回合 |
| 同样消耗回合和额度，但不给信息 | 1/3 | 0 | 对无信息干预后的剩余局面重新求解；单独看此项不声称是固定策略的因果估计 |
| 调查对象选择 | 相关目标1/3 | 无关目标0 | 无关目标已达成，隐藏偏好独立且只贡献相同的常数收益 |
| 最后一个提案回合 | 0 | 直接成交1 | 相同偏好与未承诺状态，合法改变剩余机会，调查不再划算 |

这组例子不含MENU，也没有信息量奖励或调查即时成交。正常三玩家轮转、原生合法提案与响应、整局共享一次额度都保留。目标选择变体通过合法setup先达成额外常数目标，随后仍有P0/P1/P2各一次提案机会；setup不作为行为证据。

### 明确的信息作用路径

关键正例有三个玩家各一个可承诺动作A/B/C，四个goal为AB、AC、BC、ABC。偏好为：P0=(want,avoid,avoid,want)，P1=(want,want,want,隐藏want或avoid)，P2=(avoid,neutral,want,avoid)。P1两个类型初始等支持。

P0调查P1对ABC的偏好后，P1向P0提议AB并成交。之后P2面对同一个AB已达成、C未承诺的最后提案局面：

- P1想要ABC时，P2自身收益在保留AB和推动ABC之间都为-1；其他玩家收益之和分别为2、4，因此P2选择推动ABC，P0最终收益0。
- P1想避免ABC时，P2自身收益仍并列，其他玩家收益之和也都为2。按照既定残余并列均匀随机规则，三个最优动作中两个最终保留AB、一个实现ABC，P0期望收益2/3。
- 两个类型等支持，因此调查后P0期望收益为(0+2/3)/2=1/3。

在原完整策略中做逐玩家可见性干预：只让P0不能直接读取调查结果、仍能观察后续行为，P0收益保持1/3；只让P2不能读取结果并重新计算P2针对其他固定策略的最佳回应，P0收益降为0。P1始终知道自己的偏好。由此定位到的路径为：**P0主动公开信息→P2掌握的信息改变→P2后续策略改变→P0获益**。这不是“调查者必须自己读取结果并改进计划”的证明，但已经证明公开信息行动在社会互动中的工具价值。

该正例依赖原定的利他并列与残余并列随机规则。它没有增加新player type或随机犯错机制；也不保证自由LM self-play会保持同一行为分布。Outcome工作线应通过实验检查是否学会利用该机会，不能把参考teacher下的1/3视为任意对手下的保证收益。

收益使用Fraction重算，并逐边重放原生状态转移、独立计算goal合取与终局效用。核心正例和目标选择变体各检查全部6种玩家重命名，根部全部动作价值与选择概率按映射一致。

### Self-play接入边界

已为`InvestigationRules`补充不调用solver的执行接口：

- `step(node, action, realized_world=...)`：调查答案由环境私有的真实偏好组合确定，agent仅提交`INVESTIGATE`的player/goal；普通动作沿用原生执行。整局额度、回合消耗与公开事件都实际更新。
- `terminal_payoffs(node, realized_world)`：按真实世界和最终目标达成状态返回各玩家收益，不使用teacher Q、belief或近优评分。
- `public_game()`与`node.state.public_state()`：提供机制规则、剩余调查额度和公开揭示事件。Self-play观察应另从真实世界只提取当前玩家自己的偏好，不能公开完整真实矩阵。底层Endgame的spec经过隐私净化，不能用其中的零偏好矩阵代替真实world计算奖励。

执行测试会禁止调用`TerminalWindow.solve`，仍能完成调查、报价、接受、终局并得到真实收益(1,1,-1)。原生合法但不符合teacher策略的动作也能执行，允许self-play探索，不用B oracle的行为兼容性过滤轨迹。

当前结论：机制已具备可核验的存在性正例、成本反例、目标选择对照和具体信息作用路径，可以保留并进入outcome self-play试验的环境接入阶段；无需等待全部B/P监督问题解决。生产runner/训练框架的观察、动作schema和奖励接线仍由outcome工作线核对，当前没有启动训练。审查产物的`training_ready=False`表示它们不是正式B/P训练集，不表示调查机制被判无效。

## 小规模渐进课程落地与验证（2026-09-14）

用户同意：先用少量核心局面反复练习，分阶段增加变化；B/P分开；调查结果利用先于是否调查；不追求无必要的长程；自身和利他总收益容差暂各取0.1并作敏感性检查。难度等级是待模型采样验证的设计假设，不能用solver成功代替可学性证据。

### 本轮改进

新增`social_bp_curriculum.py`生成选定teacher下的小型课程，`social_bp_curriculum_eval.py`提供题面导出、原生工具调用评分、分组诊断、分B/P分阶段的取题函数及显式HTTP推理入口。旧`social_b_curriculum.py`所用旧oracle与“最后一条行为已经足够就排除”的筛选没有被混入新课程；新课程直接使用终局teacher，保留短行为更新。`belief_examples`现在允许从正确初始belief出发，增加第一个事件后作维持/更新。

- B：形成、辅助维持、辅助更新分别标记；覆盖possible set为1/2/3，多元素favored、集合不变而favored改变。连续序列使用模型自己的前次输出，不注入前次gold。短题不要求证明多步历史缺一不可。
- P：完整belief短局、不完整belief、结果利用、调查决策分别标记。当前多回合题直接给出等支持的完整联合候选，以及公共/自身视角；不把不等支持posterior伪装成等支持，也不把隐藏数值权重变成模型必须猜的答案。已有likely区间终局证书仍单独保留，一般定性多回合输入尚未完成。
- 调查：不再把“遮住直接结果且允许从后续行为推断后仍必须损失收益”作为所有题的筛选门槛。严格信息作用诊断和教学用的结果对照分开记录。
- 短程：原生正常轮转、真实终局，保留中间玩家。调查结果利用的新例只求解最后一个提案回合，前面的合法动作明确作为setup。
- 容差：learner自身期望收益0.1、严格自身并列时其他玩家收益之和0.1；扫描两层各0/0.05/0.1/0.25，伙伴策略不随评分容差改变。
- 取题：B/P分开；先覆盖各能力分层再补充抽样。已全对的题保留低频复习，全错核心题不自动删除，诊断建议补更短过渡题。全部合法动作都得分的P题仅作格式练习，不进入默认能力训练采样。每次重复题目需要新采样回答，不能重放旧回答冒充独立GRPO样本。
- 验证：保留每10步验证设置；分别统计每类全错/全对/混合组、实际奖励是否有差异、格式错误、误排除和多保留候选。漏样或服务失败的组标记不完整，不当作全错。新工具只提供课程与取样接口，尚未把新格式接进旧optimizer入口。

### 已发现的更直接结果利用题

三个玩家、P0两个commitment选择A/B，P1一个X，P2一个C；目标为AX、AXC、BX。P0都want；P1对AX隐藏want或avoid，对AXC neutral，对BX want；P2对AX want，其他neutral。所有候选均保留正偏好，各goal有非neutral偏好，使用原生ALL_OF目标和每次每人最多新增一个commitment。

正常轮转`[2,1,0,2,1,0]`。给定合法setup：P2与P1成交，仅承诺C；P1 PASS；P0调查P1对AX的偏好；P2/P1各PASS。最后轮到P0，选择向P1交易：

| 已公开的调查结果 | 选择AX的P0终局收益 | 选择BX的P0终局收益 | 可接受选择 |
| --- | --- | --- | --- |
| P1 want AX | 2，AX和AXC同时完成 | 1 | AX |
| P1 avoid AX | 0，P1拒绝 | 1 | BX |

两题物理状态、观察到的行为、P0自身偏好相同，揭示结果及相应给定belief不同；在两层容差所有16个组合下，可接受动作集合均不相交。没有增加行为类型、随机错误、特殊收益权重或私有查询。`TerminalEpisode`补充合法公开调查setup，并在选定剩余局面的teacher前剔除与公开答案不一致的world。

这是“调查者利用已有信息作不同后续选择”的教学对照，前面的查询及PASS不是本轮证明的teacher自主最优行为；不能拿它宣称已验证主动查询的完整因果链。主动查询有正收益、无关查询无收益、最后回合不值得查询的机制证明仍见上一节独立审查。

### 产物与实际验收

当前数据：`new/local_data/social_runs/bp_short_curriculum_v5/`。v1–v4保留中间诊断，不能把各轮累加算作独立样本。首轮曾有3个配置求解不收敛，无标签；最终小型课程选择14个成功配置，并不代表任意随机配置都可解。

- 14个配置，逐边原生转移和终局收益核验通过；187个B、182个P检查点，总369题，而不是369个独立游戏。
- train 249题、同结构新配置validation 111题、额外结构validation 9题。相同source的全部检查点在同一split；结构验证与train的goal topology分离。它们都已被开发者查看，不是盲测集；结构验证目前只有P，完整B结构迁移覆盖仍不足。
- B有13条连续序列（8条train、5条配置validation），1组同旧历史下维持/更新分支对照。P有1组已证实需要根据结果改变选择的调查者对照。其他调查后题仅记为练习，不默认声称信息不可忽略。
- 最终50个P检查点全部合法动作都可接受，已排除出默认能力训练采样。B“目录全集+undetermined”基线在70/187题正确，保留这些合理维持题，但各能力分层取样，避免靠总体平均成绩掩盖行为推断失败。
- 在本批182个P检查点上，两层同时0.05或0.1均未扩大严格答案集合；两层0.25扩大2题。新结果利用对照在0.25仍有效。因此0.1目前是保守试验值，尚无证据表明它已经降低这批题的学习难度。
- 33项相关单元/集成测试通过。369题均通过原生工具schema→gold提交→集合reward=1的往返检查，题面未包含teacher Q、答案集合、策略指纹或teacher-only权重。最长请求10905字符；尚未用指定模型tokenizer测量token长度。

题面与取样计划：`new/local_data/social_runs/bp_short_curriculum_requests_v2/`。默认每题8个独立回答作分组诊断，先按能力层抽小量题；连续B任务另列，并保留实际前次模型回答。题面包含游戏规则与数值/偏好映射，不把裸向量当作足够的游戏说明。

复现CPU生成：

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.social_bp_curriculum --out <fresh-data-dir>
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.social_bp_curriculum_eval --data <data-dir> --out <fresh-request-dir>
```

给定用户指定的模型与服务后，显式小规模推理（没有优化器更新；不启动服务器）：

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.social_bp_curriculum_eval --data <data-dir> --out <fresh-probe-dir> --base-url <endpoint> --model <model> --group-size 8 --per-stratum 1
```

本轮未调用LM或启动训练，尚待用户指定推理endpoint/model。下一步依据实际分层采样结果调整题面、过渡题和难度，再决定optimizer数据导出；不因teacher通过就宣布课程已经可学。3–4玩家变化、多隐藏布局和更一般的自然语言belief保留为后续扩展，不要求第一批同时完成全部组合。


## 首轮真实 B/P 分层采样分析（2026-09-14）

本轮是 Qwen3-4B-Instruct-2507 基础模型采样，没有参数更新。32 道开发诊断题（19 B、13 P），每题 8 次独立生成，temperature=0.8，max_tokens=1024，无 retry。远程 256 次请求全部完成，无截断或基础设施失败；下载后核对请求包指纹，并用本地 v5 课程标签评分。按能力分层选择的小样本不是总体准确率或盲测泛化评估。

| 任务 | 正确回答 | 正确率 | 8 次全错题 | 有对有错题 | 8 次全对题 |
| --- | --- | --- | --- | --- | --- |
| B | 24/152 | 15.8% | 13/19 | 6/19 | 0/19 |
| P | 34/104 | 32.7% | 8/13 | 1/13 | 4/13 |

共有 21/32 题没有采到 reward=1，只有 7 题同时采到正确和错误回答。全错组可能仍因格式分产生奖励差异，不能把这种差异当作社会推理能力的有效正例。0/8 不能证明题目不可学，但不支持直接扩大 GRPO 训练规模。

### B：基础表述理解与行为推断都有问题

- 4 道更新题共 32 次回答，全部错误；包括 possible set 更新和集合不变的 favored 更新。
- 68/152 次回答保留原目录候选集合；109/152 次输出 favored=want，只有 1 次 neutral、1 次 avoid，其余 41 次 undetermined。这既有全集捷径，也有缺乏证据的 want 偏置，不能只诊断为一律全集加 undetermined。
- 题 `00b6508c25cb97472225`：目录三行第一项分别是 1、0、-1，某回答却声称查询的 goal 0 在三行中都是 1。这是可直接核对的数组/目标对应错误。
- 题 `6674abd051ee239f94a3`：正确答案为 avoid 单元素集合；8 次都保留全集，理由未用行为排除候选，部分无依据地认定 want 更受支持。
- 题 `1cd638f59100c9cb5395`：新行为应使 favored 变成 avoid，8 次均保留旧的 undetermined，理由仍停留在目录有两种可能。

### P：动作选择偏置强，调查后的信息利用尚未成功

64 次提案回答中 PASS 39 次、INVESTIGATE 24 次、OFFER 仅 1 次；其余 40 次是响应决策（ACCEPT 26、REJECT 14）。95/104 次 P 回答没有普通正文解释，completion token 中位数仅 22，未触及输出上限。缺少正文不等于没有内部计算，但这些输出没有提供可检查的推演依据。

全部 24 次具有合法调查动作的回答都选择列表中的第一个 INVESTIGATE，来自 3 道题。其中两题各 8/8 正确，另一题 0/8。一个正确题同时允许 PASS/OFFER，另一个正确题的调查目标恰好排第一。因此，调查题上的得分不足以证明模型会比较信息价值和机会成本；这批样本已经显示用户担心的“能调查就调查”倾向。

最关键的调查者结果利用对照，两题各 0/8，总计 0/16：`d551ca1ae5a7615e48e5`（want）和 `770930a4fd0e99a40d5f`（avoid）。模型共选 15 次 PASS、1 次错误 OFFER，没有随调查结果选对交易。该对照此前已由 solver 验证在全部 16 组双层容差下答案集合不相交，失败不能解释为答案边界太窄。它检验利用已有调查信息，不替代主动调查价值的独立机制证明。

### 格式与语义分开

远程摘要的 256 次 native submissions 仅表示获得可解析的原生工具调用，不代表 schema 或答案正确。本地严格评分发现 B 5 次格式失败、P 14 次格式失败。P 的 14 次均在 PASS 中多填了不允许的 `partner_id: null`；即便只为诊断去掉该字段，这些 PASS 仍然不是关键结果利用对照的正确动作。因此修提交格式必要，但不足以解决能力问题；本次未事后放宽评分或改写原始回答。

### 下一轮应先解决什么

1. 先减少题面解码负担：偏好明确绑定 player/goal 名称，避免裸数值数组与重复的大块状态；清楚区分当前提案者、待回应提案、已经生效的承诺和剩余轮次。必须保持可见信息、联合约束与 teacher 规则不变，不能把 gold 或隐藏世界泄露到题面。
2. 明确 P 的提交协议与简短理由要求，原样提交一个合法动作，PASS 不带额外字段。用原题对照重新采样，区分表述/协议改善与更改任务难度；有正文也仍要检查理由是否真正利用他人偏好。
3. 对仍然全错的核心行为推断、更新和结果利用题补更短且合法的过渡实例；保留原核心题作验证，不能因全错自动删掉，只留下易得分题。先检验核心类别能否出现正确/错误混合组，再决定接入 GRPO；后续训练保持每 10 步验证。

这次支持“需要先改进可学性与题面”，不支持宣称新一轮训练发生退化，也不否定此前已验证的 investigate 机制价值。当前没有启动后续训练或采样。

产物：同目录 `samples.jsonl` 是原始返回，`scored_samples.jsonl` 是逐条本地评分，`local_diagnostics.json` 是分组/分层诊断，`behavior_audit.json` 是动作与回答模式统计。远程来源：`/raid/chenjiahao/mas/outputs/bp_short_sampling_r1/visible_probe/probe`。

操作约定：用户已明确要求恢复“助手提供上传及运行命令 → 用户执行 → 助手下载分析”；停止 Luna 远程操作，不再委派子代理运行服务器任务。远程模型服务未关闭。


## 对首轮基础模型采样结论的修正（2026-09-14）

用户指出：读错偏好数组可能属于任务难度，偏向 PASS/INVESTIGATE 也可能通过正确训练点改善；基础模型难题 0/8 不代表不能 GRPO。应允许在简单题上学习后向难题迁移的课程路径。接受该纠正：上一节“先检验核心类别出现混合组，再决定接入 GRPO”不能作为启动课程训练的硬门槛。当前采样只反映初始表现，没有检验训练后的迁移。保留难题作为每 10 步的分层验证，允许从能够产生有效奖励差异的简单社会推理题起步；用训练曲线检验是否从读题/单步推断迁移到更新、规划与信息利用。若易题进步而核心类别长期不动，再据证据调整过渡题或其他训练方案。题面简化是可比较的干预，不是已经证实的必要修复；本轮不因此更改游戏标签、启动远程任务或要求先达到基础模型准确率门槛。

调查额度来源澄清：用户最初要求“每局就一次”，助手在本文件原记录中明确写作“暂按字面理解为整局总计一次，属于机制解释”；随后实现为全体共享一次。该共享范围来自设计解释，不是 solver 推导的必要性，也没有通过与每人一次的对照证明更好。共享额度会额外引入玩家之间的额度竞争与公开信息外溢；应与原本的回合机会成本、同一玩家的调查时机选择分开理解。当前保留既有实现，解释不自动构成规则变更。


## 调查额度与真实偏好生成分布重新对齐（2026-09-14，设计讨论）

用户建议将调查改为每位玩家每局最多一次；公开还是私有尚未决定。将每人一次作为下一版额度目标；本轮仅核查与记录，尚未修改当前共享一次的运行代码或重新生成 gold。已有共享额度下的证书、数据与基础模型采样均保留原版本含义。平局处理得到用户确认，不变。

真实生成器核对：`third_party/negotiation_benchmark/src/benac_p/generator.py` 的默认 preference_probs 按 WANT/NEUTRAL/AVOID 为 (0.4,0.2,0.4)，先逐格抽样，再拒绝任一玩家没有 want、任一 goal 全体 neutral 的矩阵。因拒绝采样存在约束，最终合法配置分布不是无条件独立边际，也不是任意候选等权。具体实验可配置概率，不能将默认值当作所有历史实验的实际参数。

当前手工公开类型目录及默认等权先验是额外的审查场景设定，不能直接称为上述随机生成游戏的原分布。内部枚举离散隐藏配置本身没有问题；问题在于任意缩小支持、改变权重，并把目录当作玩家知道的限制。下一版应考虑从真实生成分布及公开信息/自身偏好推导联合支持和条件权重；生成规则中的跨玩家限制不能硬拆成独立玩家目录。为开发者筛题而采用的条件不能自动成为玩家的公共知识。

可保留的课程设计路线：从合法随机游戏出发，在明确的教学观察规则下公开部分偏好、先只隐藏 1–2 个格子；由真实生成规则和已公开信息计算所有相容配置（原始最多 3 或 9 个，再扣除非法组合），无需另加任意目录。逐步扩展隐藏格子。完整随机信息设置另作后续迁移检验，不能声称局部披露课程与其完全同分布。若某些隐藏值只因合法性规则被排除，应与行为证据导致的排除分开统计。

可见性建议（尚非用户决定）：若优先检验调查者获得信息并改善自身后续规划，优先考虑结果私有；调查动作、目标与额度使用可公开，答案只由调查者接收，被调查者原本知道自身偏好。公开结果机制则同时包含改变其他玩家知识及行动的路径，也有价值，但不能混称为调查者自己使用信息的证明。私有方案不能只隐藏 prompt 文本：当前 solver 将揭示结果写进公共历史并全局筛世界，需要新增逐玩家观察/信息集，使未见答案者不能直接条件化于真值，同时允许其从后续公开行为学习。本轮不宣称该支持已实现。


## 两阶段的数据构造边界（2026-09-14，用户明确澄清）

用户区分 B/P 细粒度监督和 self-play outcome reward 两个训练阶段：第一阶段允许手工构造教学游戏残局、采用短 horizon，并主动调整教学目标与难度曲线；第二阶段必须按正式游戏生成机制产生真实随机对局，不允许将手工教学残局或人为指定的有利轨迹作为 self-play 训练分布。此决定优先于上一节要求教学候选必须来自原随机生成分布的建议；该建议不再是 B/P 教学阶段的必要条件。

B/P 阶段可以构造有限偏好目录、明确先验/支持、公开信息、合法残局与剩余轮次，条件是题面与 teacher 使用同一套声明设定，状态和历史满足游戏实际转移规则，标签针对指定 teacher 经验证成立。调整难度可以改变隐藏量、证据长度、相关目标数、规划跨度与动作收益差距等，不改变“形成/维持/更新”和“基于给定 belief 规划”的核心目标。必要时用合法 setup 提供起点；不得将强制 setup 动作当作自主行为的推断证据。简单题可以启动课程学习，难题初始 0/8 不是训练禁入条件；每 10 步按能力分层检查简单题学习是否迁移到更新、规划和信息利用。

Self-play 阶段按最终约定的正式环境与随机生成规则开局，各玩家依据实际可见信息自主行动，环境计算真实 outcome reward；不植入指定配合行为、正确中间 belief 或参考 solver 的最优轨迹。正式生成器原有的合法性拒绝采样属于游戏规则，不等于人为捏造。教学目录与 teacher 的行为假设不自动成为 self-play 的环境约束；尤其不能将教学目录支持或 teacher 的零似然排除直接套到自由 LM 历史。教学标签正确性和训练后的随机对局迁移能力分开验收。

调查额度每人一次的方向保留，结果私有/公开尚待最终确定；本次澄清不视为确认私有结果，也未修改运行代码或启动训练。


## 私有 investigate 研究进展（2026-09-14）

已暂停课程改进，研究结果见 `new/local_data/social_runs/private_investigate_feasibility_v1/analysis.md`，可复现审查脚本为 `training/b_sft/debug/audit_private_investigation_feasibility.py`。核验仅调查者读答案时固定末轮决策的期望收益从 1 提高到 1.5，以及最后一轮查询收益 0、普通动作最佳 1 的成本反例。未证明计入此前回合成本和普通报价的信息作用后查询具有净优势，也未实现一般私有 solver。下一步先实现跨私有答案分支的信息集绑定及每人一次额度，再验证主动调查、目标选择、等待时机。现有公共规则和旧 gold 未修改；答案私有/目标公开目前为待确认方案。


## 私有调查教学难度的进一步澄清（2026-09-14）

用户指出私有 investigate 是强信息动作：在单个关键隐藏偏好、尚有后续行动机会等简单局面中，先调查可以是直接的最优策略；允许这种 trivial 情形作为低难度教学，不要求每道题都证明复杂的信息取舍。允许构造 investigate → 收到私有结果 → 根据结果报价的短 B/P 教学链。继续保留两阶段边界：手工教学残局不进入正式随机 self-play 分布。

研究验收修正：低难度题的标签需要在声明规则下正确，但不以“调查必须严格胜过所有替代策略”作为全部训练题的入选条件；若调查与普通动作并列或在既定容差内，P 接受集合须包含相应动作，不能为了强化调查强行排除其他正确选择。需要声称主动调查有独立净价值的机制证书仍须比较全部合法替代续局。复杂取舍对照作为后续难度与迁移验证，不能阻塞基础教学题。

难度可逐步引入：一个关键未知且有后续报价机会；多个未知但只有某个影响当前决策；答案无法改变最佳行动；其他玩家下一步公开行为可能免费提供证据；等待新公共状态再选调查目标；交易机会/承诺变化造成真实机会成本；多个相关未知、一次调查仍不能得到完整信息。多隐藏并不自动意味着调查无价值，要检查调查后最优决策及剩余不确定性；余下未知可能恰好与行动无关。始终保留全部残余并列最优动作及已有 learner 近优容差。

用户提到“调查已公开 goal”作为可能的低价值选择。当前实现只允许目录中仍有多个值、未被直接公开揭示的其他玩家偏好，该动作当前不合法。若要把它作为合法但零信息收益的教学负例，需要明确允许冗余查询并照常消耗回合和个人额度，环境与 solver 的合法动作必须同步修改；本轮仅记录该规则选择，不默认为已批准扩展合法目标。公开的是某玩家对某 goal 的偏好，goal 本身描述通常已公开。

短链中的“调查完直接 offer”按 learner 的下一次决策理解；正常 3–4 人轮转的中间玩家仍须保留，从监督起点后的自主动作不能强制 PASS。末轮调查不会给同一玩家留下报价机会。B 题可以监督收到私有事实后的更新、后续维持；行为逆推训练仍需独立覆盖，直接读取调查答案不能取代根据行为推断。P 继续直接给当前 belief，让其计划未来信息与行动，不要求为了答 P 先重建当前 B。

下一步私有 solver 的必要能力不变：每玩家个人额度、逐玩家可见记录、跨未观测答案分支的信息集绑定、与真实行为机制一致的更新及价值计算；不引入随机假答案、调查失败概率或新伙伴行为类型来人为制造难度。本轮没有切换运行规则或新生成训练数据。


## 私有、每人一次调查已实现（2026-09-14）

用户进一步明确：“调查错了”是选择了不值得调查的目标，不是获得假信息；简单报价可直接提供偏好证据，目标收益重叠/相关时回应不充分揭示偏好，可以放在更难课程。本轮按此实现私有参考环境与 solver，详情见 `training/b_sft/PRIVATE_INVESTIGATE.md`。

新增 `social_private_teacher.py`：每人一次、目标公开/结果私有、允许冗余已知及无关目标、答案始终真实。公开动作树不按私有结果分支；信息集按公共历史、自身偏好及本人的查询结果划分；保留正常轮转和全部原生动作。新环境版本为 `social-private-investigate-per-player-v1`，teacher 为 `social-private-selected-policy-v1`，旧公开版本未覆盖。请求构造按明确 game variant 使用对应规则，私有题不再带旧“全局共享/答案公开”说明。

实际生成 8 个开发教学检查点（B 5/P 3），覆盖私人答案更新、未收到答案者维持、从后续公开报价更新、按答案改变交易、末轮不查；原生转移与收益重算、gold 工具提交评分通过。结果见 `new/local_data/social_runs/private_teaching_v1/`。5 项新测试连同 17 项既有相关回归，共 22 项相关测试通过。无 LM 请求、远程操作或训练。

正常轮转的完整查询起点仍有困难：一个更小案例 56,259 节点、8 次更新收敛，但 11 个根动作全并列，无动作选择奖励差异；原双选项残局先超 80,000 节点，再在 300,000 节点/50 秒预算下超时，失败无标签。这些是数据区分力和求解规模问题，不是基础模型训练禁入门槛。已输出短题采用明确合法 setup，不宣称查询与中间 PASS 是 teacher 自主最优行为。生产 self-play runner/optimizer 未接入新版本，后续不能把教学数据和目录搬进随机 self-play。


## 两人最小教学研究与全量问题清单（2026-09-14）

用户允许 B/P 教学进一步缩至两人、较少 goals/commitments；希望逐项按能力从易到难设计，self-play 随机规则不变。已新增 `debug/audit_minimal_teaching.py`，产物 `new/local_data/social_runs/minimal_teaching_v1/`。两人、两目标、三 commitment 槽位下核验 11 个实例（B 6/P 5），单题最多 19 节点，覆盖单次回应形成 1/2/3 元素集合、无关回应维持全集、一次报价使集合不变但 favored 改变、后续回应保持 favored、自身收益与利他终局选择、不完整信息及按私有答案改变报价。逐边原生重放、全部节点收益对照和显式标签断言通过，当前为案例证书而非已导出的训练集。

完整查询起点的 4 个记录配置：2 个同步策略迭代循环无标签；2 个 1,953 节点、5 次更新收敛，但 8 个根动作全部并列，不能提供动作选择奖励差异。缩小场景大幅改善成本，不自动解决收敛及区分力。未改初始化/平局作隐式回退，未改 self-play 环境。

所有能力梯度、启动简单课程的实际前置事项与可并行继续的问题，统一见 `training/b_sft/TEACHING_CURRICULUM_PLAN.md`。核心区分：先完成版本一致的最小数据包、新 B/P 奖励与课程到 GRPO 的接线、实际生成/参数更新验证及每 10 步分层评估，即可尝试简单课程；完整调查起点、一般定性联合 belief、复杂更新与多人迁移不应全部成为第一轮训练前的门槛。旧 `examples/social_b/grpo.yaml` 仍引用旧 B 数据和 worker，不能直接运行新私有 P/B 检查点。


## 用户确认隐藏目录后的采样包（2026-09-14）

用户要求提供 GPU 2 vLLM 启动、代码上传及测试命令，并确认目录可见性。已坦诚指出旧教学包会公开目录；用户通过澄清明确选择“先隐藏目录并重算标签，再测试”。本轮新增 `prepare_no_catalogue_probe.py`，以旧模板的固定槽位作为显式公开事实，其余位置按题面声明的完整教学生成支持重新枚举；不保留玩家无从知道的小目录排除。生成约束和已公开偏好仍可见，实际 type rows/joint-world 清单不向模型暴露。

最终包为 `new/local_data/social_runs/bp_no_catalogue_probe_v4/`，26 题（18 B/8 P）、208 次正式采样另加 2 次预检。17 题支持扩大，所有 gold 和任务类别重算；新增完整三值 favored 及双隐藏下 favored 消失/维持的检查点。新测试验证支持从任意两配置扩到真实五个合法配置、标签/类别变化、题面无目录/teacher 值泄露、favored 和联合约束例子。原生重放及 26 个 gold tool reward 往返通过。

运行说明见 `training/b_sft/NO_CATALOGUE_PROBE_RUN.md`。上传包只含可见题面、采样程序、启动/运行脚本与校验 manifest；gold/solver 留本地。新服务物理 GPU 2 → port 8007，复用已有 8000–8006，仍用 Qwen3-4B-Instruct-2507。脚本准备完毕但没有远程操作；由用户运行后助手下载，对 B reasoning、支持强弱、联合约束和各玩家知识视角作诊断。当前自然语言 P 只表达可完整支持的小型生成分布条件 belief，不声称已解决一般 likely 多回合接口。


## 无目录小测已下载并评分（2026-09-14）

用户完成远端运行后授权下载 `outputs/bp_no_catalogue_probe_r1/results/`。完整结果已存 `new/local_data/social_runs/bp_no_catalogue_remote_r1/`，详细分析见该目录 `analysis.md`；逐样本评分、逐题诊断、补充统计和 17 条人工 reasoning 证据均已保存。正式 208/208 返回，题包与采样脚本 SHA256 一致，每题 8 次且无重复/重试/截断。冻结基础模型，无参数更新。本轮只有下载与本地分析，没有上传、启动远端任务或使用子代理。

B 为 41/144（形成 0/48、维持 32/56、更新 9/40），P 为 2/64。B 129/144 输出全集，101 条为全集 + undetermined；一律该答案可得 48/144，说明总体分数容易奖励默认模式。直接查询 want 的 6 个错误样本均在文字中承认真值已确定，但工具仍保留全集；直接查询 avoid 的唯一错误也相同。因此必须区分行为推断不足与文字/工具不一致。已给正确旧集合的维持也不稳定，不能由全集维持答对推断维护能力已掌握。联合约束、favored 消失、知情者后续行为更新未得到可靠正证据；一些正确标签仍伴随错误知识视角或虚构公开偏好。

P 当前主要提交 OFFER（56/64），不是 pass/investigate 主导。两人 avoid 后规划虽 0/8，5 条文字清楚提出正确安全组合 P0.action1 + P1.action0，却提交 [1,0]/[0] 而非 [0,1]/[1]。同时存在独立的因果错误：把避免 goal 当作不能执行任何参与该 goal 的共享 action。54 个合法提交中 50 个各玩家期望终局收益全为零，大多数错误不能靠放宽最优容差解决。下阶段应优先补动作位含义、AND 达成关系、旧 belief 保持及单次行为候选比较的最短教学。

本题包 8 道 P 全部只剩 1 次提案机会，4 道利用此前调查答案，0 道主动 investigate 正例；不能据此判断主动调查策略或长程规划能力。完整查询起点的正常轮转、成本、可求解性仍需继续；setup 强制查询不等于最优查询证书。本轮也没有测试一般 likely 定性联合接口，不据此否定定性语言。17 个全错组中 5 个仍有格式 -1 / 合法错误 0 的奖励差异，语义有对有错的组共 7 个；区分格式学习与核心能力信号，但初始难题 0/8 不构成 GRPO 训练禁入条件。后续以最短课程训练及每 10 步分层验证检验学习路径，不让默认全集和格式题占据主要有效奖励。


## 具名题面修复、输出对照与主动调查证书（2026-09-14）

用户指出动作编号早已从正式接口移除，要求检查 prompt 质量、统计错误全集、调查 tool call 与解释不一致，并补 investigate / likely 测试和短教学。核查确认：正式 `Observation.to_agent_dict()` 使用具名新增承诺，但本轮 `prepare_no_catalogue_probe.view()` 直接导出了 solver 的 public_game/public_state 和完整向量，绕过了原有展示边界。此前将 P 大量错误归因于模型而未先核对导出接口，是题面验收遗漏。新增 `social_named_probe.py`，所有状态、历史、目标、动作及提交统一具名；内部仍保存原生索引/向量用于可逆转换及评分，不修改游戏机制。

全集逐条审查：129 条中 82 条集合错误、14 条集合正确但 favored 错、3 条目标错误、30 条完整正确，见原结果目录 `full_set_audit.json`。不能惩罚所有全集，否则会教出无依据排除。文字与工具冲突仍不能直接归因为 tool call：新包对同样 8 题比较 separate_tool、joint_tool、text 三种提交；不根据解释修复答案。重命名/不重命名、短教学/无教学也分别有控制组，不把它们混作工具接口效应。

主动 investigate 现已找到通过原默认 solver 的短正例，无策略选择回退或新增伙伴类型：两人、三个 goals、每人两个 commitments、一个未知偏好，剩余轮转 Alex → Blair → Alex。根树 7,201 节点，逐边原生核验通过。12 个根动作中只接受调查关键未知偏好：自身期望 2/3，与最佳不调查相同；伙伴期望从 1/3 提高到 2/3，默认 own/social 容差各 0.1 不改变标签。对应 want/neutral/avoid 私有答案的 B 更新与下一次自身报价均已导出，同公共历史下答案不同使报价改变。伙伴中间 PASS 是同一 teacher 下正概率的自愿行为；完整树保留其他全部合法动作，不把 PASS 强制为策略。

另做相同公共历史、相同末轮伙伴响应的信息消融：不知道自己调查答案时重新选择最佳固定报价，自身期望与有信息时同为约 0.6471，但伙伴期望从 0.6765 降至 0.3235。该公共历史的 posterior 已因伙伴自愿 PASS 而非等权，未偷偷按等权评分。根动作净比较和同公共历史的信息使用消融分开记录于新包 `investigate_certificate.json`。同结构末轮不调查反例和已知目标查询干扰项已加入。仍缺严格提高自身收益的调查正例、多个隐藏目标的相关性选择，作为后续梯度，不阻塞当前教学。

likely 新组采用两人三目标、单未知完整三值支持，14 个措辞检查点：12 个宽区间 LP 稳定标签，2 个只有 possible 而不足确定动作的题无语义奖励。没有把英文词强制映射成隐藏单点概率；未声称解决一般多回合定性推演。certain 同步移入已知事实，避免与 unresolved 矛盾。

最终包 `new/local_data/social_runs/bp_named_bridge_probe_v2/`：51 个基础检查点、91 个请求条件、728 次正式采样及 6 次接口预检、11 个带解释的短教学例。89 个有语义标签的请求条件通过 gold 往返；2 个含糊条件单独保留。28 项相关测试通过，新增具名/调查测试覆盖名字重排、旧承诺不丢失、私有信息、全集正确/错误、三输出格式与采样入口。完整 prompt 样例与运行命令见 `training/b_sft/NAMED_BRIDGE_PROBE_RUN.md`。助手未上传或执行远端命令，未训练；由用户运行，之后下载评分。
