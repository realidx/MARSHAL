# 训练准备审查（2026-09-20）

本次只审查训练数据和准备验收工具，不依据 CalBench/对抗测试表现筛题，不改奖励或训练场景。

## B/P 低信号题

旧审查覆盖的 56 个目标题在当前 `data_reasoning_v5_candidate/bp_train.jsonl` 全部存在，56/56 输入完全相同、teacher 字段完全相同；使用当前 prompt_clarification.request 重新跑两套名称的工具/schema/评分往返，全部通过。逐题证据见 bp_correspondence.json。

因此旧审查关于这 56 题的复算结论仍适用于当前相同输入/标签；不能据此宣称整个 v5 标签全部正确，也不能证明模型能从稀疏奖励学会。旧审查是 selected-policy teacher 条件下的结论，仍不等于现实 LLM 对手的普适推断规则。

## SP 收益结构

输入为当前训练文件的全部 108 个 reset，文件 SHA256 和逐局原生回放见 sp_incentives.json。

方法：以全 PASS 为基线；枚举目标承诺布尔模式，按合法原生 OFFER/ACCEPT/PASS 构造顺序轨迹，保存不同收益向量的终局见证。不是完整规划搜索，也没有要求模型知道隐藏偏好。路径存在不等于信息条件下可发现、伙伴激励相容或期望上优于拒绝。

- 108/108：至少某位玩家有比全 PASS 更好的交互路径。
- 96/108：每位玩家各自都找到了改善路径（不保证是同一条路径）。
- 95/108：找到全员不差且至少一员更好的路径。
- 97/108：也找到会损害至少一位玩家的交互路径。

额外枚举最终承诺模式计算每位玩家的效用上界，忽略时序可达性。上界不高于 PASS 时，可以证明该玩家无法通过承诺获得更高收益；否则见证未找到不代表不可能。

上界审查另发现 13 个玩家—reset 组合不可能比全 PASS 获得更高终局效用；这是局部的无正向交互收益角色，不是整个游戏都无收益。保留少量保守行为控制合理，但这些角色不能作为需要主动协调的训练证据。

目前没有依据把全库替换成更主动的场景。仍缺针对私有信息、接受激励、协商难度的覆盖量化；不以提案频率替代这些性质。

## 梯度验收入口

`training.social_mixed.gradient_acceptance` 与训练共享 objective.py，不调用 optimizer、不生成回答。读取新配方保存的 calls，使用匹配 actor HF checkpoint 与冻结 reference，计算两组 norm 参数上的分项实际梯度及 B/P 夹角。分别报告任务、协议、KL；不是 logprob 空间的梯度。

在已分配 GPU 的 SoC 作业内执行（路径需要替换）：

```bash
python -m training.social_mixed.gradient_acceptance \
  --model /absolute/matching_actor_hf \
  --reference /absolute/frozen_reference_hf \
  --calls /absolute/new_run/calls/step-N.jsonl \
  --rows 16 \
  --output /absolute/new_run/gradient-acceptance-N.json
```

actor 必须对应生成这批 rollout 的权重；优先选择 reference 已有非零偏离的 checkpoint。新配方需要 task_weight 等分项字段，旧 calls 不能不经转换直接使用。

此工具采用 HF、有限行和代表性参数，不能认证完整参数梯度、Megatron TP/DP 聚合、裁剪或实际 optimizer 更新。模型文件尚未在本地可用，且分布式栈缺 ray；本次未运行 GPU 验收，不宣称梯度平衡已通过。无需为此启动超参数搜索；它是运行检查工具。

## 本地验证

新增 SP 见证可沿原生规则独立重放到相同终局收益。稳定配方与旧低信号负例测试一起运行；CPU 测试通过不等于 GPU 栈通过。
