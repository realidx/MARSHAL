# B/P 双 A100：Megatron 训练与恢复预检

> **当前用户选择（2026-09-15）：暂停 Megatron/FSDP2 迁移，直接运行 DeepSpeed 正式30步。**
> 使用 `run_two_a100_train.sh OUTPUT_DIR`，配置为 `grpo_two_a100_deepspeed.yaml`，上传包 `/private/tmp/marshal-bp-deepspeed-train-v1`。
> 该入口先做 CPU/DeepSpeed 环境检查和数据导出，然后只启动一次30步训练；不运行下面的两步/恢复预检，不导入 Megatron 依赖检查，不自动安装包。
> 输出目录含 `train.log`、`gpu.csv`、`train.resources.jsonl`；详细初始化日志、评估、checkpoint 在 `training/`。成功标志 `TRAINING_COMPLETE.json`，失败标志 `TRAINING_FAILED.json`。每10步验证和保存，最终checkpoint为 `training/checkpoints/checkpoint-29`。这条双卡完整训练链路尚无成功端到端实测记录。

DeepSpeed v2 上传包为 `/private/tmp/marshal-bp-deepspeed-train-v2`。针对 v1 backward OOM：逐微批去除右侧 padding（不裁有效 token），entropy 系数0时跳过无用计算，backward后立即释放 logits，再加载 optimizer；改用 PyTorch 内置 fused AdamW，环境检查先在两卡各执行小张量更新/状态卸载与恢复；ZeRO-2 关闭通信重叠，reduce/allgather bucket 从50M减为10M元素。输出1024、每题8采样、16并发、microbatch1/累积64、30步计划不变。此次不是恢复旧失败任务，使用新输出目录从原模型启动。

此入口只跑 B/P 链路预检，不启动 30 步正式训练或 self-play。

## 当前版本：Megatron v1（2026-09-15）

明确沿用 SoC TicTacToe/Geography 的 Megatron 训练后端及 TP=2/SP/分布式优化器方案；任务入口仍为 B/P RLVRPipeline。`grpo_two_a100.yaml` 已独立，不继承 DeepSpeed 配置。旧 DeepSpeed checkpoint 不用于 Megatron 恢复。下面 v2–v7 章节仅保留历史记录。

- 训练角色先初始化并卸载，随后初始化 vLLM 和 reference，与旧 SoC 顺序一致；Ray 进程创建仍并行。
- 保留 CUDA graphs、16 并发和两个 TP=1 vLLM 实例。没有跨训练任务常驻 vLLM；连续训练期间会复用引擎。
- 启动顺序：上传哈希校验 → CPU 实际 DataProto/GRPO loss 检查 → Megatron 依赖/API 检查 → 模型初始化。依赖检查要求 megatron-core 0.12.x（仓库 MCA 的版本约束），并检查 Transformer Engine、FlashAttention、MCA、ROLL Megatron strategy/offload 导入。缺失则在模型加载前汇总错误，不自动安装或升级服务器软件。DeepSpeed 仍可能是 ROLL 导入依赖，但不作为此实验训练后端。
- 计数器、抽样权重检查和 checkpoint 完整性已适配 Megatron。两个 TP rank 的权重转换为 HF 布局再与 vLLM 比较；原生 checkpoint 校验 TP 两份模型、分布式优化器、scheduler、每 rank RNG 和 pipeline 状态。恢复预检继续比较 FP32 master、Adam、scheduler、RNG 的抽样证据。
- warmup 保持 5，scheduler 总 horizon 明确为 30，避免两步预检触发 Megatron `warmup < decay_steps` 断言。
- 启动日志：每进程 `startup_events-*.jsonl` 记录 BEGIN/END，`startup-*.jsonl` 记录阶段耗时和 CPU/I/O 差值；等待期间每 60 秒写 `startup-stacks-*.log`。外部监控每 10 秒写 `continuous.log.resources.jsonl` / `resumed.log.resources.jsonl`，仅采集本任务进程树；`gpu.csv` 每 5 秒记录 GPU。

本地 43 项相关测试通过：真实 Hydra/dataclass 配置解析、TP 批次分发、原生工具奖励、DataProto、CPU GRPO loss/backward、计数器、checkpoint 文件缺失检查及启动诊断。另用官方 Megatron-core 0.12.0 scheduler 源码执行了 0→1→2 和恢复检查。Mac 上未运行 CUDA/Megatron 前后向；双 A100 显存、原生 optimizer checkpoint 恢复及实际启动耗时仍需远程验证。

此预检仍有两次模型初始化：连续两步，然后另起进程恢复一次。第二次用于证明真正重启后可恢复，不是每个训练 step 都重启。正式 30 步实验仅初始化一次。


