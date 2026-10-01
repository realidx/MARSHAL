# B/P 迁移到 Megatron（2026-09-15）

用户明确要求复用 SoC TicTacToe/Geography 的 Megatron 后端。此前 DeepSpeed 选择来自当前服务器上完成的旧 B 标签实验；没有先对照更早 SoC 配置，这一选择依据不足。历史对照见 `bp_soc_training_config_comparison_20260915.md`。

## 最终配置

入口 `examples/social_bp/grpo_two_a100.yaml` 现为独立配置，无 DeepSpeed 配置继承。actor 为 megatron_train、TP2 PP1 DP1、sequence parallel、BF16、distributed optimizer，遵循原 Megatron 分阶段 onload/offload。actor → vLLM → reference 初始化；角色进程创建并行。vLLM 仍为两个 TP1 引擎、CUDA graphs、sleep、16 并发。

微批为 1，累积从 DP2 时的 64 改为 TP2/DP1 的 128，保持 16 题 × 8 回答、每 rollout 一次参数更新。数据、题目日程、原生工具、二元奖励、1024 输出、LR1e-6、warmup5、KL0.01、clip0.2、30 步且每10步验证不变。

原 DeepSpeed optimizer counter 改为实际 Megatron scheduler.num_steps，只在 optimizer.step 成功后增加。MCA 参数转换剔除 ROLL 专有 optimizer_backend 字段，显式使用实验 seed。两步预检的 lr_decay_steps 仍为正式 horizon30，避免 warmup5 大于预检总步数的断言。

模型 witness 通过 MCA 自带 TP gather/HF 转换，对比两个 TP rank 和两个 vLLM 已加载模型的抽样参数；optimizer witness 包含分片 FP32 master 和 Adam 状态。原生 checkpoint 使用两个 TP 模型文件、分布式 optimizer、scheduler、两份 RNG 和 pipeline 状态；完成标志在同步上传后产生。MCA 模型与 RNG 恢复显式采用可信原生 checkpoint 的 torch.load(weights_only=False)，兼容 PyTorch 2.6 的非 tensor 状态。

## 本地验证

以下 43 项通过（4.49 秒）：

```
/private/tmp/social_native_tools_venv/bin/python -m pytest -q \
  training/b_sft/test_bp_megatron.py \
  training/b_sft/test_bp_two_gpu.py \
  training/b_sft/test_bp_rollout_protocol.py \
  training/b_sft/test_bp_startup_diagnostics.py \
  training/b_sft/test_social_bp_training.py \
  training/b_sft/test_social_bp_curriculum.py
```

包含真实 Hydra 和 dataclass 解析：正式 actor.max_steps30、预检2、BF16=true、world_size2、累积128；生产 TP 分发代码传递完整128条给 TP0，TP1 的 tensor 经已有 broadcast 同步。生产 DataProto/GRPO loss 使用真实 CPU TensorDict/torch 前后向，无模型或 CUDA。

另读取官方 PyPI megatron-core0.12.0 源码，在 CPU 独立执行真实 OptimizerParamScheduler 类与本仓库 MegatronLRScheduler：计数/LR 为 (0,0)、(1,2e-7)、(2,4e-7)，恢复第1步再推进后与连续第2步 scheduler state 相同。对应 [NVIDIA 0.12.0 scheduler 源码](https://github.com/NVIDIA/Megatron-LM/blob/core_v0.12.0/megatron/core/optimizer_param_scheduler.py)。checkpoint 文件布局对照仓库 MCA 以及官方0.12.0 dist_checkpointing 源码。

这些验证没有执行真实 CUDA kernel、TP通信、4B模型前后向或原生 distributed optimizer save/load，因此不能宣称双40G显存已通过，也不能保证无错误或承诺初始化变快。依赖检查在模型前执行；没有操作远程或更改服务器环境。

## 日志与交付

每个初始化阶段有 BEGIN/END、耗时、CPU运行/调度等待/I/O增量，60秒线程栈；独立进程每10秒记录当前任务进程树，GPU每5秒记录。日志不会把重叠/嵌套阶段简单相加为总耗时。

上传包 `/private/tmp/marshal-bp-megatron-v1`。运行与下载命令在 `examples/social_bp/TWO_A100_PREFLIGHT.md`。预检先连续两步，再独立重启恢复一步；正式30步仍是一个生命周期。不要把预检中的两次初始化误认为每个更新都重启。
