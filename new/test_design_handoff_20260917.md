# 最终 test 场景设计前的交接记录

记录日期：2026-09-17。本文件保存前一阶段事实、用户决定和未解决问题；不代表最终 test 设计已确定。接下来任务转为设计最终测试场景，不要自动继续训练扩展、提交作业或重写 teacher。

## 1. 用户已经确定的研究边界

- 游戏只包含 **全 binary** 或 **全 linear** 的目标完成规则。用户明确要求排除一局中两种规则并存的 mixed 游戏，已经从活跃训练、验证、测试与 self-play 配置中删除。
- **Mixed 训练组**仍保留：它指 B/P + self-play 的训练混合，和 mixed 游戏规则完全不同。
- Binary 有多个承诺共同完成目标的互补收益；linear 的终局效用可拆成每个承诺的固定加性贡献，但仍有对手回应、时序与信息问题。测试应分别报告 binary/linear，不能只给合并均分。
- 用户认为读状态、识别标识符本身属于模型能力。不要用 grounding-assisted 条件替代真实任务，也不要只在合法回答子集上报结果。
- 用户不接受通过 `goal_`/`commit_` 前缀重命名来解决 grounding。
- 必须解决“未知就 INVESTIGATE”的简单策略。应同时测该调查、不该调查（deadline/机会成本）、调查目标选择、答案利用；单看调查率下降不是成功。
- 用户希望细分监督引导 reasoning pattern，再由 self-play 帮助适应互动；从未认为精确 teacher 标签可以解决一切。
- 用户明确表示没有时间再跑小规模训练能力实验，要求直接接通完整训练。不要未经要求恢复这个前置实验。

## 2. 当前本地 Git 状态（刚核对）

- 仓库：`/Users/bruce/MARSHAL`，当前分支 `new`。
- HEAD：`cc3eaef Add B/P only`。
- 本地缓存的 `origin/new` 相比 HEAD 落后 1 个提交；本次未 fetch，不能据此断言实时远端状态。
- 写本文件之前工作区 clean；本文件是新加入的交接记录。
- 前序提交：`9eedd0b Exclude mixed scoring and connect binary-linear full training`；`a629e8c Merge remote-tracking branch 'origin/soc-runtime-fixes' into new`。
- 用户最新说远端又有一些修改，尚未提供远端 `git status`、所在分支或新 commit。不要直接 pull 覆盖、不要 reset --hard，也不能断言这些修改已合并。
- 已向用户建议：远端先把重要修改 commit/push 到 soc-runtime-fixes，本地保存自己的修改后 fetch/merge，再 push new；远端训练用固定 commit 的独立 worktree。
- 上次 merge 的处理：备份本地 tracked 修改，stash，fetch/merge origin/soc-runtime-fixes，再 stash apply；无冲突，保留两边修改。备份 `/private/tmp/marshal-pre-runtime-merge-krsl4avm`，当时保留了 stash，当前是否仍存在未重新核对。
- 那次合入的 4 个提交包括 Transformers 5 chat template 输出适配、NumPy 2 的 np.product 兼容、Torch checkpoint writer 兼容、取消首步强制 checkpoint。

## 3. 活跃数据与结构划分

唯一当前数据入口：`training/social_mixed/core.py` 的 `DATA` 指向 `examples/social_mixed/data_binary_linear_v3`。

| 数据 | binary | linear | 合计 |
|---|---:|---:|---:|
| B/P train | 278 | 148 | 426 |
| B/P validation（开发） | 248 | 27 | 275 |
| B/P test | 23 | 21 | 44 |
| self-play train 配置 | 48 | 48 | 96 |
| self-play validation 配置 | 16 | 16 | 32 |

- 另有 4 道 linear diagnostics；没有独立 self-play test 配置文件。
- Train 内核：B1 104、B2 52、B3 58、P1 72、P2 56、P3 24、P4 60。
- Train/validation/test 合计各自包含 28/15/11 个依赖几何家族（计入 self-play）；当前审查未发现跨集合几何重叠。
- `structure_coverage.py` 精确枚举小图的玩家/每位玩家承诺/目标重命名，保留重复目标。为防止变体冒充新结构，家族归并忽略 scoring、时序、偏好世界和背景。它不是对所有推理语义的完美刻画，也不能把配置数当作独立结构数。
- 44 道现有 test 是 v2 的 65 道过滤 mixed 后所得；v2 来自已有 test 来源，候选在重求解前冻结，未使用本次模型结果筛选。但这些原始来源过去是否曾参与评估或指导修改，**尚未独立核实**。因此不能把它直接宣传成历史上从未使用的最终测试。
- 本轮删除 mixed 时保留题的输入、标签、ID、split 完全不变。删除 B/P train 16、validation 26、test 21；self-play train 48、validation 16。
- requests_train/validation/test 已重建，和保留题一一对应；manifest 更新哈希、数量与来源。P4 调查—答案利用链接完整。
- 历史 v1/v2 数据仍用于追溯与复现；当前训练不读取它们。
- 当前已使用的诊断与开发题不可重新宣称为新的盲测场景。

