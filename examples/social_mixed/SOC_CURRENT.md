# SoC 当前训练入口（2026-09-16）

运行时适配来源：origin/codex/outcome-rollout-nus-1gpu，提交 e1430bb。
仅合入 vLLM 0.28 适配、Hermes/ChatCompletionRequest 新导入路径、HF reference 去除非必需 DeepSpeed 导入、依赖检查及 Conda 默认值。数据仍使用 data_distribution_v1，未采用远程分支的旧 data/ 课程。

目标：marshal-vllm09 环境（路径名不是版本），Qwen3-4B-Instruct-2507，gpu-long 的两张 h100-96，Megatron TP=2，两个 actor-local vLLM TP=1 副本，HF reference 两个 worker。不启动 HTTP 服务，不安装依赖，不使用 H100-47/MIG 作为默认。

vLLM 0.28 适配明确调用 V1。VLLM_USE_V1=0 保留交接要求，但不代表运行 V0。实际 executor 被适配器设为 uni，因为 ROLL 已管理每个 actor 的 GPU 和进程。CUDA_HOME/nvcc/LD_LIBRARY_PATH 保留交接分支逻辑，继承新 Conda 环境激活后的 cu13 路径。

新增修复：SocialWorker.generate_native 使用 prompts=[{'prompt_token_ids': ...}]，旧的独立 prompt_token_ids 参数不适用于 vLLM 0.28。依据：https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/entrypoints/llm.py 。依赖检查验证实际生成方法签名。

提交前在新环境运行 training.social_mixed.check_dependencies（不加载模型）。作业内开启 SOCIAL_GPU_PREFLIGHT=1：独立 torchrun 按 profile 的 rank 数 检查 CUDA 可见性和 NCCL all_reduce，进程退出释放上下文，再进入模型初始化。失败日志为 gpu_topology.log、nccl_preflight.log。driver 心跳、phases.jsonl 和 BP_STARTUP_DIAGNOSTICS 继续记录初始化阶段。默认每10步验证/保存，首步及终止边界强制保存；最近两份完整 checkpoint 保留。

本地没有该 CUDA/Ray/vLLM 训练环境，因此本地语法、数据和脚本测试不能代表远程训练已通过。最终需核对训练 metrics、实际参数更新、权重同步、原生 checkpoint 和恢复。

A100 diagnostic 上传包 marshal-distribution-probe-v1.tar.gz 已冻结，不受后续 SoC 适配影响。SoC 使用另一个包 marshal-social-soc-v028-v1.tar.gz，解压到独立目录，不覆盖原始远程 checkout。

## 执行效率版本 v2

固定执行参数（依据显存预算选择，尚无 GPU 吞吐实测，不声称绝对最优）：

| profile | 训练 microbatch | reference microbatch | 每卡采样并发 | vLLM 显存比例 | 训练状态常驻 | reference 常驻 | 激活重算 |
|---|---:|---:|---:|---:|---|---|---|
| h100-47 | 1 | 1 | 16 | 0.50 | 否 | 否 | full |
| h100-96 | 2 | 4 | 16 | 0.55 | 否 | 是 | full |
| h200-141（单卡 TP=1） | 2 | 4 | 32 | 0.45 | 否 | 是 | full |

显存比例只是 vLLM 预算，不包含其他进程。单张 H200 在训练/采样之间卸载 Megatron 状态，避免与 vLLM 的缓存同时常驻；H100-47 仍必须通过实际可见性/NCCL 检查，不能用配置修复不兼容的 MIG 分配。GPU 检查会核对实际容量是否匹配所选 profile。

执行优化：
- 每个训练 microbatch 按实际长度裁掉右侧 padding，长度对齐 TP=2。PP 固定为1。
- 尾批补零权重样本，按 padded_count/original_count 校正真实样本权重；每次完整 rollout 仍只有一次 optimizer update。
- reference/采样分配按长度交错到两张卡，并还原输出原始顺序，避免一张卡独占长请求。
- reference 小尾批不再扩大到超过配置上限。
- self-play 初始32局（单张 H200 也为32局），每空出4个位置补入一个新的四重复组；预算达到后停止补组并完成全部已开始游戏。不按终局收益、完成速度筛掉已开始的游戏。
- 执行器仍按同步生成波次返回结果；本版没有实现 token 级异步调度，波次内部最后一个请求仍可能造成尾部等待。
- 开启前缀缓存，用于相同问题的重复采样；现有 offload 会在更新边界清缓存，不跨策略权重复用旧 KV。
- 硬件 profile 及实际参数记录到 experiment.json/resolved_config.json。

提交入口：`bash examples/social_mixed/submit_soc.sh <profile> <mixed|selfplay> [完整checkpoint路径]`。
H100-96 默认 gpu-long；H100-47 检查 gpu-long 是否提供对应GRES，否则 gpu三小时；H200使用 gpu三小时。H100申请两张卡，H200申请一张卡。H200可通过同入口第三参数恢复，不自动重复提交排队。只支持相同 TP/world size 的原生续训，双卡 TP=2 checkpoint 不能直接在单卡 TP=1 续训； microbatch/采样并发变化可能改变数值舍入和每步收集边界，不保证逐token复现。

本版打包文件：marshal-social-soc-efficient-v2.tar.gz。使用独立解压目录。不要覆盖正在运行的 v1 目录。

### v2 上传与提交

Mac：
```bash
rsync -avP -e 'ssh -J e1300530@stujump.comp.nus.edu.sg' \
 /private/tmp/marshal-social-soc-efficient-v2.tar.gz \
 /private/tmp/marshal-social-soc-efficient-v2.tar.sha256 \
 e1300530@xlogin.comp.nus.edu.sg:/home/e/e1300530/
```

SoC 登录节点准备（成功后终端当前目录为新 runtime）：
```bash
cd /home/e/e1300530
sha256sum -c marshal-social-soc-efficient-v2.tar.sha256 && \
SOC_RUNTIME="$(mktemp -d "$PWD/social-efficient-v2-XXXXXX")" && \
tar -xzf marshal-social-soc-efficient-v2.tar.gz -C "$SOC_RUNTIME" && \
cd "$SOC_RUNTIME"
source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
export PYTHONPATH="$PWD:$PWD/mcore_adapter/src:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
export SOCIAL_MODEL=/home/e/e1300530/models/Qwen3-4B-Instruct-2507
export VLLM_USE_V1=0 VLLM_TOOL_CALL_PARSER=hermes TOKENIZERS_PARALLELISM=false
python -m training.social_mixed.check_dependencies > dependency-check.json 2> dependency-check.log
```

上述检查成功后按资源选一条（不是三条全部提交）：
```bash
bash examples/social_mixed/submit_soc.sh h100-96 mixed
bash examples/social_mixed/submit_soc.sh h100-47 mixed
bash examples/social_mixed/submit_soc.sh h200-141 mixed
```
将 mixed 改为 selfplay 即提交对照。恢复同一实验：
```bash
bash examples/social_mixed/submit_soc.sh h200-141 mixed /absolute/path/to/checkpoint-N
```
