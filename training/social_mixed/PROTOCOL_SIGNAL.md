# 调用级协议负信号 v1

本次只修改截断／非法动作的训练信号，不修改 grounding 提示或数据。每次生成上限保持 1024；不添加按长度普遍扣分或合法格式奖励。

## 规则

- B/P 正确性仍是 1/0；SP 仍按自身终局效用，同一 reset/player 的 replica 分组。
- 任务 advantage 只从任务收益中心化得到，不再加入累计协议罚分。不完整 SP 组继续没有终局任务 advantage，不伪造终局效用。
- 合法调用使用任务 advantage；截断／无法解析／非法动作调用的任务 advantage 置零，改用固定 `-protocol_coefficient`，默认 **−0.2**。
- 协议负信号不组内中心化。全组失败时仍有非零负信号；它不保证一次更新就学会正确动作。
- SP 首答和重试分别判断：失败首答不继承重试后的正任务信号；合法重试正常使用任务信号。保留一次重试与原状态转移规则。
- `Episode.penalties` 与 `protocol_cost` 中原有 −0.1 数值只保留作历史兼容审计，不再进入优化目标，不能与新的 −0.2 相加。
- 基础设施故障拒绝进入优化数据，不当作模型非法动作。

这是直接改变传入 PPO 的 advantage，而不是简单地将任务 reward=0 改为负数。每条调用仍沿用原有 token 平均和 episode-player loss 权重；没有改为按调用数量给长局更大总权重。整个失败回答收到负信号，不能声称定位到了导致失败的具体 token。

## 配置与日志

`python -m training.social_mixed.run ... --protocol-coefficient 0.2`。参数要求有限且大于零，写入 `experiment.json`；版本为 `call-local-negative-v1`。旧奖励版本或不同系数的 checkpoint 不允许作为同实验 resume。

每条训练调用保存 `task_advantage`、`protocol_advantage`、`protocol_failure` 和 `advantage_version`。指标 `*/call_signal/*` 分开报告截断、非截断非法调用、非零任务调用及两种信号的加权绝对量。绝对量是 advantage 权重统计，**不是实际梯度范数**；KL、PPO clipping 等仍影响实际更新。

原 `utility_mixed_groups` 继续报告任务反馈。全错组即使有协议负信号，也不能计作“正确性出现组内差异”。

## 验证

```bash
python -m unittest training.social_mixed.test_protocol_signal training.social_mixed.test_core
```

覆盖全组截断、终局高收益不能强化失败首答、合法重试、合法但答错与格式错的区别、不完整组不伪造终局、基础设施故障隔离。默认系数是待观察的工程起点，尚无新模型训练结果。
