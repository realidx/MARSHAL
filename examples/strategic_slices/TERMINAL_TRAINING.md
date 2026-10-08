# v4 terminal slices：逐步 binary reward 训练

2026-10-06：按本次讨论采用此首版方案。使用选定的 100 道 train slices；
原 v4 pool、reference、D 结果和数据传输包不变。训练入口已实现，CPU 校验
与 mock 用于检查交互和评分；**尚未启动 GPU 训练，16K context 的训练显存
与新 collector 的真实 optimizer/checkpoint 链路仍需 smoke 验证**。
此前的 [discussion draft](TERMINAL_TRAINING_DRAFT.md) 仅作历史记录。

当前 contract 为 `terminal-step-binary-shared-reset-loo-fixed-questions-v3`：
**每 update 固定 4 道题 × 8 trajectories**，总训练目标仍为 6M response
tokens；best 按用户选定的 **validation 整段 slice 成功率**确定，保留 best
和 final，二者相同则只有一份 checkpoint。旧 token-batch 版本不能静默续跑。

本次修订 `terminal-step-binary-shared-reset-loo-v2`：按用户要求沿用 **1024
输出 tokens**（训练和 validation 一致）；恢复失败调用额外 **−0.2 protocol
advantage**。context 仍为 16384。原 D 的 4096 配置与历史结果不改。
修订后 12 项 training/native-budget 检查通过，包括全组失败时仍有 penalty、
有效调用不受额外惩罚、默认请求上限 1024；100 题 metadata check 也通过。

## Reward 和 advantage

同组默认 8 条 trajectories，共享 slice entrance、hidden world、focal player。
各 replica 独立采样模型与固定 oracle 的随机动作。跨组重新从该题声明的
joint distribution 采样；hidden world 只用于环境执行，不进入模型输入或
把评分 belief 改成 point mass。

第 t 个受控 decision，令 Q_t(a) 为：基于当前**可见信息的 posterior**，
先选 a，剩余 k−t 个 focal decisions 最优行动，随后恢复原 frozen terminal
oracle 的期望 terminal utility。partner 始终使用同一 frozen profile。
root 使用冻结的 root_Q，后续计算有限控制窗口的 exact best response，
terminal continuation 复用已求解 reference，不重新求 equilibrium。

```text
r_it = 1  if legal and max_a Q_t(a) - Q_t(chosen) <= 1e-7
       0  otherwise

mean_reward_j = mean(r_jt over actually generated decisions)
b_-i = mean(mean_reward_j for j != i)
task_A_it = r_it - b_-i
protocol_A_it = -0.2 if truncated or invalid action else 0
A_it = task_A_it + protocol_A_it
```

所有 value-tied optimal actions 都得 1。1e-7 是数值容差，不是允许损失
0.1；不额外奖励 INVESTIGATE，也不要求模仿 oracle 的单个 tie-break action。
terminal utility、whole-window success 保留为评价指标，不进入训练 reward。

A_it 仅作用于**该步生成的 response tokens**，包括该步生成的 reasoning
和 tool call；后续步骤的得分不会复制给前面的 tokens。baseline 排除本条
trajectory，用其他 replicas 估计，避免自身得分进入自身 baseline。
不做 std normalization。protocol penalty 不进入 binary reward 或组 baseline；
作为独立 loss 项，仅作用于失败 call 的 response tokens，不回传给有效 prefix。
因此合法但 suboptimal action 的 task reward 同样是 0，却没有额外 protocol penalty。

复用 PPO clipping (0.2) 和 frozen-base reference KL (0.01)。每条 trajectory
等权，其内部对实际生成的 decisions 取平均，每个 decision 对 response
tokens 取平均。这是 sampled-state local correctness 的训练 surrogate；
不宣称它等价于 terminal-utility policy gradient，亦不是单一 trajectory
reward 的标准 GRPO。可变长度加权和跨状态共享 baseline 是首版取舍。
全部 0 或全部 1 的组没有 task advantage；全组截断/非法仍有 protocol penalty，
也可有 KL 项。`task_active_groups` 与 `protocol_active_groups` 分开统计，
`active_groups` 是二者的并集，不把格式纠正信号当作战略分离度。

依据是已保存的真实 D：whole-window binary 只有 179/800 成功，strong
acquisition 只有 2/96；但逐步正确分别有 567/1251 和 86/203。
这支持先尝试逐步反馈，不能证明训练一定更好，也不能用独立-reset D 的
组内分离度代替共享-world训练的实测分离度。

## k、失败、预算与采样

- k=1/2/3 数的是 focal decisions，包括 proposal、investigation、response；
  partner actions 不占 k。达到 k 后 focal 也恢复 oracle，运行至 native terminal；
  游戏提前结束则立即停止，不填充未发生的 decisions。
