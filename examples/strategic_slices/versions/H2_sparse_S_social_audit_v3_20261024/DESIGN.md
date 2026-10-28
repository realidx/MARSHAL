# 稀疏S原因与回应社会平局信息审计v3

父版本`H2-sparse-S-causes-full31-v2`，仅新增只读汇总和独立诊断维度，不修改已关闭源码、
游戏、reference、主S或训练reward，也不把新量静默并入Q/S选择。

新的检查动机：主S只计算own utility损失，而既定规则要求ACCEPT/REJECT自身最终效用平局时
优先最大化其他玩家最终效用总和。own S=0不能推出不需要信息遵守这条规则。

对原31局保存标签逐条检查：仅response、两个以上own最优动作、遗漏策略在原Oracle当前Q矩阵下
自身第一步regret<=1e-8、其他人总效用第一步regret>1e-8时，另记为社会平局信息敏感。
入口后的完整遗漏策略与原Oracle continuation可能不同，非终局项限定为当前动作Oracle评分诊断。
最后一轮response无后续决策，额外断言当前社会regret与原保存的实际secondary payoff loss一致。

这不是把他人效用加权进主utility，也不是新GRPO；主S仍原值，D未测、prompt/训练未改。
汇总同时保留31局完整诊断、缺失46/76、数值门槛检查、入口时点联合遗漏与未来新观察保留验证。
