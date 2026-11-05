# Q/S 行动价值表与分布描述审阅 v1，2026-11-04

用户授权：检查按行动分布变化评价信息是否合理，判断原100父游戏哪些标签需重新计算，完成后再讨论800入口。
独立研究扩展，不覆盖旧Q/S或已关闭快照，不激活prompt、奖励、D或训练。用户已同意slice入口起控制当前玩家至原生终局。

## 定义与文献核查

1. `Q_full(I,a)`保持原定义：固定已认证对手reference，当前强制行动a，自身之后使用完整可见信息最优应对至终局。
   完整信息指玩家合法可见信息，不是读取其他玩家真实隐藏偏好。
2. 对每条允许遗漏的旧信息e，仍建立相同的遗漏观察forest：入口counterfactual权重不使用本人过往行动概率；
   保留规则、目标、公开偏好、自己偏好、当前承诺/pending/额度/合法菜单；后续记住新观察/自身行动。
   `Q_omitted_subjective(e,a)`是遗漏条件信念下，强制当前a并用遗漏条件最优后续的期望终局收益。
   `Q_omitted_evaluated_true(I,e,a)`把同一后续策略放回实际完整入口I评价；两种Q不能混称同一个量。
3. 保留旧标量`S=V_full(I)-V_I(pi_omitted)`为收益损失摘要；补齐整张表和行动分布，不将旧S偷偷改为KL。
   `own_current_loss=sum_a pi_omitted(a)[max Q_full-Q_full(a)]`；
   `own_future_loss=sum_a pi_omitted(a)[Q_full(a)-Q_omitted_evaluated_true(a)]`；两项之和等于S。
4. `canonical_full_action_probabilities`在完整Q/response社会次级规则允许的最优当前动作上均匀。
   遗漏分布沿原forest均匀剩余平局；完整Q的未来自身平局仍沿旧contingent_values规则保留reference支持。
   TV及JS(nats)仅描述这套明示Oracle平局约定产生的分布变化，绝非目标模型行动概率，不直接排序/筛选。
   一个变化很大的分布可能仅在同收益动作之间重分配，S仍为0；微小动作差距可对应JS=log2。
   不把Q直接softmax：温度、行动基准分布、效用尺度会额外规定行为模型，尚未获准引入。
5. 补充`relative_Q_change`，即遗漏与完整各自的`maxQ-Q(a)`向量之差、最优集合及其交集。
   共同平移所有Q不会产生相对变化；其Linf只作统计，不是最终strategic分数。
   response仍区分own最优与社会次级最优；自身S=0不证明协议上无信息需求。
6. D仍需在固定新题面/工具/采样/控制合同下测量；Oracle分布变化不冒充模型D。
   模型的遗漏收益差可能为负（误用信息/采样噪声）；不继承Oracle非负性，更不由本次CPU结果补猜。

文献支持的是研究方向，而非我们的全部具体口径已经有现成认证：

- [Blackwell, Comparison of Experiments (1951), 原始档案](https://digicoll.lib.berkeley.edu/record/112749)：
  信息结构与可实现决策风险的比较是成熟方向；档案可检索，原文PDF本次403，未声称已逐页读过。
- [Chen等，UAI 2017](https://proceedings.mlr.press/r15/chen17a.html)：
  sequential value of information以信息帮助做出高质量决定及其成本为目标，非单独追求熵下降。
- [Arumugam & Van Roy，NeurIPS 2021](https://proceedings.neurips.cc/paper_files/paper/2021/hash/517da335fd0ec2f4a25ea139d5494163-Abstract.html)：
  将学习目标的信息需求与performance shortfall结合，说明信息变化须连到决策后果。
- [Schulman等，Equivalence Between Policy Gradients and Soft Q-Learning，§2–3](https://arxiv.org/html/1704.06440v4)：
  Boltzmann分布来自明示的KL/熵正则目标、温度和基准分布；不能将它当成未正则化游戏唯一的行动分布。
- [Fosgerau等，Discrete Choice and Rational Inattention，作者稿](https://www.its.caltech.edu/~mshum/papers/general_entropy.pdf)：
  行动概率依赖信息成本/随机效用模型，logit仅是特例。本文不额外引入该行为模型。

## 数据身份与计算范围

“原100”严格指`new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl`，
SHA256=`30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad`。
原终局reference99份、缺25；H2/A2H2三人变体及结构24池另有身份，不能拼成“已升级正式100”。
本轮重用原99份reference，只补节点标签，不重新搜索/选择均衡；重新构树并认证，原生cutoff必须为0。
旧Q/S及保存遗漏分布逐项对照。第25题保留missing，零CF保留不可测；不以窗口reference代替。

每条遗漏forest本就计算了各当前行动的后续值；新增返回它们，避免对每个动作分别重新求解。
保留证据唯一确定入口的singleton直接复用自身Q；这是同一信息结构下own价值等价，不表示社会收益或真实隐藏world相同。
本轮完整补算需要运行，不可仅从旧`omitted_action_probabilities`还原未选择动作的遗漏Q。

参数：CPU workers=2；数值线程每进程1；构树max_nodes=100000、60秒；reference重新认证180秒；
指标无内部时限；epsilon=1e-8、tie_tolerance=1e-9；固定终局reference，不新加奖励/温度/选题阈值/配额。
每次运行独立输出目录和完整pipeline_snapshot；源文件/输入/reference/旧labels均记录SHA256。

## 800入口之前

先统计去重入口的行动结构、私人/历史信息渠道、当前/后续损失、社会平局和父游戏覆盖。
Q/S用于构造结构覆盖的候选集，模型D决定对目标模型的实际难度；本轮不提前规定800配额或最终100。
运行结果另写新报告及EVIDENCE，不覆盖本文方法合同或旧报告。