- 截断、非法/缺失 act：该步 binary reward 为 0，另加 −0.2 protocol advantage，
  结束 trajectory；前面有效步骤的局部 reward
  保留，terminal utility 为 null。无 retry、自动续写或 oracle 补答。
- 网络、context overflow、缺失 behavior tokens/logprobs 或 oracle 错误：
  中止该 collection，不提交 sampler cursor；恢复最近完整 optimizer checkpoint。
- 训练只采 selected 100，按题打乱循环；每周期每题一组，不再按 parent 均匀。
  不读取 validation/test 的结果来选训练题。
- 8 replicas，32 native 并发容量，temperature=1、top_p=1、top_k=-1；
  每个 call 最多 1024 输出 tokens，context 16384，超长 prompt 报错、不裁剪。
  D 的 .8 temperature 不适用于这里实际 behavior-probability PPO 的配置。
- native ROLL 按 decision waves 批量生成；不是 D HTTP 的 completion-refill。
  同批部分 episode 结束后，并发数会下降；保持原生 tokens/logprobs 的对应关系。
- 每 update 固定 **4 道题 × 8 trajectories = 32 trajectories**，总目标
  **6,000,000** response tokens。达到预算后仍完成当前 update 才停止，
  所以可以超过目标。失败和有效 prefix tokens 都计入；validation
  /test 和 oracle 计算另计。沿用 token-progress cosine LR：1e-6 → 1e-7。

固定 batch 使每次更新覆盖相同数量的问题和 trajectories；输出长度变化不会
再改变采样题数。但 k、有效 decision 数和 reward contrast 仍会变化，因此不
宣称每个 batch 的有效学习信号相同。整个 collection 期间权重固定，32 条
trajectories 完成后累积各 microbatch 梯度，进行一次 optimizer update。
100 道题打乱循环，默认每 25 updates 覆盖一遍；下一遍重新采样 hidden world。
`--questions-per-update` / `TERMINAL_QUESTIONS_PER_UPDATE` 默认 4；并发容量
独立控制调度，降低并发不会改变 update 的题数。原 `--tokens-per-update`
已移除。总更新数取决于实际输出量，不再有约 92 步的预估；`max_steps=10000`
仅是安全上限，若先触及该上限会报告预算未完成，不自动运行 test。

## 文件与本地检查

- 数据适配、rollout、reward、resume：`training/strategic_slices/terminal_training.py`
- native ROLL 接入：`terminal_training_pipeline.py`；入口：`train_terminal.py`
- evaluation：`terminal_training_evaluate.py`
- final checkpoint 自动 test：`terminal_training_final_test.py`
- best/final 判定与去重保留：`terminal_training_checkpoints.py`
- SoC 手动启动脚本：`examples/strategic_slices/sbatch_terminal_train.sh`

需要当前 repo 代码和之前的 `strategic-slices-terminal-selected-v4.tar.gz`
数据包。**旧数据包内的 source 是当时快照，不包含本次训练入口**；在空目录
解包后，把 `new/local_data/` 数据复制到当前 repo，避免覆盖当前代码。
不需要另外导出 SFT traces，oracle feedback 在线计算。

```bash
python -m training.strategic_slices.train_terminal --check-only
python -m unittest training.strategic_slices.test_terminal_training -v
python -m unittest training.social_mixed.test_native_limits -v
python -m unittest training.strategic_slices.test_terminal_final_test -v
python -m unittest training.strategic_slices.test_terminal_checkpoints -v
python -m training.strategic_slices.train_terminal --mock --mock-updates 25 \
  --output /tmp/terminal-training-mock
```

默认 mock 的 25 次 collection 覆盖 100 题 / 800 trajectories，额外重复下一批
验证 sampler resume。synthetic token IDs/logprobs 只能验证 plumbing，不能
证明模型效果、真实 tokenizer 或 GPU optimizer 正确。
本地 solver 环境没有 Hydra，完整 Hydra/dacite 配置构建尚未在这里执行；
已检查配置字段覆盖，完整构建使用已有 SoC 环境完成，不能算作本地通过项。

上一版（4096 输出、无额外 penalty）的本地结果：29 项相关检查通过（23 项 rollout/analysis/selection 回归、
3 项 batch/loss 检查、2 项 native budget 检查、1 项逐步 loss 梯度检查）。
全量 mock 为 100 题、800 trajectories、1,248 calls，全部 native terminal；
另重复下一批 32 trajectories 两次，验证恢复结果一致。失败路径由针对性
测试注入，不把 mock 的 100% completion 当作模型证据。证据在
`new/local_data/terminal_training_mock_v1/CHECK.json`；两题 validation mock
及两种 full-game 模式在 `new/local_data/terminal_training_mock_validation_v1.json`。