相关文件：
- `training/social_mixed/prepare_binary_linear.py`：过滤 v2，拒绝覆盖既有 v3。
- `training/social_mixed/scoring_scope.py`：检查实际目标 binary 字段，拒绝混合规则或元数据不一致。
- `training/social_mixed/structure_coverage.py`：几何归并审查。
- `training/social_mixed/preflight.py`：CPU 数据哈希、采样覆盖、结构隔离检查，不训练或 rollout。
- `examples/social_mixed/data_binary_linear_v3/{manifest.json,structure_audit.json,p4_links.json,README.md}`。

## 4. 三个训练组与运行设置

| 参数名 | 训练样本 | loss 权重 |
|---|---|---|
| mixed | B、P、self-play | 25%、25%、50% |
| selfplay | self-play | 100% |
| bp | B、P | 50%、50% |

- B/P-only 仍是二值任务奖励下的 GRPO，不是答案 token 的监督交叉熵 SFT。
- B/P 每题同次生成 8 个回答，按题分组计算 advantage；不是更新模型后连续复习 8 次。
- `bp` 训练路径不访问 self-play reset、不启动 Episode；开发评估包含完整游戏，与另外两组一致，评估不进梯度或训练 token。
- 三组使用同一本地基础模型 Qwen3-4B-Instruct-2507；seed 默认 42；总预算各 6,553,600 训练响应 token。
- Mixed/SP-only 的 65,536 tokens/update 是软收集目标，不能当成实际批量上限或“100 步预算”。
- 训练每批一次 optimizer update；默认安全上限 1000 updates；累计真实训练响应 token 达到预算后结束。
- `bp` 每步只取当前调度的完整 B/P 对照组，不凑齐 65,536 token，不补游戏，因此同总 token 下更新次数与 Mixed 不同。
- 三组的周期开发评估均为 33 道 B/P 题 × 2 次，加 self-play 验证。每 10 步以及正常训练终止时执行。
- 首步强制 checkpoint 已删除。每 10 步、结束/中断仍保存。
- 用户要求 `bp` 只保留最新一个完整 checkpoint；新文件完整写入后删除旧的。Mixed/SP-only 保留最新两个。
- token/arm/硬件布局/数据哈希的恢复检查保留。不能用失败的 mixed-851174 或旧数据包 checkpoint 接续新实验。

提交入口（SoC 已同步代码、干净独立 worktree 内）：

```bash
bash examples/social_mixed/start_training.sh h100-96 mixed
bash examples/social_mixed/start_training.sh h100-96 selfplay
bash examples/social_mixed/start_training.sh h100-96 bp
```

`both` 只提交前两组，不包含 bp。h100-96 每组 2 GPU；h200-141 每组 1 GPU。不是要求现在执行。

主要文件：`core.py`（采样/奖励分组）、`distribution_sampling.py`（课程）、`pipeline.py`（优化/评估/保存）、`run.py`、`checkpoints.py`、`examples/social_mixed/{common,mixed,selfplay,bp}.yaml`、`start_training.sh`、`submit_soc.sh`、`sbatch_train.sh`、`FULL_TRAINING.md`。

## 5. 预算与课程覆盖的已知问题：尚未修复

用户问为什么大约 40 步 token 就用满，以及题是否来不及复习。已核实并承认此前“约 100 步”的估计不成立：

- Mixed 先生成整批 B/P，然后仍启动完整并发 self-play（当前常见为 32 局）；达到阈值只停止补新局，已开始的局全跑完。
- mixed-851174：40 更新、6,199,298 tokens（预算 94.6%），均值 154,982/update。
- 本地下载的 mixed-853822 记录：19 更新、3,521,149 tokens，均值 185,324/update；这只是本地记录长度，不是远端最终运行状态。
- selfplay-853824 本地只有 2 更新，均值 188,054.5 tokens/update。
- 这些说明相同更新次数、总 token、实际计算量与有效梯度不是同一件事。

按当前 426 题采样器，seed 42 的静态调度：