## 数据与配置

- 冻结包：`data_two_a100_v1`，train 280（B 152 / P 128），validation 67，test 64。
- 原始训练题去掉 9 道直接读取调查结果的 B；加入 30 道非 L0 短行为题、3 道简化 L0 assisted 题。L0 formation follow-up 未加入。新增 3 道 L0 validation。
- 原 test 的题目、输入、标签不变，仅加训练包来源元数据。test 不进入采样和验证。
- 每步 16 题：B 为 L0 2 + 其他 bridge 3 + 原行为题 3；P 四池各 2，information 一正一反。每题 8 个独立 seed，共 128 个回答。30 步题目 ID 已写入固定 schedule，不按本次模型成绩重采样。
- 前 30 步固定配额。两卡共同用于采样和训练，TP=1 两个 vLLM 实例，CUDA graphs + sleep；训练使用 Megatron TP=2、PP=1、DP=1、sequence parallel、distributed optimizer，microbatch=1、累积 128 次。两张卡共同处理同一批 128 条回答，每轮一次 optimizer update。
- 原生工具、二元奖励、1024 输出预算、无答案 retry、无长度惩罚。最大输入 2048，超过即报错，不截题。
- 候选正式参数：LR 1e-6、warmup 5、KL 0.01、clip 0.2、每批 1 epoch，30 步，每 10 步验证；验证当前统一 67×4（268 回答）。新 L0 单独统计，不将辅助题得分等同于完整行为能力。
- 预检覆盖当前 CPU/GPU 软件环境的真正兼容性和显存峰值；本地通过不代表两张 40G 已实测可容纳。保持 GPU optimizer，阶段切换时状态暂存主存。

## 预检如何判定

先连续更新 2 步，再另起独立 Ray 进程从 `continuous/checkpoints/checkpoint-0` 恢复，接着完成第 2 步。`checkpoint-0` 表示已完成一次 optimizer update。

连续过程采样 256 回答，恢复过程再采样 128 回答。另有 3 轮 4 道训练 canary×4 回答，共 48 回答，总计 432。canary 仅作接口检查，不是 held-out 成绩。warmup 的第一次 LR 可以为 0；第二次之后要求观测到实际 BF16 参数变化。

必须同时满足：

1. 两个 actor rank 的实际 Megatron scheduler `num_steps`（仅 optimizer.step 成功后推进） 为 0→1→2；恢复为 1→2。
2. 采样前检查两副 vLLM **已加载模型张量**与 actor 的抽样指纹一致；reference 保持 base。
3. 第一次 checkpoint 恢复后，模型/FP32 master/Adam/scheduler/RNG 的证据匹配。
4. 每题 8 个不同 seed；恢复后相同步的题目和 seed 相同。最终用更新两次的权重再生成。
5. checkpoint 文件完整，两个 driver 正常退出。

检查张量采用跨所有 MLP 层、embedding、最终 norm 的抽样指纹，不声称逐比特全模型或完整训练可复现。预检成功也不证明策略改善；奖励差异、截断和错误类型要另看 rollout。

## 本地上传

```bash
cd /Users/bruce/MARSHAL
python3 -m training.b_sft.build_bp_training_bundle --output /private/tmp/marshal-bp-megatron-v1
rsync -az --progress -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  /private/tmp/marshal-bp-megatron-v1/ chenjiahao@36.102.215.18:/raid/chenjiahao/mas/
```

bundle 已存在时不覆盖；更新后使用新的 bundle 目录。服务器启动时验证上传文件哈希。

## 服务器运行（用户执行）

确认这次仍分配 GPU 6、7；若编号变更，只修改 `BP_GPUS`。

```bash
cd /raid/chenjiahao/mas
BP_GPUS=6,7 bash examples/social_bp/run_two_a100_preflight.sh \
  /raid/chenjiahao/mas/runs/bp_megatron_two_a100_preflight_v1
```

可在已有 tmux 会话运行。使用 `/raid/chenjiahao/conda_envs/mas/bin/python` 和本地 Qwen3-4B-Instruct-2507。独立本地 Ray，不连接旧 Ray、不运行 `ray stop`。依赖缺失/未核对版本会留下 environment.json 后停止，不自动安装升级。当前预检允许 torch 2.6.0、vLLM 0.8.5.post1、transformers 4.51.3/4.57.3；版本后缀单独记录。

成功必须出现根目录 `PREFLIGHT_COMPLETE.json`。错误会保留 `PREFLIGHT_FAILED.json`、已产生的日志和 rollout。不要因为出现 checkpoint 就认定成功。

