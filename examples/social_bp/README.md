# B/P GRPO pilot（SoC，2026-09-14）

本目录包含可提交的冻结题库、训练配置和启动脚本。**尚未在 SoC 执行 GPU 更新**；本地已完成逐题 solver/native 审查、真实 tokenizer 检查和配置解析。服务器启动会再次检查依赖、原生工具 parser、数据哈希、GPU 映射和实际 optimizer 更新次数。

## 本轮固定内容

- `data/tasks.jsonl`：256 train + 64 validation + 64 test；每个 split 的 B/P 各一半。按原生游戏结构分为 42 / 12 / 12 个互不重叠的家族。重命名和相邻 checkpoint 不跨 split，旧 probe 的五个家族只能进入 train。
- Train B：formation 48、maintain 32、update 48。集合大小 1/2/3 分别 58/38/32；多元素且有明确 favored 10 道，集合不变而 favored 改变 2 道，直接读取新真值 9 道。
- Train P：complete、uncertain、result_use、information 各 32 道。调查正反例各 16 道；7 道正例严格提高自身收益，4 道反例仍有后续机会。16 道定性 belief 题在记录的宽语义范围内具有稳健的可接受行动集合。
- 每步 16 题（8B/8P），每题 8 次独立首次回答；100 步上限，每步恰好一次 Adam 更新。B 内 3 formation + 2 maintain + 3 update；P 四池各 2，每步调查正例和反例各 1。
- 难度按每 10 步、每个 B/P 各 80 题兑现配额：初始 56/20/4，允许进阶后 32/40/8，再到 16/40/24。B/P 独立进阶；连续两次验证主练层非直接读取题正确率 ≥60%，对照和关键能力没有明显退步才升级。仍保留困难题探索，不按 base model 答错删除题目。
- 原生工具作答；正确 1，错误/截断/格式失败 0。没有纯文本 JSON 恢复、作答 retry、长度惩罚、重复惩罚或全错组替换。基础设施异常终止当前运行，不补一个 0 混入 group；本版也不自动重试基础设施请求。
- LR 1e-6，warmup 5，clip .2，KL .01，temperature .8；response 1024。最长真实 prompt 1894 tokens，4096 上限不变。
- step 0 和每 10 次更新验证一次，每题 4 次。保留最近两个完整 checkpoint 和按验证集选择的最佳模型权重；宏平均提升但关键对照下降超过 10 个百分点时，不替换最佳模型。训练完成后另跑一次 test，每题 8 次，不用于课程反馈。

`data/solver_audit.json` 给出全部 384 题的逐题记录：306 个原生求解根，120 个旧 belief 复核；296 题通过信息相容的独立逆推检查，159 道 P 通过独立末轮收益检查。其他题的标签仍是针对可复现的选定伙伴策略，不声称该策略唯一。语义去重与抽样模拟在 `data/sampling_audit.json`。查阅题面见 [prompt_examples.md](prompt_examples.md)，renderer 在 `training/b_sft/social_prompt.py`。

这些是教学残局，采用 ALL_OF、每人一次私有 investigate，遵循原生合法动作。最短的部分调查正例跨 round 边界，允许的剩余顺序是 learner、learner、partner；每个原始 round 每位玩家仍各一次。它们不证明固定顺序任意长局都值得调查。没有修改 outcome self-play 的生成分布或训练配置。

## 上传

将本轮相关代码和本目录（包括 `data/`）随你的正常 Git 提交推送。`new/local_data/` 是本地生成/搜索记录，不需要上传；`data/generation_provenance.json` 保存来源哈希，冻结题本身包含重建标签需要的信息。已有其他工作区修改需按你的提交范围处理，不建议直接 `git add .`。

服务器在仓库根目录执行 `git pull --ff-only` 后，先新建独立环境。不要安装到之前用于 probe 的 vLLM 0.28 环境：ROLL 此路径使用 vLLM 0.8.5.post1。

```bash
bash examples/social_bp/setup_env.sh
```

默认使用 `python3.10` 创建 `$HOME/tmp/marshal-bp-grpo`；可用 `BP_SETUP_PYTHON` 和 `BP_TRAIN_ENV` 更改。脚本拒绝修改已存在的环境。PyTorch AdamW 路径避免可选 FusedAdam 的 JIT 编译，不改变已有训练配置的默认 optimizer。

## 启动训练

默认模型路径为 `/home/e/e1300530/models/Qwen3-4B-Instruct-2507`。如需替换本地模型位置：

```bash
export BP_MODEL=/home/e/e1300530/models/Qwen3-4B-Instruct-2507
sbatch examples/social_bp/sbatch_train.sh
```

申请同一节点 6 张 `h100-47`：4 张训练、1 张 rollout、1 张 reference。使用 Slurm 分配的逻辑卡序号，不绑定机器上的固定物理卡。每卡需至少 40 GiB；8 小时是任务时限，不是运行耗时估计。环境路径变更时同时设置 `BP_TRAIN_PYTHON=/你的环境/bin/python`。

每次使用新的 `runs/bp_grpo_pilot/$SLURM_JOB_ID/`。脚本不覆盖旧 run、不启动独立 OpenAI API server、不全局 `ray stop`。启动前校验失败会停止；第一轮更新还会校验 DeepSpeed 的真实计数是否增加 1。该 GPU 路径仍需在 SoC 实际验证，不能把本地检查等同于端到端训练成功。

主要输出：

- `run_manifest.json`、`export/manifest.json`：实际配置、依赖版本、源文件和数据哈希。
- `bp_sampling.jsonl`、`bp_training.jsonl`：每步选题、分层正确率和全错/混合/全对 group 数。
- `bp_validation.jsonl`：分池、分难度、错误全集、误缩集、favored-only、调查正反例、定性 belief 和截断统计。
- `native_reward_calls/*.jsonl`：原始生成 token、文本、原生工具提交及评分；截断使用引擎的真实 finish reason。
- `checkpoints/`、`best_model/`、`best_checkpoint.json`：最近两个完整训练状态、最佳权重及选择依据。

优先在第 30 步查看趋势；若某层持续全错，检查是否缺少可采到正确答案的桥梁，不能用总平均分掩盖它。

## 最终 held-out test

训练完成并冻结模型选择后，用一张卡运行一次：

```bash
export BP_TEST_MODEL="$PWD/runs/bp_grpo_pilot/训练任务号/best_model"
sbatch examples/social_bp/sbatch_test.sh
```

结果在 `runs/bp_grpo_test/测试任务号/`，共 64×8=512 条首次回答。该程序没有 optimizer，不写课程状态。不要用 test 分数选择 checkpoint 或调课程。

## 本地复核与边界

```bash
python -m training.b_sft.social_bp_grpo --data examples/social_bp/data --validate-only
python -m pytest -q training/b_sft/test_social_bp_training.py training/b_sft/test_social_b_grpo.py
python -m training.b_sft.audit_bp_pilot \
  --tasks examples/social_bp/data/tasks.jsonl \
  --tokenizer "$BP_MODEL" --out /tmp/bp_solver_recheck.json
```

原始 SoC 错例回放测试需要本地下载的旧结果；没有该文件时只跳过这一项。数据与训练信号的其他检查使用已提交题库。

这轮是学习趋势 pilot。难度分层是结构和推理依赖的初始近似；尚未验证模型能够按该曲线学会，更不保证 100 步收敛。4 人长局、全部 favored 反转方向和更复杂联合 belief 不属于本轮开训门槛，仍需之后扩展。