## SoC smoke：仅提供手动命令

沿用已经跑通的 SoC conda/CUDA/ROLL 环境、Qwen3-4B-Instruct-2507 本地权重。
默认 profile 为 2×H100-47、actor TP=2、train microbatch=1；32/1024/16384
保持一致。脚本不安装依赖或下载模型。下面命令需用户手动执行，本次未提交。

先完成一次 optimizer update 并暂停：

```bash
export TERMINAL_TOTAL_TOKENS=6000000 TERMINAL_QUESTIONS_PER_UPDATE=4
export TERMINAL_MAX_STEPS=3 TERMINAL_EVAL_EVERY=1 TERMINAL_VALIDATION_LIMIT=2
export TERMINAL_PAUSE_AFTER_UPDATES=1
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

然后在相同代码、数据、profile、budget、sampling 配置下，从完整 checkpoint
恢复一次更新；输出用新目录，保持上述 smoke 环境变量：

```bash
export TERMINAL_RESUME=/absolute/path/to/first-run/checkpoints/checkpoint-0
export TERMINAL_PAUSE_AFTER_UPDATES=2
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

核验 `RESULT.json`、`LAST_CHECKPOINT`、checkpoint `COMPLETE.json`，以及
`metrics.jsonl` 中 optimizer update、behavior-probability discrepancy、
binary accuracy、active groups 和 completion。`calls/` 保存每步 reward、Q、
posterior、tokens/logprobs；这些私有审计字段不进入模型请求。
第一步 norm-tensor 变化检查沿用旧 pipeline；finite discrepancy 超阈值按旧
逻辑记录 warning，不自动停止，smoke 需读 `probability_warnings.jsonl`。
CPU 精确 sampler resume 不等于已验证 GPU 浮点逐位复现。

正式运行前清除 smoke 与 resume 变量，从 base model 新开实验：