## 下载（本地执行）

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/bp_megatron_two_a100_preflight_v1
rsync -az --progress \
  --exclude='*.bin' --exclude='*.pt' --exclude='*.pth' --exclude='*.safetensors' --exclude='*.distcp' \
  -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/bp_megatron_two_a100_preflight_v1/ \
  new/local_data/social_runs/bp_megatron_two_a100_preflight_v1/
```

checkpoint 权重保留远程；下载 JSON 证据、生成内容、日志和 GPU 采样记录即可分析。全部三份 checkpoint 可能占用较多磁盘，请使用 /raid 路径。预检不自动开始正式训练。

CUDA graphs 与 eager 参数语义核对来源：[vLLM 0.8.5 LLM 文档](https://docs.vllm.ai/en/v0.8.5/api/offline_inference/llm.html)。本仓库已有 sleep/权重同步封装，是否兼容当前环境以这次实测为准。

## 2026-09-15：0.16.3 环境检查修正

第一次运行在版本检查处停止，未加载训练模型。原检查仅允许 0.16.4，现允许服务器的 0.16.3，同时在模型加载前核对 checkpoint/ZeRO-2/卸载接口签名与枚举。保留实际更新、权重同步和恢复校验，不自动升级环境。官方两版的 `_update_model_bit16_weights`、`_link_all_hp_params`、`get_data_parallel_partitions`、`state_dict`、`load_state_dict` 经 AST 比较一致；这不是端到端训练已兼容的证明。

新版上传包：`/private/tmp/marshal-bp-two-a100-v2`；重新运行请使用新的输出目录 `runs/bp_two_a100_preflight_v2`，保留原失败记录。

核对源码：[DeepSpeed 0.16.3 ZeRO-2](https://github.com/deepspeedai/DeepSpeed/blob/v0.16.3/deepspeed/runtime/zero/stage_1_and_2.py)、[卸载状态枚举](https://github.com/deepspeedai/DeepSpeed/blob/v0.16.3/deepspeed/runtime/zero/offload_config.py)。

## Ray 临时盘空间修正（v3）

原入口把 Ray 临时目录固定到 /tmp；该盘只剩约 12 GB 时反复报警。新入口默认使用 `/raid/chenjiahao/ray`，可用 `BP_RAY_TMP_ROOT` 覆盖；独立 session 和 object spilling 都在该目录下。启动前检查目标盘剩余比例和 Unix socket 路径长度，实际路径/空间记录在 `ray_session.json`。不会删除旧 session 或关闭其他 Ray。

先在服务器执行 `df -h /tmp /raid/chenjiahao /dev/shm` 确认挂载与剩余空间；不能假设 /raid 一定是独立且空闲的盘。运行中的 Ray 不能靠修改环境变量迁移目录。仍在推进的任务可先观察；需要切换时，在任务结束或停止本任务后上传 `/private/tmp/marshal-bp-two-a100-v3`，并以新输出目录 `runs/bp_two_a100_preflight_v3` 运行。不要在任务运行中覆盖代码。

Ray 2.46 官方实现支持 `object_spilling_directory`：[源码](https://github.com/ray-project/ray/blob/ray-2.46.0/python/ray/_private/node.py)。

## NCCL 诊断草案（v4，已被下方 v5 替代）

reference 首次 all-reduce 报 `CUDA driver version is insufficient for CUDA runtime version`，这时尚未开始训练。新增 `training.b_sft.check_bp_nccl`，在加载模型之前检查两张卡各自 CUDA 运算、FP32/BF16 all-reduce。每个进程只看到自己分配的卡，与 reference worker 一致；通信开关沿用关闭 cuMem/NVLS、loopback。

诊断只使用少量张量，不启动 Ray/vLLM、不升级依赖。记录 nvidia-smi、磁盘、包版本、LD_LIBRARY_PATH/LD_PRELOAD、各 rank 实际加载的 CUDA/NCCL 动态库、NCCL 日志和 ldd 结果。进程总等待上限 100 秒，失败保留证据。单独 NCCL 通过后仍需检查 Ray worker 与模型阶段，不能将诊断成功视为训练成功。

服务器先执行（输出目录需全新）：

```bash
cd /raid/chenjiahao/mas
/raid/chenjiahao/conda_envs/mas/bin/python -u -m training.b_sft.check_bp_nccl \
  --gpus 6,7 --output /raid/chenjiahao/mas/runs/bp_nccl_check_v1
