# 双 A100-40G、CUDA 11.8 的 RL 框架选择

2026-09-15。仅完成本地代码和公开源码审查，未改变训练入口、远程环境或当前 B/P v2。没有远程执行。

## 结论

在驱动470.256.02、torch2.6.0+cu118、vLLM0.8.5.post1+cu118保持不变的前提下，OpenRLHF 0.8.0 + DeepSpeed ZeRO-3是首选迁移验证候选，特别针对B/P。其版本和原生Hybrid Engine比最新版框架更贴近现有环境；这不是已验证的双40G成功配置，也不是官方认证的整套CUDA11.8组合。

如果同时要求摆脱DeepSpeed而采用FSDP2，旧版verl值得适配，但不能称为开箱即用的CUDA11.8路线。没有找到一个同时原生满足当前环境、我们的原生工具B/P、多玩家私有信息self-play和精确采样token契约的零适配框架。单凭换框架无法承诺初始化时长或显存峰值。

## 确认的源码证据

### OpenRLHF 0.8.0

版本提交：`a542dd98d29efacef89a4f694366e66c6e6d419b`。官方源码归档已下载到`/private/tmp/openrlhf-v080.tar.gz`，解压到`/private/tmp/OpenRLHF-0.8.0`，只读审查。

- [setup.py](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/setup.py)明确指定vLLM0.8.5.post1。
- [requirements.txt](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/requirements.txt)固定DeepSpeed0.16.7、FlashAttention2.7.4.post1、Ray2.43.0、Transformers4.51.3。这与当前DS0.16.3、Ray2.58、Transformers4.57.3不同；不允许无分析覆盖环境，也不能把依赖范围当运行证明。
- [官方GRPO Hybrid Engine脚本](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/examples/scripts/train_grpo_ray_hybrid_engine.sh)有group_norm、ZeRO3、colocate_all_models、vllm_enable_sleep、deepspeed_enable_sleep、梯度检查点和packing。原脚本是8卡、microbatch8、模型reward并开启eager，不能整份用于我们。
- [状态卸载实现](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/openrlhf/utils/deepspeed/deepspeed_utils.py)明确只支持ZeRO3 sleep，并处理较新DS版本修复后的状态类别。GPU优化器路径默认使用DeepSpeed FusedAdam，需要真实算子编译/加载验证；不是当前B/P v2使用的torch fused AdamW。
- [Agent实现](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/openrlhf/trainer/ray/vllm_engine_async.py)强制VLLM_USE_V1=1。它收集文本和字符action_ranges，后续[experience maker](https://github.com/OpenRLHF/OpenRLHF/blob/v0.8.0/openrlhf/trainer/ppo_utils/experience_maker_async.py)重新分词。默认累计文本预算也不等于我们的每次输出1024预算。不能直接用来训练当前self-play。

### verl

- [最新安装文档](https://verl.readthedocs.io/en/latest/start/install.html)要求CUDA>=12.8，支持的vLLM已远新于0.8.5。
- [v0.4.1安装文档](https://github.com/verl-project/verl/blob/v0.4.1/docs/start/install.rst)仍声明CUDA>=12.1，示例环境主要cu124/cu126，并非官方cu118路线。
- [v0.4.1 FSDP工具](https://github.com/verl-project/verl/blob/v0.4.1/verl/utils/fsdp_utils.py)对torch>=2.6使用公开FSDP2 API；[worker](https://github.com/verl-project/verl/blob/v0.4.1/verl/workers/fsdp_workers.py)已有全分片、reference offload、训练/采样权重管理。因此FSDP2本身不是被CUDA11.8一票否决，整套适配仍需验证。
- [v0.4.1依赖](https://github.com/verl-project/verl/blob/v0.4.1/setup.py)限定tensordict<=0.6.2，vLLM extra限定<=0.8.5（不包含0.8.5.post1）。v0.5.0转为tensordict0.8–0.9.1，vLLM extra仍<=0.8.5。不能无视post-release约束或直接装最新版依赖。

### TRL

[TRL0.18.2依赖](https://github.com/huggingface/trl/blob/v0.18.2/setup.cfg)允许vLLM>=0.8.3，GRPO已有colocate和FSDP参数同步，适合较简单单轮任务。但该版[GRPOTrainer](https://github.com/huggingface/trl/blob/v0.18.2/trl/trainer/grpo_trainer.py)没有后来版本的vLLM sleep调用，也没有现成的多玩家工具轨迹接口。不能引用最新版功能声称这个旧版具备它们；双40G全参加self-play不是这次的首选迁移方向。

## CUDA与驱动边界

[FlashAttention2.7.4.post1构建源码](https://github.com/Dao-AILab/flash-attention/blob/v2.7.4.post1/setup.py)要求nvcc>=11.7，并包含sm80编译目标，CUDA11.8+A100有构建路径。还需匹配torch2.6、Python3.11和C++ ABI，验证BF16前后向。

[NVIDIA小版本兼容说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)对CUDA11.x提供有限旧驱动兼容；新driver API和PTX仍可能失败。保持实际已验证的cu118 NCCL和ptxas，不因切框架就撤掉修复。不直接使用CUDA12 Docker镜像，也不把更改CUDA_HOME当驱动升级。

## 迁移验证应如何缩小范围

先验证OpenRLHF0.8.0候选依赖能否与模型、工具模板共存，再检查小张量NCCL、FA2 BF16前后向、FusedAdam及ZeRO3卸载/恢复。小型模型验证权重同步、CUDA graph恢复和checkpoint。最后单次加载4B，连续完成真实rollout/update/sync及保存/恢复，记录各阶段峰值与时间；不将这些检查拆成反复冷启动4B的完整任务。

B/P目标布局：两卡训练ZeRO3、GPU Adam、非当前阶段状态卸载；不增加学习型reward model或critic；保留当前二元reward、16题×8回答、1024输出和工具模板，microbatch1。vLLM先沿用V0/XFORMERS和CUDA graphs路径，TP1双副本还是TP2单副本由完整显存预算决定，不能先保证二者任何一个必然合适。

Self-play需独立的token级环境适配：保留每次真实输入/输出token及behavior log-probs，按实际初始世界×玩家位置计算优势，只有对应玩家生成token参与loss，按玩家轨迹正确归一化。不能借框架迁移改成单代理文本拼接、泄露私有状态、缩短历史，或使用教学残局替换真实游戏。旧Agent示例不是满足该契约的现成实现。

本次仅建议迁移验证方向，未安装OpenRLHF、修改ROLL或提交新训练。
