# B2/B3实际精简

| 数据 | 原train | 保留 | 备用 | validation/test |
| --- | ---: | ---: | ---: | --- |
| B2 主动提案逆推 | 29 | 8 | 21 | 13/9，保持不动 |
| B3 自己响应后的belief维持 | 19 | 4 | 15 | 5/5，保持不动 |

## B2保留内容

- 严格区分want与avoid的两道代表题；来自不同场景，不冒充单变量配对。
- 同一场景两个不同提案分别支持want/neutral与neutral/avoid：2题。
- 较复杂联合情形中的同场景替代提案：2题。
- 主动提案没有信息，保留原belief：1题。
- 全集不缩小但favored改变：1题。

两组同场景替代提案已核对root一致、标签不同。没有声称这8题覆盖所有合法提案，也没有为每个PASS/INVESTIGATE分支补题。动作似然审核考虑所有合法备选行动，主动提案并列不使用利他筛选。当前不修改题面；有旧belief/无旧belief属性保留，不能把差异算成独立推理内核。

## B3的重要纠正

现有29题全部是别人OFFER→观察者自己ACCEPT。逐题检查的不仅是possible/favored，而是完整联合posterior：自己的响应前后全部不变。它们是“不要把自己的行动当成他人偏好的新证据”的维持对照，不是29个真正累计新证据的推理场景。

只保留4种代表：单值、二值且favored、全集undetermined、全集且favored。它们属于同一个维持内核的答案形态对照，不能再次计为4种独立能力。剩余15道train备用。真正的多条外部行为证据导致集合或权重变化，当前仍是缺口，本轮不新造题。

## 验证与文件

80题重新求解，核对策略hash、原生状态/收益、前后belief、gold和posterior；适用时另作独立backward对照，适用数量见manifest。B2的完整根节点备选行动似然、B3前后联合posterior是否相同的检查见audit.jsonl。研究者的审核信息与模型题面分离。

b2_train_tasks.jsonl为8题核心；b3_maintenance_tasks.jsonl为4题维持对照；reserve_tasks.jsonl为36题备用；heldout_tasks.jsonl保留32题原划分。cards.md给出完整题面及标签；selection.jsonl给出逐题去向。

叠加B1的16题，B训练核心从152题缩为28题。bp_candidate_tasks.jsonl为实际合并的279题候选库：28道B train、67道B heldout、184道P。P完全保留，包括之前暂置的8题，不在本轮处理。原403题库不改写；未切换采样器、未设置权重、未启用训练或模型测试。对新核心不能宣称已具有完整B3训练信号。