```

旧驱动 470 支持部分 CUDA 11.x 小版本兼容，不能仅凭 nvidia-smi 的 CUDA 11.4 与 torch cu118 不同就认定必须升级驱动；需核对实际加载的库及功能路径。[NVIDIA 兼容说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。

## v5：沿用已完成 B GRPO 的运行环境（当前入口）

找到本地 `new/local_data/social_runs/b_grpo_b_r2_final/run_manifest.json` 与 checkpoint-59 完成记录：2026-09-12 的 B r2 已完成 60 步。解释器为 mas；torch 2.6.0+cu118、vLLM 0.8.5.post1+cu118、DeepSpeed 0.16.3、Ray 2.58.0、transformers 4.57.3。原脚本与 YAML 都显式预加载私有 cu11 NCCL。新 B/P 入口此前漏带这项设置，重现了旧记录已解决的相同 CUDA driver insufficient 错误。

已恢复：

- `CUDA_HOME=/home/chenjiahao/cuda-11.8`。
- `LD_LIBRARY_PATH` 优先使用 `/raid/chenjiahao/conda_envs/mas/lib`。
- `NCCL_LIBRARY=/raid/chenjiahao/mas/new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2`，校验已完成训练 manifest 中相同 SHA256：`4de8ef6a9d27e45e0e3d067c81fdc0a7103cb318e34557da25949a4230a9caaf`。
- launcher、Ray driver runtime_env、各 worker system_envs 显式继承 `LD_PRELOAD`；初始化前检查实际映射路径。
- 撤销 v4 自动追加的通信诊断，不重复安装包、下载库或跑 GPU smoke。私有库缺失时明确停止，不改共享 site-packages。

旧训练使用六卡、vLLM 独占且关闭 sleep。当前双卡分时卸载不能凭旧结果声称已实测通过，仍执行原有两步训练与恢复预检。旧数据/部分匹配及失败 -1 奖励不迁回；保留当前冻结 B/P、二元奖励及 1024 输出预算。

当前上传包 `/private/tmp/marshal-bp-two-a100-v5`。上传后执行：

```bash
cd /raid/chenjiahao/mas
BP_GPUS=6,7 bash examples/social_bp/run_two_a100_preflight.sh \
  /raid/chenjiahao/mas/runs/bp_two_a100_preflight_v5
```

Ray 目录仍采用 v3 的 `/raid/chenjiahao/ray`；保留此前 v1/v2 的失败结果。

## 历史 v6：缩短初始化等待（已由 Megatron v1 替代）

用户澄清目标是缩短训练初始化，不要求跨任务常驻服务。本版保留原 driver 生命周期，优化启动阶段：

- B/P 两卡模式并行创建 actor、vLLM、reference、reward 的 Ray 进程及查询设备；CPU reward 初始化与 GPU 初始化重叠。
- 各角色的实际模型初始化保持串行，以控制两张 40G 的峰值；reference 先初始化，基础 NCCL 故障在 vLLM 初始化前暴露。
- 每个进程产生 `startup-<pid>.jsonl`，记录进程创建、Ray、reference NCCL/加载、vLLM、actor NCCL/加载、ZeRO、初始卸载、恢复和权重通信设置的耗时。阶段有嵌套，不把所有秒数相加当总耗时。
- 保留 v5 的已验证私有 cu11 NCCL 和 CUDA 路径、v3 的 /raid Ray 临时目录。

本地并行同步屏障、失败传播、原 B/P 训练回归等 25 项测试通过；未实测远程节省时间。上传包 `/private/tmp/marshal-bp-two-a100-v6`，新输出目录 `runs/bp_two_a100_preflight_v6`。上传与运行方式同 v5，仅改版本目录；不要覆盖正在运行的代码。
# v7：修复 rollout 附加字段的 DataProto 类型

v6 运行在 `DynamicSamplingScheduler.report_response` 拆分返回批次时可能触发
`non_tensor_batch must be a numpy.array with dtype=object`。原因是新增的
`bp_token_count` 和 `bp_sample_seed` 使用了默认整数 dtype，违反 ROLL 的
DataProto 约束。v7 显式使用 object 数组，并在 postprocess 返回前校验。
数值、随机种子、输出 token、结束原因和奖励规则均保持不变。

本地 26 项相关测试通过。新增 CPU 回归执行生产 postprocess、DataProto
重复/索引/一致性检查方法，覆盖单条与 8 条返回、带/不带种子、stop/length；
恢复旧表达式时三个场景均复现原断言。该测试不替代远程 GPU 训练预检。

上传 `/private/tmp/marshal-bp-two-a100-v7/` 后，使用新结果目录：

```bash
cd /raid/chenjiahao/mas
BP_GPUS=6,7 bash examples/social_bp/run_two_a100_preflight.sh \
  /raid/chenjiahao/mas/runs/bp_two_a100_preflight_v7
```
