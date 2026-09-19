# B 推断递进练习 v6

针对最新训练仍为 0/192、0/160 的 B2 linear reduced-support，以及低成功率 B1 linear/B2 binary。保留 v5 的所有原题、P、SP、验证和测试，不用旧测试失败案例制作新题。

74 个训练父题各增加两种训练辅助版本，共 148 题：B2 linear 24、B1 linear 44、B2 binary 80；其中 44 题标签为 full support 对照。它们不是新的独立结构。

- likelihood：同一历史下提供查询偏好的先验与观察动作的条件似然表，练习贝叶斯更新、支持集和 favored；表格是显式额外教学信息，因此不能用辅助题成功证明自主行为推断。
- procedure：仅提醒比较合法替代动作、应用 teacher 平局规则、结合先验；不提供数值或答案。
- raw：原题请求完全不变，保留自主推断目标。

新 stable-v2 sampler 在 B 候选中按三个阶段轮换，阶段内继续覆盖/active 交替；step 轮换起点。仍为每题8次、B/P各目标4有效组、总候选32上限。阶段配额针对候选，不保证各阶段产生等量有效梯度。

似然按 teacher 的世界条件动作概率、可见信息先验边缘化得到，不使用 realized hidden preference，不反推 gold 制表。52 个原有缩集题复用已审查且与当前输入/teacher完全一致的证据，其余对照重新求解。每题表格更新复核 gold；全部新增题做两种名称的工具/schema/评分往返。逐父题表格在 b_bridge_audit.json。

验证仍无辅助，使用 validation 的 raw B reduced-support 分项检查迁移；不能仅报辅助题正确率。无法保证本轮训练必然学会原始零信号题。

启动脚本默认 SOCIAL_DATA_DIR 指向本目录，可显式覆盖。新训练应从预定起始模型开启新阶段，不传旧配方 resume checkpoint。源码需要先提交同步，训练入口要求 clean checkout。

数据文件变更后旧对抗 v2 的训练源散列不再匹配，不能原样沿用正式 OOD 认证。虽然本次没有新增几何，正式评测前仍需更新来源审查；不得按测试表现重新选题。
