# B chronological controls v4：88 次采样复核

结果：`new/local_data/social_runs/b-controls-v4/20260915-100649/`。
模型 Qwen3-4B-Instruct-2507；11 题各 8 次；1024 输出预算；原生工具、二元任务奖励。

## 完整性和标签

88/88 收齐，task/replica 无重复，各题 replica 0–7，88 个不同 seed。任务和实际 messages/tools 与冻结数据一致；重新计算的 reward 全部一致。11 题通过 verify_task 的 solver、独立收益/响应证书及 posterior 核验，未发现标签错误。标签针对指定 teacher 策略，不代表唯一均衡。

这是两个结构家族中的 11 个训练侧诊断题，不是 11 个独立策略场景，也不是 heldout 泛化评估。

## 结果

| 题型 | 正确/8 | 截断/8 |
| --- | ---: | ---: |
| binary_target_accept | 5 | 1 |
| binary_target_reject | 3 | 2 |
| binary_unrelated_accept | 4 | 2 |
| altruistic_target_accept | 0 | 4 |
| altruistic_target_reject | 4 | 2 |
| altruistic_unrelated_accept | 0 | 6 |
| conflict_target_accept | 0 | 3 |
| conflict_target_reject | 1 | 2 |
| conflict_unrelated_accept | 2 | 5 |
| net_payoff_target_accept | 5 | 2 |
| net_payoff_target_reject | 4 | 2 |

合计正确 28/88（31.8%），截断 31/88（35.2%），格式失败 10/88；其余 19 次为完整、格式有效但标签错误。

原三道 anchor 正确 12/24，截断 5/24；v3 为正确 11/24、截断 5/24。改善没有消失，但样本很小，不解读为进一步提升。新增八题正确 16/64，截断 26/64。

8/11 题有正负 reward；其中 6/11 同时有正确答案与完整有效的错误答案。另两题的负奖励全来自截断或格式失败。三题全零，当前这一组直接计算 GRPO advantage 时没有组内信号。

## 推理审读

审读了针对性正负样本，并完整审读 net_payoff_target_accept 的全部五个正确样本；未对全部 88 条做逐条人工推理标注。

- 净收益接受题的五个正确样本（replica 0、1、4、5、7）全部没有建立正确的联合收益推断，而以没有调查、接受承诺不揭示偏好等理由保留全集。有的同时误称提案与被问目标无关。这些答案得分正确，但不能证明模型理解净收益。
- 该题正确依据：接受同时完成两目标，Blair 的收益分别为 2、1、0，拒绝为 0。avoid 情况下双方总收益仍并列，因此接受仍可能发生；三种偏好都保留。接受后的 posterior 为 want=.4、neutral=.4、avoid=.2，favored 因最高支持并列而 undetermined，绝非行为没有信息。
- altruistic_target_accept replica 2、conflict_target_accept replica 0 出现把动作与目标的关联读错、以及否认行为可以提供偏好证据的问题。
- conflict_target_reject replica 5 虽得分正确，却以 neutral 没有自身收益所以可以拒绝来解释，没有落实他人收益这一平局规则。该启发式不能解释利他条件下 neutral 应接受。
- net_payoff_target_reject replica 2 得分正确，但解释没有完成联合净收益与残余平局分析。

所以目前仍有题面/规则理解错误，同时也有真正的 social reasoning 瓶颈：neutral 条件下的他人收益、多个目标收益求和、由行动反推候选偏好。不能把所有截断归因于循环，也不能把所有正奖励解释为正确推理。

## 对数据和训练的含义

保留 v3 时序/表格呈现和这些对照，不再退回旧呈现。当前已存在二元奖励差异，但不能据此宣布全部 B 数据质量或训练效果已验证。

对照必须成组覆盖接受/拒绝、利他/冲突、需要排除/合法保留全集，避免高配额的单一容易题奖励同一种错误规则。合法全集不能删掉或额外扣分。按机制检查训练配额与累计奖励，而非仅看标签大小数量平衡。

现有全零题保留为较难对照，但不宜成为早期训练的主要采样来源。若补教学题，优先让 neutral 的自身收益平局、他人收益正负这一变化成为唯一变化因素，并继续用 solver 和独立收益验证；不把计算结果或正确推断写进题面。

这些结果不支持继续单纯增加输出预算或引入 retry，也不要求因 base 的错误再重写机制。B group=8 仍合理，但本轮不是 4 对 8 的训练效果比较。
