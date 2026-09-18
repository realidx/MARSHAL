# 下一轮训练：B/P-only 与 SP-only

本轮只运行 `bp` 和 `selfplay`，`both` 表示这两个独立实验，不运行 Mixed。提交入口默认选择 `data_reasoning_v5_candidate`；底层历史代码的默认数据不改变，直接调用 Python 时需显式设置 `SOCIAL_DATA_DIR`。

## 已冻结的设置

- 数据：594 道 B/P 训练题、495 道开发题，108/36 个 SP train/dev reset，仅 binary/linear。
- B/P 在原 v4 每步任务组上限内重分配；同题 8 个 replica。SP 为每 reset 4 个 replica。两臂各 6,553,600 个训练响应 token，输出上限 1024。
- 截断／非法调用使用默认 −0.2 的独立负 advantage；合法调用保留任务 advantage。详见 [PROTOCOL_SIGNAL.md](../../training/social_mixed/PROTOCOL_SIGNAL.md)。
- Prompt 只修改目标依赖表的玩家列名，并增加一句“所需承诺不是偏好；一个承诺可以影响多个目标”。没有增加 grounding 任务或额外状态表。历史 v3/v4、正式 A、CalBench 提示文件不被改写。
- **第 0 步验证**：参数更新前，当前模型完成 45 道 B/P（各一次）与 8 局 SP，保存 `validation/step-0.json`。不保存初始 checkpoint。之后每 10 次更新和正常训练结束验证，评估 token 不计训练预算；两臂验证相同，不加载 Q0。

## Best 与 last

每臂保留最佳开发验证 checkpoint 和最新完整 checkpoint。两者相同则只有一份实体。先写入完整 checkpoint，再清理不再需要的旧 checkpoint 及其 staging 链接。

- B/P best：先分别平均 B1/B2/B3 与 P1/P2/P3/P4 的 binary/linear 准确率，再按 B/P 各 50% 合并。格式失败和截断按原完整样本评分计入。
- SP best：固定开发 reset 的 `cohort_player_utility_lower` 最大；未完成局用其偏好可计算的效用下界计入，不只算完成者。平分时依次比较完成率、较低非法调用率。
- 完全平分保留较早 checkpoint。best 只在训练后验证点中选；step 0 是基线，不作为待保存的训练 checkpoint。
- 指针：`BEST_CHECKPOINT`、`LATEST_CHECKPOINT`，退出时另写 `LAST_CHECKPOINT`；选择分数存 `BEST_VALIDATION.json`。目录 `checkpoint-N` 中 N 为从零计的优化器 step，完成更新数是 N+1。
- SIGUSR1/TERM 在当前更新结束后保存最新状态。初次周期验证前若被抢占，可能暂时只有 latest；恢复后继续验证。没有自动重新排队。

小开发面板的 best 是选择规则，不是正式泛化结论。旧奖励版本不能作为相同实验续训；版本、数据指纹和协议系数均检查。

## 发布与提交

先在本地检查工作区，将本轮训练代码、v4/v5 候选数据及构建所需基础题归档提交，再 push 到 `new`。不要提交下载的 rollout、checkpoint 或 runs 目录。此文不执行远程操作。

在 SoC 仓库中固定此次代码：

```bash
git fetch origin
SOCIAL_COMMIT="$(git rev-parse origin/new)"
SOCIAL_WORKTREE="${PWD}-train-${SOCIAL_COMMIT:0:12}-$(date +%Y%m%d-%H%M%S)"
git worktree add --detach "$SOCIAL_WORKTREE" "$SOCIAL_COMMIT"
cd "$SOCIAL_WORKTREE"
bash examples/social_mixed/start_training.sh h100-96 both
```

单独提交将 `both` 改为 `bp` 或 `selfplay`。单卡 H200 将 profile 改为 `h200-141`。每臂独立 token 预算；B/P 不为凑齐 SP 的软批量 token 目标而补题，不保证相同步数。

提交入口先运行数据、配置、依赖检查，然后调用 sbatch。保留现有 SoC conda 环境和本地 Qwen3-4B-Instruct-2507 模型路径；本地不代为操作远程。回执在 `submission/reasoning-v5-<profile>-*/`。若第二臂提交失败，只补交缺少的那一臂。

结果在 `runs/social_mixed/<arm>-seed<seed>-<jobid>/`。同版本实验恢复用：

```bash
bash examples/social_mixed/submit_soc.sh h200-141 bp /absolute/path/to/checkpoint-N
```

`start_training.sh` 始终新建实验；恢复用 `submit_soc.sh`。训练 worktree 在运行期间保持不变。

## 本地验证边界

CPU 数据、采样、prompt、step 0 编排、checkpoint 清理和模拟 Slurm 测试可在本地执行。Ray/Hydra 与真实 Megatron/vLLM checkpoint 写入仍需 SoC 环境的启动检查；没有宣称本地已经跑过 GPU 训练。
