# SoC TicTacToe / Geography 与当前双卡 B/P 配置对照

2026-09-15。本地配置与历史提交 `da7161b` 核对；没有操作服务器。
尚未找到这两次旧任务的完整启动日志，因此不声称已核验其初始化分钟数或实际 GPU/MIG 容量。

## 找到的旧入口

- `examples/tictactoe/sbatch_tictactoe_minimax_2gpu_full.sh`
- `examples/tictactoe/agentic_train_tictactoe_minimax_selfplay_2gpu.yaml`
- 继承 `agentic_train_tictactoe_minimax_selfplay.yaml` → `agentic_val_tictactoe_selfplay.yaml`
- `examples/geography/sbatch_geography_counterfactual_distance3_5_full_2gpu.sh`
- `examples/geography/agentic_train_geography_counterfactual_distance3_5_2gpu.yaml`
- 继承 `agentic_train_geography_counterfactual_distance3_2gpu.yaml` →
  `agentic_train_geography_counterfactual_selfplay_2gpu.yaml` → 上述 TicTacToe 双卡配置。

## 实质差异与相同点

| 项目 | 旧 SoC 双卡配置 | 当前 B/P 双卡 |
|---|---|---|
| 框架入口 | ROLL AgenticPipeline | ROLL RLVRPipeline |
| 训练策略 | `megatron_train` | `deepspeed_train`，ZeRO-2 |
| 训练并行 | TP=2、PP=1、sequence parallel | TP=1、DP=2 |
| 优化器路径 | Megatron distributed optimizer | PyTorch AdamW + DeepSpeed ZeRO-2 |
| 模型 | Qwen3-4B-Instruct-2507 | 同型号模型 |
| 推理 / reference | vLLM / HF | vLLM / HF |
| 角色布局 | 三角色共用两卡，onload/offload | 三角色共用两卡，onload/offload |
| 初始化顺序（当前代码） | actor → vLLM → reference | reference → vLLM → actor |
| attention 配置声明 | `flash_attn: fa2` | `attn_implementation: sdpa`（actor/reference） |
| 作业资源 | Slurm 请求两张 `h100-96`、24 CPU、`--mem=0` | 两张 A100-40G，私有 Ray 声明 16 CPU |

旧 Slurm 请求的 GPU 标签不是实际可用显存证明：仓库另有 H100-47 共享卡的单卡配置，
Geography 脚本也包含 MIG 设备解析。Ray 的逻辑 CPU 声明不是操作系统 CPU 配额或独占保证。
attention 表中仅列配置声明，不据此断言旧运行实际 kernel 或初始化加速幅度。

此前将当前慢主要解释为“旧任务模型常驻、现在才共卡卸载”不适用于这两项 SoC 任务，必须纠正。
两个任务本来就采用共卡卸载。真正需要对照的是 Megatron TP=2 与 DeepSpeed DP=2 的加载、
优化器和通信路径，以及两台机器运行环境。不能仅因后端不同，就断言它解释了全部 25 分钟。

旧配置不能整份复制到 B/P：旧 counterfactual/reinforce、长度奖励、重试、输出格式不是 B/P
的二元原生工具 GRPO 目标。若回到 Megatron，需保留 B/P 数据与奖励，并适配目前专门检查
DeepSpeed global_steps、FP32 master、Adam 恢复及未切分 Qwen 参数的预检；两张 40G 的峰值未验证。

## 已下载 v6 的确定证据

`new/local_data/social_runs/bp_two_a100_preflight_v6/continuous/startup-3819228.jsonl`：
Ray 8.10 秒，pipeline 构造 1531.73 秒，合计约25分40秒。
角色创建112.64秒，reference352.04秒，vLLM549.80秒，actor415.50秒。
reference 模型加载两副本129.76/277.14秒，actor28.35/116.46秒，graph捕获88/20秒。
仅完成一条初始验证回答打分，无训练更新；参数见证确认 step=0、actor 与 vLLM 抽样参数相同。

这些日志定位了耗时阶段，尚不能区分共享资源争用、I/O 和 CUDA/通信等待。
本地新增详细阶段 begin/end、进程 CPU/缺页/I/O 快照、超过60秒时的线程栈，外部监控每10秒
记录本任务进程树与系统 CPU/内存/交换/I/O 压力，不读取其他任务的进程参数或环境。
CPU 前置检查使用实际 TensorDict 与生产 DataProto/采样后处理/GRPO loss 代码，验证128条
样本、16组、独立种子、零优势组与非零梯度；它不替代 CUDA/ZeRO 的真实更新验证。
