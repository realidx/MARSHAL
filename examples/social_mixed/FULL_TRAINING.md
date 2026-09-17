# 完整训练入口（2026-09-17）

直接运行完整预算实验，不插入小规模训练能力实验。Teacher 使用已修复的现有精确版本；本次噪声与初始化审查不改变训练标签。

## 已接入

- 所有提交均限定 binary/linear；启动及加载数据时检查真实目标规则。活跃数据为 `data_binary_linear_v3`：426 道 B/P 训练题、275 道开发题、96/32 个 self-play 配置。44 道结构测试题不进入训练或周期验证。
- P4 每次被采样时同时包含 query_only 与 ordinary_only；日志包含分内核、规则、角色与题型的有效 advantage 组及全样本表现。
- 三种训练组：Mixed 的 B/P/SP 权重为 25%/25%/50%；SP-only 为纯 self-play；B/P-only（命令参数 `bp`）为 B/P 各 50%，仍使用二值任务奖励的 GRPO，不是答案 token 的 SFT。三组都从同一本地基础模型重新开始，seed 默认 42，各 6,553,600 个训练响应 token。
- Mixed/SP-only 的 65,536 tokens/update 是停止补充 self-play 的软目标，不是硬批量上限，完整游戏收尾可能显著超出。B/P-only 每步使用与 Mixed 相同调度的完整 B/P 对照组，每题 8 次，不补 self-play，也不强制凑齐 65,536 tokens。三组都按实际进入训练的响应 token 累计停训，不保证 100 步或相同更新次数；另有 1000 步安全上限。
- 三组使用相同固定开发评估：33 道 B/P 题、每题 2 次，加已有 self-play 验证。每 10 步及正常终止边界评估，评估响应不计入训练预算。
- checkpoint 每 10 步与终止边界保存，不再首步强制保存，Mixed/SP-only 保留最近两份完整 checkpoint，B/P-only 仅保留最新一份完整 checkpoint（新 checkpoint 完整写入后才删除旧的）。SIGUSR1/TERM 请求保存退出；不会自动重新排队。不能从失败的 mixed-851174 或 v1 数据 checkpoint 续训。
- 提交前只做 CPU 数据/采样检查、配置构造和环境依赖检查，不运行训练或模型 rollout；作业内继续已有 GPU/NCCL 启动检查。

## 本地发布本次修改

本次实现保留为工作区修改，尚未 commit/push。按下面显式路径提交，避免带入下载的结果与其他本地审查目录：

```bash
cd /Users/bruce/MARSHAL
git add examples/social_mixed/data_binary_linear_v3 \
  examples/social_mixed/data_distribution_v2 \
  examples/social_mixed/start_training.sh examples/social_mixed/submit_soc.sh \
  examples/social_mixed/bp.yaml examples/social_mixed/sbatch_train.sh \
  examples/social_mixed/FULL_TRAINING.md examples/social_mixed/GIT_TRAINING.md \
  examples/social_mixed/SOC_CURRENT.md \
  training/social_mixed/core.py training/social_mixed/distribution_sampling.py \
  training/social_mixed/pipeline.py training/social_mixed/run.py \
  training/social_mixed/preflight.py training/social_mixed/prepare_coverage_v2.py \
  training/social_mixed/prepare_binary_linear.py training/social_mixed/scoring_scope.py \
  training/social_mixed/test_scoring_scope.py \
  training/social_mixed/structure_coverage.py \
  training/social_mixed/test_structure_coverage.py \
  training/social_mixed/test_full_submission.py training/social_mixed/test_training.py \
  training/social_mixed/test_bp_only.py training/social_mixed/test_configuration.py \
  training/social_mixed/checkpoints.py training/social_mixed/test_checkpoint_retention.py
git commit -m "Exclude mixed scoring and connect binary-linear full training"
git push origin new
```

## SoC 提交

在 SoC 已有 MARSHAL Git 仓库中执行。独立 worktree 固定此次训练代码，不影响后续继续开发 new：

```bash
git fetch origin
SOCIAL_COMMIT="$(git rev-parse origin/new)"
SOCIAL_WORKTREE="${PWD}-train-${SOCIAL_COMMIT:0:12}-$(date +%Y%m%d-%H%M%S)"
git worktree add --detach "$SOCIAL_WORKTREE" "$SOCIAL_COMMIT"
cd "$SOCIAL_WORKTREE"
bash examples/social_mixed/start_training.sh h100-96 both
```

`both` 提交两个独立作业，每组两张 H100-96、gpu-long 最长 72 小时。如果使用单卡 H200，将 profile 改为 `h200-141`；每组一张卡，gpu 分区最长 3 小时，可能需要之后恢复。只提交一组可将 `both` 改为 `mixed`、`selfplay` 或 `bp`。`both` 保持原义：仅 Mixed 与 SP-only，不会自动增加第三组。

新增 B/P-only 的完整实验：

```bash
bash examples/social_mixed/start_training.sh h100-96 bp
```

B/P-only 训练路径不访问 self-play 配置、不产生终局收益训练样本；共同验证仍包含完整游戏，只用于评估，不计入训练 token 或梯度。配置为 `examples/social_mixed/bp.yaml`，回执和输出目录使用 `bp` 前缀。

默认沿用环境 `/home/e/e1300530/tmp/marshal-vllm09` 和模型 `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`。这是 SoC 训练入口，不是 chenjiahao 的 A100 rollout 环境。

提交输出给出每组 job ID 与回执路径 `submission/binary-linear-v3-<profile>-*/<arm>.json`，包含 source version、数据哈希、seed 和预算。若第二组提交失败，第一组的 job ID 已保存；只补交缺少的一组，不要重复运行 both。

训练结果在 `runs/social_mixed/<arm>-seed<seed>-<jobid>/`：`metrics.jsonl`、`validation/`、`checkpoints/`、`RESULT.json`、`EXIT_CODE`。H200 等时间限制下，确认完整 checkpoint 后，用原入口按相同硬件布局恢复：

```bash
bash examples/social_mixed/submit_soc.sh h200-141 mixed /absolute/path/to/checkpoint-N
```

`start_training.sh` 总是新实验；恢复应使用 `submit_soc.sh`。作业排队或运行期间不要修改训练 worktree。训练完成前不使用结构测试选择 checkpoint。

## 验证状态与限制

本地已通过数据检查与 CPU/模拟 Slurm 提交检查；未运行新的 GPU 训练。此次 SoC SSH 连接被跳板机 password 认证拒绝，因此没有真实 job ID。

仅使用 homogeneous binary / homogeneous linear 游戏，mixed 完成规则已从所有活跃数据及请求文件排除。Mixed 训练组名称仅表示 B/P+self-play 的损失组合。继承 test 来源的历史使用情况尚未独立核实，作为实验解释限制记录。

B/P-only 接入验证：23 项 CPU／模拟提交测试通过，覆盖零 self-play 训练、B/P 各 50% 权重、每题八重复及三组一致的开发评估。当前本地缺少 Hydra，完整配置构造测试无法在本机运行；提交入口会在已有 SoC 环境检查三个训练组配置后才调用 sbatch。尚未提交 B/P-only GPU 作业。