```bash
unset TERMINAL_TOTAL_TOKENS TERMINAL_QUESTIONS_PER_UPDATE TERMINAL_MAX_STEPS
unset TERMINAL_EVAL_EVERY TERMINAL_VALIDATION_LIMIT TERMINAL_PAUSE_AFTER_UPDATES TERMINAL_RESUME
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

本方案每 10 updates 及结束时评估/保存；初始 base 也评估。正式 validation
覆盖 96 slices，外加对应 12 个 held-out parents 的完整游戏：team self-play
和逐个 focal 对 frozen oracle。temperature=0，1024 输出，报告逐步 binary、
whole-window success、completion、terminal utility 和失败的 outcome bounds。
自动 test 仍使用 final；best 由 validation 判定，test 不参与选择。当前没有独立的
strong-acquisition held-out family，长程泛化也不能由短 parent 自动推出。
失败率须和 completed-only utility 同看；不能把只完成的高分当成整体改进。

## best 与 final checkpoint

best 的唯一排序指标是 validation `full_window_success_rate`：trajectory
成功完成，且窗口内所有实际发生的受控 decisions 均为 oracle-optimal 才算成功；
非法/截断算失败。分数并列时优先较晚的 evaluated checkpoint，因此 final
只要达到历史最高分即同时为 best。初始 base model 仅作监控，不作为训练
checkpoint 候选。默认每 10 updates 和正常结束时评估，best 是这些评估点中
的最好结果，不是未经测量的全部 optimizer steps 中的理论最好结果。

训练期间只保留 best + 最近完成的恢复点；二者相同时只留一份。正常结束后：

- `BEST_CHECKPOINT` 指向 best；`FINAL_CHECKPOINT` 和 `LAST_CHECKPOINT` 指向 final。
- `BEST_VALIDATION.json` 记录成功率与 selection rule；`CHECKPOINTS.json` 记录
  best/final 路径和 `unique_checkpoints`（1 或 2）。
- final 最好或并列最好：两个角色指向同一目录，删除当前 run 其余完整旧 checkpoint。
- final 较差：保留 best 与 final 两份，删除当前 run 其余完整旧 checkpoint。
- 保存包含 optimizer、sampler 和 best-selection 状态。只有新 checkpoint
  完成后才清理；未完成的 checkpoint 不按完整文件处理。
- 跨 output 目录续跑时，可引用旧 run 中的 best，当前 run 只留最新恢复点；
  不自动删除旧 run 的文件。若恢复的 final 本身也是 best，新 run 保存一份
  并重新绑定两种角色，避免把相同权重作为两个候选保留。

保留规则只使用 validation，不根据 test 结果改选 best。自动 test 仍评估
final；保存 best 方便后续独立比较，但本次没有额外增加 best 的 test run。

v3 检查：29 项相关测试通过，包含固定题数与 token target/并发解耦、best
和 final 相同/不同/并列、续跑指针绑定、test 生命周期及旧训练流程回归。
一条旧测试的 keep 参数由 1 修正为 2，以匹配“保留两份”的现有通用规则；
通用 prune 实现未改。真实数据 mock 一次 update 为 4 题 / 32 trajectories /
60 calls，后续 collection 的恢复结果一致，证据在
`new/local_data/terminal_training_mock_v3_fixed_batch/CHECK.json`。这些仍是 CPU
检查，GPU optimizer/checkpoint 链路的 smoke 尚未执行。

## 训练结束后的自动 test

正常达到训练 token 预算、保存 final checkpoint 后，`TerminalPipeline.run()`
自动同步最终 actor 权重并执行 test。暂停、信号中断、提前 gate、step limit
导致预算未完成、训练异常均不触发。test 不参与训练、不选择 checkpoint。
`--validation-limit` 不会截断 test；正常 test 始终使用完整 test split。

- 200 道 test slices，默认每题 8 个固定种子的实例，共 1,600 trajectories。
- 25 个 test parents，每个实例做 team self-play 和逐个 focal 对 frozen
  oracle，共 696 局完整游戏（8 × (25 + 13×2 + 12×3)）。
- temperature=0、每 decision 最多 1024 输出。8 次通过不同 seed 采样
  entrance/world/oracle 随机性，增加实例覆盖；不是温度采样，也不保证穷举 worlds。
  可通过 `--test-repeats` / `TERMINAL_TEST_REPEATS` 调整，默认 8。
- 输出 `test/report.json`（slice 和 full-game 指标、轨迹、逐步记录、checkpoint
  身份）与 `test/COMPLETE.json`（完整报告 checksum）。`RESULT.json.final_test`
  明确区分 complete、interrupted、failed、not_run。`training_response_tokens`
  不包含测试；测试输出量另记为 `generated_response_tokens`。
- test 中断/失败时已完成训练的 checkpoint 保留，不写测试 COMPLETE。
  用同一参数和代码 `--resume <final checkpoint>`、新 output 目录重启即可：
  已用完训练预算，因此不追加 optimizer update，自动重新执行完整 test。
  测试结果不做跨部分运行拼接；同目录已有且校验通过的 COMPLETE 则不重复评分。
- test 曾用于历史 base-model D 分析，报告中明确注明，不能称为完全未查看的
  blind test。strong-acquisition 独立 held-out 覆盖仍然不足。

接入后 15 项 training/final-test 检查通过，覆盖 split 隔离、全部 focal
位置、固定 seed、最终权重同步、完成标记、避免重复评分、暂停/预算未完成跳过、
测试中断和失败恢复。CPU mock 不证明 GPU checkpoint 恢复已验证。

已有生产流程证据见 [历史 BP/SP 链路](../../new/training_chain_evidence_20260921/README.md)
和 [D24](../../new/d24_partner32_evidence_20260926/README.md)。这些支持复用
optimizer/sync/checkpoint 基础设施，不替代本次新配置的 GPU smoke。

## Single H100-96 SoC smoke

`h100-96-single` is a separate execution profile: one GPU, TP=1, train/reference
microbatch=1, full recompute, both train and reference state offload, vLLM memory
fraction 0.40. The existing two-GPU `h100-96` profile is preserved. Override both
Slurm resources and the profile; the script's defaults are still two H100-47 GPUs.

```bash
SOCIAL_GPU_PROFILE=h100-96-single TERMINAL_MAX_STEPS=3 \
TERMINAL_EVAL_EVERY=1 TERMINAL_VALIDATION_LIMIT=2 \
TERMINAL_PAUSE_AFTER_UPDATES=1 \
sbatch --partition=gpu --gres=gpu:h100-96:1 \
  examples/strategic_slices/sbatch_terminal_train.sh
```

For a resume smoke, keep these settings, set `TERMINAL_RESUME` to the complete
checkpoint and `TERMINAL_PAUSE_AFTER_UPDATES=2`, and use a fresh output directory.
This smoke does not establish full validation performance or a completed 6M-token run.

2026-10-06 SoC smoke executed: jobs 915648 and 915674 both exit 0; native checkpoint resume and two optimizer updates passed. [Measurements and limitations](../../new/terminal_training_single_h10096_smoke_20261006/README.md). Subsequent full-target run 915731 was paused after 550 updates and 3,500,783 response tokens (the 6M target was not reached). Both retained checkpoints were exported and evaluated; see [raw results and audit](../../new/terminal_hf_test_calbench_20261008/README.md).
