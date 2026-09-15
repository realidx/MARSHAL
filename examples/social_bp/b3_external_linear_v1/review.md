# 新增B3：两条外部证据，含binary/linear对照

12道新train教学题：6 binary＋6 linear；8道标签更新、4道外部证据后的维持对照。每题均有两次来自他人的自主动作，中间自己的响应/提案不被当作隐藏偏好的新证据。12题的两条外部证据都改变完整联合posterior；4道维持题表示被问偏好的定性标签保持不变，不代表联合posterior没有变化。

原4道“自己接受后维持belief”的B3对照保留。本包补上原先缺失的外部证据链，不冒充全部问题已解决。

## 三组，逐一对比binary与linear

| 场景 | 两条外部证据之间的推理关系 | 题数 |
| --- | --- | ---: |
| direct_followup | 对方先提出承诺安排，随后回应关于被问目标的提案；第二条证据缩小集合 | 4 |
| joint_exclusion | 第一条证据改变联合偏好支持，第二条响应进一步区分；binary可继续排除，linear同路径可能维持被问集合 | 4 |
| joint_favored | 联合隐藏收益与后续机会影响响应似然；linear可在全集不变时把favored从avoid更新为neutral | 4 |

每组都是同一几何、偏好生成规则、查询和事件路径，只切换全部目标的binary标志；两个版本分别重新求解，并都保留ACCEPT/REJECT。binary/linear下的旧belief可以不同，不能强行固定成同一旧belief。

三个场景使用两个既有train结构家族（85cb50332b166e5d、7505d4426cb54a17），均不与原validation/test家族交叉。没有挪用heldout题。这是少量教学结构，不是12个独立策略场景；目前没有混合binary+linear目标的B3题。

## 是否真的需要前一条证据

做了固定策略下的诊断：保留最后的公共历史和响应策略，把观察者的权重重置到初始先验，只乘最后一次响应似然。它不是另一条合法游戏轨迹，不等于删除首事件后重新求解。

- binary joint_exclusion / ACCEPT：正确答案为want/neutral；只看最后一次响应会错误保留avoid。前一条证据不能丢。
- linear joint_favored / ACCEPT：集合仍为全集，但favored由avoid变成neutral；只看最后一次响应会得到neutral与avoid并列。前一条证据不能丢。
- 另3道维持题的标签也对这一诊断敏感，但复制提供的旧belief仍可能得分，因此不把它们算作强“更新”正例。
- 其余题提供较基础的更新/维持对照；不宣称所有题都能单独检验累计推理。

## 规则和工程修改

Private teacher现在显式允许linear目标，保留每个goal的binary标志。旧SharedWindow入口仍默认拒绝linear，避免未经复核的旧流程悄悄改变语义。独立终局收益核验和backward核验同步支持完成比例。

具名题面区分ALL_OF和LINEAR_FRACTION，说明linear得分为已绑定要求数/总要求数乘偏好值。旧binary题面的文本与工具保持不变。语义去重区分binary与linear，结构家族仍把两者放在同一划分中。

本包使用支持多事件、带评分类型的通用B/P题面，没有强行套用只接受三事件最终响应的旧B1 renderer。没有给模型收益表、动作似然或内部worlds。仍是原生工具、二元B奖励、1024输出上限，无retry和length penalty。

## 核验与限制

47项CPU测试通过，涵盖新包12题、真实分数完成收益、各信息集的阶段条件最优动作/均匀并列、逐事件联合posterior、前后标签、ablation、linear语义去重，以及403道旧binary请求逐一不变和原有回归测试。收益与策略审计覆盖所选完整教学树，不用一条抽样回报代替期望价值。

还没有调用模型，不能保证这些题在1024内能被base稳定完成。joint_favored属于组合层，涉及9种联合偏好，不能把它和两目标基础题看作同等难度。当前新包只属于train；linear的heldout泛化尚未验证。

探索过程中若同步最佳响应循环则不出标签，也未换求解顺序作为隐式fallback。教学探索不改变outcome self-play数据，循环不是游戏无解的结论。

## 文件与候选库

- tasks.jsonl：12题及审核标签。
- requests.jsonl：模型可见请求；未实测。
- cards.md：完整题面与分开的审核说明。
- manifest.json：逐题prior/posterior、标签变化、消融结果、文件hash。
- bp_candidate_tasks.jsonl：在上轮279题候选库后加入12题，成为291题，其中B train为40题。P及全部旧heldout逐字保留，原始403题库不变。

采样器尚未切换，所有新题仍training_ready=False；不得据题目数量自动设置B3或linear的采样权重。
