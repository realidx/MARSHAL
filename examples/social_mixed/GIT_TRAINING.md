# Git 训练入口

当前完整实验使用 data_binary_linear_v3。新数据、双臂提交和回执说明见 [FULL_TRAINING.md](FULL_TRAINING.md)。

一次提交完整 Mixed 与 SP-only：`bash examples/social_mixed/start_training.sh h100-96 both`。

不再生成或上传 tar 包。Git checkout 优先以 commit 校验代码，不读取旧 bundle_manifest；训练的 experiment.json 记录 source_commit/source_version。无 .git 的历史上传包仍使用 manifest 校验。

本地提交并 push 后，在服务器的已有仓库执行（将 origin/new 换成需要的已推送分支或 commit）：

```bash
git fetch origin
SOCIAL_COMMIT="$(git rev-parse origin/new)"
SOCIAL_WORKTREE="${PWD}-train-${SOCIAL_COMMIT:0:12}-$(date +%Y%m%d-%H%M%S)"
git worktree add --detach "$SOCIAL_WORKTREE" "$SOCIAL_COMMIT"
cd "$SOCIAL_WORKTREE"
```

按需提交一个实验：

```bash
bash examples/social_mixed/start_training.sh h200-141 mixed
```

或单独提交纯 self-play：

```bash
bash examples/social_mixed/start_training.sh h200-141 selfplay
```

H200 每作业一张卡；h100-96/h100-47 每作业两张卡。作业排队或运行时不要修改该 worktree。提交时固定 SOCIAL_SOURCE_COMMIT，作业内再次检查 HEAD 和工作区；未提交代码会报错。模型、runs、submission 输出不进入 Git。依赖和模型继续使用既有 SoC 路径。

B/P-only 第三组使用 `bash examples/social_mixed/start_training.sh h100-96 bp`。它保留相同 B/P 题、奖励与组内采样，B/P 权重各 50%；训练不包含 self-play，共同开发评估仍包含完整游戏。`both` 仍只提交原先两组。