| 更新数 | 未出现 | 仅出现一次 | 至少出现两次 |
|---|---:|---:|---:|
| 35 | 167 | 201 | 58 |
| 40 | 144 | 207 | 75 |
| 100 | 50 | 96 | 280 |

“出现一次”是进入一个训练批次（当批 8 回答）。此前只检查 512 步覆盖所有题，没有对齐实际 token 预算下的覆盖。曾建议重做课程调度/固定更新预算，但**用户尚未要求实施，当前代码仍未改成固定 100 步或压缩课程**。不要在最终结果解释中遗漏这一点。

## 6. B/P 接口与 grounding 的既有诊断

### 接口审查

- B 主要输出 `possible_preferences`、`favored`；P2 可以给定明确联合 belief，P3 使用定性区间稳健规划。
- 同样的 possible/favored 不足以确定最优动作，原因包括概率强度与跨目标相关性。
- `new/bp_interface_audit_20260917/`：84 道 P2 终局独立收益检查，40 道 P3 检查；28 个同 B 标签对照中 12 对可接受动作不相交。这些有背景重复，不能当 12 个独立结构机制。
- 原 P2 的显式 belief 常是人为给定，并非该自然历史下 teacher 的 posterior；不能把分别提升的 B/P 分数直接视为组合能力已成立。
- 未把数值 posterior/likelihood 强制加入 B 输出，也未强制 self-play 采用 B→P 两次调用。

### 同历史组合诊断（已经用过，属于开发）

目录 `new/bp_composition_diagnostic_v1/` 与审查 `new/bp_composition_run_review_20260917/`。

- 2 个结构族 × 自愿历史/强制 setup × B/P_gold/P_infer，共 12 请求，每题 8 次，96 调用。
- B 7/32；P_gold 0/32；P_infer 2/32。P_gold 全合法但 29 次 INVESTIGATE、3 次 PASS、0 OFFER。
- 不能把这个结果单独归因于 B→P 接口；P 在给定正确 belief 后也没完成任务。
- 存在把需求承诺当偏好、误读承诺添加规则、误认为最后一轮 OFFER 不会获回应等现象。
- 旧 grounding 审查：107 次 P 格式失败中 105 次混淆 goal/commitment 标识。高合法率也可能来自一直 PASS/INVESTIGATE，不能证明会正确 grounding OFFER。
- 用户强调真实读状态能力；不将辅助解析条件当主要解决方案。
- 旧组合包依赖哈希冻结较广；源码变化可能让本地加载失败。重放旧结果优先使用其 `remote_bundle/`，不要重新生成旧包掩盖版本变化。

## 7. Teacher 审查已完成的两项与限制

参考 `new/teacher_robustness_20260917/{review.md,selection.json,results.jsonl,summary.json,provenance.json,audit.py,test_audit.py}`。

### 行为噪声

- 固定 8 道 B1/B2 训练开发题，按实际合法行动数使用 `(1-epsilon)*pi_T + epsilon*Uniform(legal_actions)`，重算自愿历史似然。
- setup 不作为自愿行为证据；仍保留公共/私有事实、自己的偏好和先验约束。
- epsilon = 0、0.001、0.01、0.05、0.1。
- 4 道原缩集题在任何所测正 epsilon 下都恢复为三种偏好有正概率；4 道原全集题支持不变。
- 全部 8 题 favored 在范围内不变。原标签排除的后验质量最大值：epsilon=.001 时约 .0500%；.01 时约 .5013%；.05 时约 2.5316%；.1 时约 5.1282%。
- 例：原 avoid=1，在 epsilon=.01 时变为 want≈.002506、neutral≈.002506、avoid≈.994987。严格支持不连续，不意味着行为证据整体失效。
- 这些是指定噪声模型下给定历史的条件后验，不是 LLM 的实测错误率。没有重新求解噪声均衡，也没有重算噪声对手下 P 的最优策略。

### 初始化/更新顺序

- 固定 14 题、8 几何：8 B1/B2 + 6 binary P4。每题默认 uniform/synchronous、first、last、按所有玩家正序/逆序更新，共 70 次求解。
- 默认 14/14 成功并重现生产标签；替代 56 次中 52 成功，全部概率策略与标签同默认。
- 4 次 first 初始化循环（P4 acquisition、target_selection、ordinary_alternative、answer_use），记失败，不算另一种有效策略。
- 策略比较用实际概率数组，不比较混入求解器元数据的 policy hash。
- 仅有限样本的阴性发现，不证明均衡唯一。尚未改变回应利他平局规则、近优行为；这些仍未检查。
- 保留精确 teacher，不修改生产 solver 或标签。真实模型面对已告知/未告知的行为模型变化能否调整推断、self-play 是否帮助，尚无此次实验结果。

