# B1/B2 少量 binary / linear 对照

这批是训练候选补充，不是已通过模型评估的训练集。15 题，全部继承已有 train 拓扑家族；不新增 heldout、不调用模型、不改变正式训练入口。原候选 291 题逐行保留，追加后 306 题，其中 B train 55。未发现与旧候选重复的语义 ID。

## 内核与对照

| 内核 | 场景 | 题数 | 检查能力 |
|---|---|---:|---|
| B1 | partial_helpful | 4 | binary 未完成收益为零；linear 部分收益使 want/neutral 接受、avoid 拒绝 |
| B1 | partial_harmful | 4 | 只把观察者对目标的偏好改为 avoid：linear neutral 因伤害他人而拒绝；binary 仍无信息 |
| B1 | compensated_control | 2 | 另一完整目标收益补偿部分负收益，avoid 也接受；两种评分均不能排除任何偏好 |
| B2 | target_offer_control | 2 | 两种评分下同一目标提案均只支持 want，防止学成“linear 必须换答案” |
| B2 | background_offer | 2 | 同一完整背景目标提案：binary 后验 1/5,2/5,2/5；linear 1/4,1/2,1/4，favored 从 undetermined 变 neutral |
| B2 | partial_background | 1 | linear 下部分背景提案只由 avoid 类型选择；binary 同动作概率零，不造标签 |

7 组仅切换评分方式的配对：5 组标签改变、2 组不变。B2 是同一个物理场景的不同可观察提案分支，不是三种独立策略场景。所有题只有一个隐藏偏好（三种候选），B1 一次外部响应，B2 一次外部提案。

B1 的 imposed setup 是合法教学前缀，不当作隐藏偏好证据。B2 对所有合法动作求策略，不能只在展示的提案之间做选择。仅在响应自身收益并列时考虑他人收益，提案并列均匀随机。

## 边界与分布

排除 3 个零概率观测：compensated_control 两种模式下的 REJECT，以及 binary partial_background。它们记录在 manifest，未做成训练题。

本包 15 题中 8 题允许全部三个候选，其中 7 题 favored=undetermined，1 题 favored=neutral。这批配对有意保留 binary 无信息控制，不能按文件行数等权追加到训练采样，否则会增加全集答案权重。后续应按内核/对照组分配配额，并联合统计旧候选中的排除、维持、favored 信号；“单题更多”不意味着该内核更高权重。

本包没有混合 binary/linear 目标同局的题，所有目标统一切换评分。它提供最短评分机制对照，不代表完整难度覆盖。还需 1024 token 的模型重复采样检验可完成率、组内奖励差异及 reasoning。

## 核验

每题重新求解；独立核验终局收益、固定策略下各信息集动作排名及均匀并列概率，再由逐世界动作似然重算后验。测试锁定 15 题全部预期动作似然，并检查配对输入只改变 binary 标志、零概率排除、原候选不变、原生答案奖励 1 和输出预算 1024。

题面见 cards.md；逐世界 prior / likelihood / posterior 与所有合法替代动作概率见 tasks.jsonl 的 teacher.b12_audit；这些审核信息不发送给模型。