## 8. 最终测试设计的未决问题（下阶段讨论，不是既定方案）

- 最终 test 要支撑的主张：指定 teacher 下的推断？不同对手下的适应？完整互动的收益改善？应先明确，不能用一个分数混合。
- 当前 44 道结构 test 不能自动等同于将要设计的最终场景。需要新场景来源、冻结流程和历史污染审查。
- OFFER 信息获取仍缺专门场景：不同提案引发不同信息价值，反馈确实改变后续决策，计入提案/承诺/时间成本。INVESTIGATE 成绩不能替代这项证据。
- 同时保留调查正例、deadline/机会成本反例、答案利用对照，避免固定 INVESTIGATE 或固定不调查策略得高分。
- 结构家族、偏好世界、同局玩家及重复 rollout 有相关性；大量运行次数不是大量独立结构。报告粒度和置信区间需匹配。
- 需要基础未训练模型的评估基线，不需要为此额外训练。三组训练比较仍不完全排除 grounding 练习量混淆。
- B/P-only 在相同 token 下有更多 B/P 练习；三组比较是固定预算方案比较，不自动证明严格的组合增益。
- 最终测试不可用于挑场景、调标签、反复选模型后仍宣称盲测；开发场景与最终场景要区分。

## 9. 服务器与操作约束

### SoC：正式训练

- 账号 e1300530，登录 xlogin.comp.nus.edu.sg，常经 stujump.comp.nus.edu.sg。
- Conda：`/home/e/e1300530/tmp/marshal-vllm09`，路径名不等于 vLLM 版本；已适配 vLLM 0.28 V1。
- 模型：`/home/e/e1300530/models/Qwen3-4B-Instruct-2507`。
- H100-96 默认 gpu-long，2 GPU，最长 72h；H200-141 默认 gpu，1 GPU，最长 3h，可能需原生 checkpoint 恢复。
- 本地此前尝试 SSH 被跳板机 password 认证拒绝，没有代用户提交真实作业。
- 旧运行时根因包括 log_probs.detach 共享存储污染（已改 clone）及 Transformers 5 RoPE 参数迁移导致 theta 回退（已修复为模型要求的 5,000,000）；修复诊断支持重开训练，不使失败 851174 变成健康结果。

### chenjiahao：rollout 评估

- `chenjiahao@36.102.215.18`，port 2201；本地 key `/Users/bruce/.ssh/id_rsa_dgx2`。
- 仓库 `/raid/chenjiahao/mas`；Python `/raid/chenjiahao/conda_envs/mas/bin/python`。
- 模型 `/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507`。
- 之前获准使用 GPU 6、7，但新任务不能假定仍空闲/仍被分配。
- 旧 rollout 环境是 V0/XFORMERS，与 SoC V1 训练环境不同；不能混用启动参数。
- 旧组合诊断 REMOTE.md 中有明确 bundle 上传和双端点命令；最终新场景需要另做评估包，不覆盖旧包。

## 10. 验证状态

- 去除 mixed 后，26 项相关 CPU 回归通过。
- B/P-only 接入：23 项 CPU/模拟提交测试通过，包括不启动训练 self-play、权重、八重复、共同验证。
- B/P-only 保留 1 checkpoint：4 项保留/模拟提交检查通过，新文件未 COMPLETE 时保留上一个完整 checkpoint。
- 本地缺 Hydra，真实配置构造测试未能运行；SoC 提交脚本会在服务器检查三个训练组配置和依赖后再 sbatch。
- 本文中的检查不是新的 GPU 训练或模型最终测试结果。没有证据表明新加 B/P-only 已由助手提交到服务器。

## 后续决定：A/C 优先及 oracle 信息边界

- 用户将包 B（R/G/GB）降优先级；先做 A 完整局与 C2C 链路。
- A 增加 LM 对相同可见信息 teacher 的对局。用户已明确排除全知 oracle；teacher 只能访问公开历史、自己的偏好和自己的调查结果。
- C2C 四名玩家默认全部调用本地模型，环境自带谈判摘要模型也路由本地 Q0，保留显式 API 配置，不自动回退云端。
- 新实现位于 `examples/final_evaluation/`，目前只接受开发计划，没有运行正式测试。
- 远端原 `third_party/cooperate-to-compete` 没有 `.git`；`git -C` 实际发现 `/raid/chenjiahao` 的无关上级仓库。不能对其直接 fetch/checkout。准备脚本现已检查独立仓库根目录，并对非 Git 复制目录保留备份后建立固定 checkout。
