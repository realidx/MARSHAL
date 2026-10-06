# Consequence-selected slices versus complete self-play

This is the direct-action experiment defined in
[`new/strategic_game_slices_checkpoint_20261001.md`](../../new/strategic_game_slices_checkpoint_20261001.md).
The intended comparison has two independent training arms, **slices** and
**selfplay**. Both start
from Qwen3-4B-Instruct-2507 and use the same native `act` tool interface,
optimizer, four replicas per group, and generated-response-token budget.
There is no separate inference or conditional-planning supervision.

## 当前研究方向（2026-10-05）

**正在推进的新目标与可复现 checkpoint 见 [PROGRESS.md](PROGRESS.md)。**
当前任务是改进入口采样与信息依赖覆盖；下方各阶段报告均
保留原始口径，不能将历史条目直接相加作为当前进度。

**v2 的真实 D 结果已由用户提供：800 题，每题 8 次，共 6,400 条轨迹。**
模型为 **Qwen3-4B-Instruct-2507**，结果在
[2026-10-05 SoC 记录](../../new/strategic_slices_terminal_d_20261005/README.md)。
SoC 历史配置、离线打包、手动运行和
断点恢复见 [TERMINAL_D.md](TERMINAL_D.md)，配置在 `terminal_d_soc.json`。
原任务采用 16 并发，后续 completion-refill 使用 32 并发；输出上限 4096 tokens。
入口 `run_terminal_d.sh --check` 只做离线校验；`sbatch_terminal_d.sh` 留给用户手动提交。
候选生成阶段“不跑 D”的历史约束已转为“准备 D pipeline，但不自行提交任务”。

**2026-10-06 D 补跑入口更新：**使用 `terminal_d_soc_v4_delta.json`，自动锁定
v4 manifest 和 78 道待测题，保留 **32 并发、completion-refill-v1、4096 输出 tokens**。
`run_terminal_d.sh --config examples/strategic_slices/terminal_d_soc_v4_delta.json --check`
会报告 624 条轨迹；新传输包是 `strategic-slices-terminal-D-v4-refill32.tar.gz`。
旧默认配置仍对应 v2；完整手动提交与续跑命令见 [TERMINAL_D.md](TERMINAL_D.md)。

**2026-10-05 最新候选 v4：6 个强主动调查 family，仍为 100×8。**
[v4 审核](../../new/local_data/strategic_slices_oracle_consistent_candidates_v4/audit.json)
保留 100 个 parent、800 个 slices；用 6 个已独立复核的 acquisition parent 替换
6 个没有受保护信息案例的训练 parent，新增 48 题，其余 752 题与 v3 完全一致。
替换优先减少重复 family，并严格保持 player×proposal-count×split 配额：双人/三人
仍为 50/50，双人双轮 30、双人单轮 20、三人单轮 50；train/validation/test 不变。
原 10 组 entry-answer contrasts、4 个 collective controls 全部保留。

扩展实验在两个既有原型基础上，对三人原型的真实 goal requirements、goal mode
及合法 schedule 作结构变体。先按 player/action/goal 重命名去重，25 个 family
候选中 24 个认证成功、1 个超时，找到 4 个新强 acquisition family。加上两个原型
共 **6 个不同结构（5 个三人、1 个双人）**，均重载同一保存的 policy、重新认证并用
独立 scalar BR 复核 S。它们围绕两个基础机制，不应声称覆盖六种独立战略机制。
没有靠改 prior、添加 dummy goal 或 utility scaling 凑 family 数。

每个新 parent 保留 k=2/3 的两个主动调查窗口，共 **12 个 S>.05 的问题**，
S=.08333–.21429，均有 C>.1。其余六题按原始 oracle reach、未覆盖 actor/decision kind
和不同入口选择 k=1 问题。新题的 future-public-history channel 尚未测量，保持 null；
不会将已有答案 contrast 的集体 S 复制到 singleton。所有新增 family 因经过机制
校准只进入 train；新的强 acquisition held-out 覆盖仍待独立建设。

入口合同新增 `initial-terminal-local-decisions-v2`：在已完整认证的初态 terminal
tree 上允许更早入口，k 仍限 1/2/3；未展开的树或外生 prefix 不能使用此合同。
默认旧入口 API 仍为末 3 次 proposal，旧题记录不改。v4 的双人正例新增两个剩余
4 次 proposal 的入口窗口；放宽范围没有新增 equilibrium 求解，只重新度量入口。

相对真实 D 所用 v2，**722 题及 reference 完全一致、78 题需要补测**（v3 的 30 题
加本轮 48 题）。`D_reuse.json` 是可复用身份清单，没有伪造或合并模型结果。
补跑 CLI 支持 `--candidate-ids <D_reuse.json>`，恰好 78×8=624 条轨迹；subset IDs
进入 protocol identity，改变题目集合不能续跑旧目录。见 [D 补跑说明](TERMINAL_D.md)。
旧 v2/v3、真实 D 和原传输包保留。最终 100 个训练 slices 尚未按新 D 选定。
本轮 44 项测试通过；48 道新增题的 384 条 native mock rollout、全部 78 道待测题的
624 条 pipeline mock 均到达 terminal，完成后 resume 没有新增调用。
[校验记录](../../new/local_data/strategic_slices_acquisition_v4_validation/runtime.json)
同时记录 source snapshot 补充前后的 manifest identity 与完全相同的 runtime inputs。
这些是本地工程校验，不是模型 D 或训练效果证据。

**2026-10-05 前序改进：可选 generator 扩展与成对校准。**
`sample_parent(..., goal_structure='multi_action')` 现在可给一个 goal 增加同一玩家的
第二个 action requirement；默认仍为 `legacy`，旧 seed 的原始 parent identity 不变。
`training.strategic_slices.build` 的 config 可显式设置 `goal_structure`；现有 terminal
candidate pipeline 仍调用默认模式，已有冻结任务与数据不会因此被重写。
这个模式仅扩展 requirement 结构，不改变 preferences、type catalogue、prior、
回合顺序、binary/linear 类型或规则。没有合法扩展位置时返回相同 parent，不能算新样本。

[8 组 paired pilot](../../new/local_data/strategic_slices_goal_structure_calibration_v1/summary.json)
在求解前按结构可扩展性选定 seed，每个 arm 都从初态展开 native terminal tree。
旧模式和新模式各 8 个，分别 4 个通过认证；仅 **3 组双方都通过认证**。
已认证游戏中没有新的强主动调查案例。其余失败不能当作 S=0，更不能据此估计
可靠的产出率提升。这一结果说明扩展结构并不自动产生调查价值；payoff 冲突、
未知偏好与后续可行动机会仍需要共同校准。

本轮 40 项测试通过，包含旧 seed identity、成对修改范围、原生合法性和失败比较的
null 语义。正式 100-parent / 800-slice 数据和已有 D 未改动。
建议下一阶段先形成 5–10 个不同结构的强信息获取 parent family，逐一检查实际
answer-dependent action gap，再扩大候选池。对于已经完整求解的 parent，还应单独
评估是否将“剩余 proposal≤3”由硬门槛改为采样层：k≤3 的局部控制长度可以保持，
但允许双人四次 proposal 初态；这不会新增该 parent 的 equilibrium 求解，仍会增加
入口度量成本。当前入口合同尚未变更。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 new/local_data/solver_benchmark_env/bin/python \
  -m examples.strategic_slices.calibrate_goal_structure \
  --pairs 8 --seconds 45 --workers 2 \
  --output new/local_data/goal_structure_paired_reproduction
```

**2026-10-05 前序 native acquisition 小实验：两个完整初态正例。**
[搜索汇总](../../new/local_data/strategic_slices_native_acquisition_review_v1/summary.json)
记录 130 次尝试：15 个早期草案未通过 native 规则校验，已修正生成代码；其余
115 个合法游戏中 94 个通过完整树认证，21 个求解失败，失败者没有 oracle label。
这是定向搜索，不是对正式 generator 产出率的无偏估计。找到两个不同结构的正例：

| Native fixture | 完整节点数 | 入口剩余 proposal | k=2 C | k=2 S | full-terminal S |
|---|---:|---:|---:|---:|---:|
| [三人单轮](fixtures/native_acquisition_three_player.json) | 18,799 | 3 | .45581 | .08333 | .08333 |
| [双人双轮](fixtures/native_acquisition_two_player.json) | 143,014 | 4 | .37500 | .10714 | .21429 |

两者均从 native initial state 展开所有 action/response 分支，`cutoff_leaves=0`；
没有外生 prefix、叶子估值或事后删除 world。保存的同一 oracle 在初态以概率 1
选择调查，入口 reach 为 1。重载 reference 后完整 contingent deviation/local support/
response tie checks 再次通过；独立 scalar BR 复核 full/masked/no-query values。
这不是唯一 equilibrium 的证明。双人例的初态**不满足现行末 3 次 proposal 入口限制**，
故仅作机制原型，不能直接计入现行候选；三人例的 k=2/3 同时通过 C>.1、S>.05。

三人例调查 player 2 的 goal 1 后，player 1 提出同一份 offer；下一步的选择为：

| 私有答案 | Q(REJECT) | Q(ACCEPT) | 唯一最优 response |
|---|---:|---:|---|
| AVOID | -.08333 | -.33333 | REJECT |
| NEUTRAL | -.66667 | -.33333 | ACCEPT |
| WANT | -.66667 | -.33333 | ACCEPT |

三个答案各占 1/3，full value=-.25；遮住答案但保留调查动作、成本及 partner policy，
最佳 value=-1/3，因此 S=1/12。这里是减少损失的决策；不是要求 terminal utility 为正。
k=1 的 S=0，因为该窗口尚未包含使用答案的 response；k=2 已保留全部信息增益。

[六个控制实验](../../new/local_data/strategic_slices_native_acquisition_controls_v1/summary.json)
全部从初态重新求解并通过认证：三种非均匀 prior 的 S 为 .0625/.0625/.125；
把关键 binary goal 对 focal 两个动作的联合要求缩成一个动作，S=0；将该 goal
改成 linear，S=.02778；给原来只有 AVOID 的 goal 补上公开 WANT，S 仍为 .08333。
这些是所选 certified profiles 下的对照，包含重新求解带来的 equilibrium-selection 变化。
prior 变体不作为不同结构的 parent 凑数。

**生成器的具体缺口**：`sample_parent` 每个 goal 从每位参与者只取一个 action，
而原生规则允许同一 goal 要求同一玩家的多个 action；两个正例都包含这种结构。
三人例的局部消融支持保留这种联合要求，但不能推出它是所有正例的必要条件。
公开 WANT 本身并没有在这个控制中消灭信息价值；不能把它定为统一原因。
该轮实验未修改正式 generator、100 个 parent、800 个候选、D 结果或 transfer bundle；
后续的可选 generator 扩展见上方，默认行为和冻结数据仍保持原样。
36 项测试通过，包括从初态重新求解三人正例的 regression test。

复现工具：`search_native_acquisition.py`（记录所有成功和失败），
`verify_native_acquisition.py`（重载已保存 reference 独立复核），
`ablate_native_acquisition.py`（六个原生控制）。例如：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 new/local_data/solver_benchmark_env/bin/python \
  -m examples.strategic_slices.search_native_acquisition \
  --geometry three_targeted --seed 15 --count 1 --workers 1 --seconds 60 \
  --output new/local_data/native_acquisition_reproduction
```

**2026-10-05 前序 game-mechanism 诊断：不能只归因于调查占用一回合。**
[诊断记录](../../new/local_data/strategic_slices_mechanism_diagnostic_v1/conclusions.json)
选取五个已有 entry-answer 正值的双人 parent，以及 early audit 的唯一弱正值三人 parent。
保持 partner profile 不变，在每位玩家首次 proposal 免费提供一个真实偏好：249 个
入口×slot 比较中仅 3 个正值，最大 .03661，均在该三人 parent。再免费提供所有
partner 的完整偏好，五个双人 parent 的所有早期入口仍无增益，三人 parent 最大 .09117。
这是信息干预诊断，不是重求免费调查规则下的 equilibrium，也不是随机 parent 产出率。

规则检查确认：100 个 parent 均允许初态单边增加 commitment 的 offer；REJECT 同样
消耗 proposal turn，但不产生 commitment 或额外拒绝罚分。只有每笔新增承诺上限，
没有行动互斥或总承诺预算。37 个纯 linear parent 的效用可精确展开为各 commitment
的固定加权和（19,992 个 payoff 对照，最大误差约 2.22e-16）；另有 42 个 binary、
21 个 mixed parent。generator 还保护每个 goal/每个 player 的部分公开 WANT，
并重复同一轮换顺序；这些结构没有保证未知信息会改变最优策略。
以上规则特征是候选解释，尚未通过逐项干预量化各自的因果贡献。

旧调查 fixture 在外生 PASS 后重求仍有 S=.25；完整初态两次搜索均未通过认证，
因此其正值入口的完整 oracle reach 仍未知。合法的轮换顺序对照中，固定交替版本
通过完整 terminal 认证且无调查严格优势；另一侧未认证，不能声称回合顺序的因果
效应已证实。更短但不满足每轮每人一次 proposal 的尝试被原生校验拒绝，未计作游戏。
实验脚本：`investigate_game_mechanics.py`、`investigate_schedule_controls.py`。
34 项相关测试通过；正式游戏规则、候选、reference 和 D 均保持不变。

**2026-10-05 early-round 调查检查已完成。**
[完整结果](../../new/local_data/strategic_slices_early_investigation_v1/summary.json)
覆盖原 100 个 parent、250 个 parent/player 组合的首次 proposal，共 8,357 个可达
information sets，包含旧三次 proposal 邻域排除的 88 个初始信息集。没有入口 cap
或 C 过滤；focal 对所有剩余 proposal/response 优化到 native terminal，partner
保留原 reference。与冻结 focal continuation 的 Q 最大差异仅约 1.78e-15。

最佳调查相对最佳非调查行动：2,573 个信息集打平，5,783 个较差，仅 1 个小正值
（.0138533），没有 >.05 的案例。按原始 reach 加权并等权汇总 parent/player，
约 40.36% 打平、59.50% 较差、0.13% 为小正值；不能把信息集数量当成采样频率。
禁止 focal **后续所有调查**后，8,356 个信息集的最佳价值不变；同一个小正值案例
下降 .0138533。其中 528 个入口同时满足仍有未知偏好、调查后还有一次自身 proposal，
仍全部没有严格调查优势。

唯一小正值来自三人单轮开局，value 从 .03410494 到 .04795821；独立删除调查分支
重算得到相同结果。但保留该 INVESTIGATE 动作并遮住其答案直到终局，value 仍为
.04795821，**S=0，强制同一 query 后的 full/masked value 也相同**。
它证明的是调查动作引起的交互/continuation 差异，不是利用私有答案的收益。
检查见 [answer masking](../../new/local_data/strategic_slices_early_investigation_v1/positive_answer_mask_check.json)。
因此当前 parent 集合尚未提供强的主动信息获取案例；补入已有答案对照并未解决此问题。
这不是“看得不够深”的测量结论，也不推广到其他 parent 或其他 equilibrium profile。
本次没有修改数据集、游戏、oracle 或模型任务；31 项相关测试与独立子树检查通过。
复现入口及指标定义见 [early-round audit](ENTRY_INFORMATION.md#early-round-investigation-audit)。

**2026-10-05 新候选 v3：补入已有 private answer 的信息—行动对照。**
[v3 审核记录](../../new/local_data/strategic_slices_oracle_consistent_candidates_v3/audit.json)
仍是 **100 个原 parent，每个 8 题，共 800 题**；parent、reference、prior 和 split 均不变。
对原 100 份 oracle 的全部可达末段入口扫描，测得 9,209 个已有答案对照组，其中
220 组 S_entry_answer>.05，分布于 10 个 parent；原 800 题没有保留这些正值组的成员。
每个符合条件的 parent 保留一个完整对照组，最终为 **10 组、30 个单独题目**，
其中 train 9 组、test 1 组，validation 尚无这类强正值覆盖。
保留组的条件性 S 为 **.05357–.31884**；全扫描最大 .44444，未按最大条件 S 单独挑选。
先按原始 reach×S 排序，再保留全部答案分支并尽量少替换旧题。

这是入口已知答案的价值，不是主动调查的收益；同组题面的 private answer 不同。
集体 S 只写入 `entry_answer_relations.jsonl`，不复制成每个 singleton 的 S。
原 C>.1、S>.05 门槛不变；独立 masked DP、member C 与 prefix posterior 复核通过。
**770 题内容完全不变，30 题替换为新入口并待测 D**；对应关系见 v3 的 `D_reuse.json`。
原 v2、其 D 结果及传输包保留，未提交新任务。k=1/2/3 变为 383/263/154，
proposal/response 为 411/389；双人席位仍各 200，三人席位分布不变，四个 collective
public-history controls 全部保留。定义和局限见
[entry-answer channel](ENTRY_INFORMATION.md#existing-private-answers-one-decision-entry-contrasts-2026-10-05)。

复现（使用带 NumPy/SciPy 的 Python；输出新目录）：

```sh
python -m examples.strategic_slices.audit_entry_answers --output NEW_AUDIT_DIRECTORY
python -m examples.strategic_slices.retain_entry_answer_contrasts \
  --audit NEW_AUDIT_DIRECTORY --output NEW_CANDIDATE_DIRECTORY
```

**历史 checkpoint v2（2026-10-05）：每个 parent 恰好 8 个。**
[oracle-consistent candidates v2](../../new/local_data/strategic_slices_oracle_consistent_candidates_v2/REPORT.md)
包含 **100 个不同 parent、62 个 structural families、800 个候选窗口**。
其中 30 个双人两轮、20 个双人单轮、50 个三人单轮；parent 与 split 保持不变。
从已审核的 [v1 原池](../../new/local_data/strategic_slices_oracle_consistent_candidates_v1/REPORT.md)
1,596 个候选中选取，依次平衡每个 parent 的 player、k、proposal/response 数量，
再提高 player×k、剩余 proposal turn 和不同入口的覆盖；四个 collective control 全部保留。
结果 k=1/2/3 为 **365/279/156**，proposal/response 为 **396/404**；
双人位置 0/1 各 **200** 个，三人位置 0/1/2 为 **136/130/134** 个。
选择脚本为 `rebalance_candidates.py`，完整规则与逐 parent 记录在新池中。
800 条候选内容逐条与原池完全一致，100 份 parent/reference 记录及 reference 文件保持一致。
原池完成的 100 份 reference 独立认证、1,608 个成员 C/posterior 复核、104 条 S 复测
作为原始审核证据保留；本次验证子集继承关系，没有重新运行 solver 或 C/S。
此前 62 项相关测试通过。**D 未运行，最终 100 个 slices 尚未选择。**
覆盖仍有限：没有三人多轮，也没有已测 S>.05 的候选；四条 collective 记录具有
约 .015 的正信息价值。其余未测的 entry-history channel 保持 null，不能解释为零。

当前重新检查的是 **slice generation 与 C/S 筛选**，尚未进入新 supervision 的设计。
目标是原游戏中局部可理解的战略片段；下方 production v4 是已冻结的 bounded
baseline，不代表其 cutoff C/S 已被认可为 terminal C/S 的替代。

**当前生效的目标与约束：** 先收集 **100 个不同 parent game**，每个保留多个有代表性的
slice 入口和 k 窗口；未来计算 D 后才确定最终 100 个 strategic game slices。
当前改进候选覆盖，不自行提交新的 D 任务，也不提前压成每个 parent 一个 slice。

所有候选必须共享同一种 terminal oracle 的行为逻辑：每个 parent 只使用一份从初态
完整展开至 native terminal 并认证的 profile。入口必须在这份 profile 下具有正概率；
belief 由同一 profile 的 prefix likelihood 与自身信息条件化得到；partner 与 k 后的
focal continuation 继续使用原 profile。不得将随机 prefix 后重新求解的局部 reference
当作整局一致的替代，也不能仅凭“同一个 solver”认定两份 equilibrium 相同。

下文旧 unified v1 的 **47 parent / 345 candidate** 是历史性混合口径，**不再作为该目标
的合格进度**：其中 10 个长 parent 的外生-prefix reference 不符合上述约束。旧文件
保留供诊断，新的合格集合单独生成和审核。入口的 proposal/response、focal 在剩余
schedule 中的位置、k 与实际 decision capacity 都须单独记录。

**以下为本轮优化前的 solver 成本诊断；当时暂停了短 parent 扩充。**
小规模 [current solver / Gambit sequence-form LCP 对照](../../new/local_data/strategic_slices_solver_comparison_v1/REPORT.md)
未发现直接替换 solver 的收益：两个原有单轮 case 的 current solver 在 .1 秒内完成
求解及认证，Gambit 16.4.1 LCP 均达到 30 秒搜索上限；两轮 case 41/47 的 dense
tableau 单矩阵预计需要约 308/419 GB，预检查后跳过，不能记作 LCP 超时或无解。
两轮 case 47 在 120 秒预算内约 90.6 秒结束但未通过认证，其中 16 次候选认证共
约 69.8 秒；case 41 则完整通过。优先优化认证实现与候选筛查，而非仅延长预算。
这些是少量固定案例的实现诊断，不代表所有 sequence-form 方法，也不说明模型学不会。
实验未更改游戏、C/S 或认证门槛，未运行 D，未将实验 reference 纳入数据集。


已完成 [terminal-only 入口采样 pilot](../../new/local_data/strategic_slices_terminal_entry_pilot_v2/REPORT.md)：
在 6 个已有训练父游戏中筛查 144 个剩余 2/3 次 proposal 的入口，求解 12 个采样入口及
2 个独立列出的调查对照入口，全部到真实 terminal、通过认证和 native audit，总耗时
约 5.37 秒。沿用 C/S 门槛，parent cap 前得到 34 个候选 slices，其中 4 个 S-positive
全部来自调查对照；采样入口贡献 28 个 S-zero slices（24 个集中于同一入口）。
最小树倾向于选择承诺已完成、调查机会已耗尽的局面，下一步需按未解决的战略结构分层，
不能只按树大小挑选。该 pilot 不估计随机父游戏产出率，不是新冻结数据，也没有运行 D。
复现脚本：`examples/strategic_slices/terminal_entry_pilot.py`。

后续 [v3 分层采样](../../new/local_data/strategic_slices_terminal_entry_pilot_v3/REPORT.md)
将范围改为距真实 terminal 剩余 **1/2/3 次 proposal**（完整包含 response），
按 commitments、剩余调查预算、条件性未知偏好和后续行动机会分层；树大小仅作预算门槛。
增加不依赖隐藏偏好的 PASS/REJECT-biased 路径，以保留部分未解决的选择。
同一批 6 个父游戏筛查 412 个历史，选出 55 个不重复入口；51 个认证成功，4 个达到
6 秒 solver budget，未赋予标签。耗时约 30.42 秒，parent cap 前保留 274 个候选
slices，8 个 S-positive 分布在 4 个调查入口；其中 4 个 slices 来自自动发现的非预设
历史，另 4 个来自原有对照历史。随机父游戏仍未产生正 S，不能据此宣称机制覆盖已解决。
所有成功树的叶子均为 native terminal；正式 v4 数据、C/S 定义和门槛保持原样。

### 后续可靠性检查（2026-10-04）

- [完整 reference 与入口重求解](../../new/local_data/strategic_slices_terminal_reference_consistency_v2/REPORT.md)：
  6 个新的一轮随机小游戏中 5 个完成比较，1 个超时；另尝试的原始调查题完整树有
  143,014 个节点，超过本次 30,000 上限。使用完整 reference 行动概率产生的同一入口
  posterior，105 个信息集 × k 比较没有 C/S 或筛选变化，但全部不具正 S，不能据此
  认证调查机制的一致性。额外重建子树、移植原策略，验证 C/S 与 root Q 保持一致。
- [8 个新随机父游戏](../../new/local_data/strategic_slices_terminal_entry_fresh_v1/REPORT.md)：
  4 个双人、4 个三人，原始 3/9/27-world support 未缩减。72 个入口中 59 个认证成功，
  10 个达到时间预算，3 个未通过 reference deviation/tie checks；耗时约 61 秒。
  parent cap 前得到 333 个 C 候选，仍无 S-positive。失败入口不赋予标签。

结论仍是 pilot：中后段 terminal 求解可以产生 C 候选，但随机机制的正 S 覆盖、
调查题从初始游戏求解的一致性，以及 D/可学习性均尚未得到验证。

### S 的测量范围修正（2026-10-04）

此前的 S 仅测量未来 INVESTIGATE 答案的价值；“无正 S”不能解释为没有一般信息价值。
新增可选的 [public-behavior channel](../../new/local_data/strategic_slices_behavior_information_v1/REPORT.md)：
比较正常 public history 与只保留 focal 决策时物理观察、私有答案和自身观察/行动记忆的策略。
通过 sequence-form LP 跨历史约束信息集，保留 perfect recall，并独立 replay 验证价值。
该指标只测未来 transcript 超出物理观察的价值，不遮蔽入口信息或状态本身透露的信号。

`terminal_entry_pilot.py --behavior-information` 启用新版本
`query-plus-future-public-history-v1`，分别保存 `S_query`、`S_behavior`，使用二者的 max
执行正 S/长度增量筛选（不相加）。默认和冻结数据仍使用旧 query-only 定义。
8 项新增测试及 10 项 pipeline 回归通过；无 INVESTIGATE 的合成信号博弈测得 S_behavior=.5。
8 个真实父游戏的 28 个窗口复测仍无正 S_behavior，因此尚未证明原生数据产出改善。

### 原生非调查信息案例与入口集合（2026-10-04）

进一步检查发现单个已条件化入口会漏掉 **入口前公共证据**。新增入口集合对照：
在同一 retained observation 下，保留不同历史的联合 history/world 概率，再比较能否
区分历史。拒绝遗忘此前 focal 决策或合并重叠子树；完整 reference 与真实 terminal 不变。
定义与手算见 [ENTRY_INFORMATION.md](ENTRY_INFORMATION.md)。

[12 个新原生小游戏的检查](../../new/local_data/strategic_slices_native_entry_search_v1/REPORT.md)
有 6 个完整求解并认证、6 个超时。找到一个 **未发生调查的原生正 S 案例**：B PASS 与
B 向 C 出价被拒绝后，A 面对相同物理状态，却应选不同 offer。完整树 6,971 节点、
27 worlds；条件性 S_entry = **1/66 ≈ .01515**，由独立首步 action 枚举和 LP 双重验证，
参考再次通过完整 deviation/tie 认证。它低于现有 .05 门槛，不能列为 information_positive。

据此整理了 [38 个 entry-set review candidates](../../new/local_data/strategic_slices_terminal_entry_candidates_v2/manifest.json)：
6 个父游戏、4 个不跨 split 的 family，每个 parent 最多 8 个；train/validation/test
为 30/6/2 个集合，校准 family 只放 train。两条可检测正 S 记录是同一机制的 k=1/2，
并非两个独立案例。共享 S 属于整个入口分布，不能直接复制成每个历史的独立标签；
未测的 query/future channels 记为 null。该格式明确 `training_compatible=false`，
尚不是替换正式数据的冻结集，未运行 D；全部来自三人一轮小题，规模/机制覆盖仍有限。
24 项相关测试通过，并完成候选文件 hash、联合概率、C 加权恒等式和 family split 检查。

### 扩样与机制敏感性（2026-10-04）

此前 [entry candidates v4 报告](../../new/local_data/strategic_slices_terminal_entry_candidates_v4/REPORT.md)
汇总了新增 32 个随机父游戏与 14 个明确标注的同机制 prior/scoring 变体。
随机批次 16 个认证（8 双人、8 三人），15 个超时、1 个超过 joint-cell budget；
366 个比较未发现新增正的 public-history S。变体 7 个认证、7 个超时；linear balanced
和 want-heavy 下分别约 .015334/.015152，其余成功变体接近零，失败者不赋予标签。
balanced 正值再次经过完整策略认证和独立首步 action 枚举核对。

去重并施加 parent/family cap 后，[当时的 review manifest](../../new/local_data/strategic_slices_terminal_entry_candidates_v4/manifest.json)
包含 **28 父游戏（8 双人、20 三人）、20 family、195 个入口集合/窗口记录**。
train/validation/test 为 18/3/7 个父游戏、129/24/42 条记录，校准及其变体 family 只放
train；每个 parent 最多 8 条，每个 family 最多 8 个 parent。四条可检测正值来自
同一机制的两个 prior × k=1/2，仍然没有 public-history S>.05。query 等未测通道为 null。
新增数据全部是可完整求解的一轮短父游戏，不能声称长父游戏末段覆盖已完成。
候选通过 [readback audit](../../new/local_data/strategic_slices_terminal_entry_candidates_v4/audit.json)，
保存源码快照与全文件 checksum；仍为 `training_compatible=false`，未运行 D，未替换正式 v4。

### 同案例求解预算对照（2026-10-04）

用户指出 6 秒预算可能过紧；已对新随机批次中 **同一批 15 个超时案例**完成
[30/120 秒逐级重跑](../../new/local_data/strategic_slices_terminal_budget_retry_v1/REPORT.md)。
30 秒档：8 个认证成功、6 个超时、1 个未通过认证；剩余 7 个升至 120 秒后没有新增
成功，6 个未通过 deviation/tie 检查、1 个仍超时。原先另一个 joint-cell 超限案例
单独列出，未改变其资源限制。原三人批次的可认证覆盖因此从 **8/24 提升到 16/24**，
双人仍为 8/8；不能再用旧 6 秒失败率推断 terminal 本身难以求解。

15 个案例均完整构建 9,643–19,048 节点的 terminal 树；30 秒档构树中位数约 .64 秒，
聚合构树/搜索/显式认证及最终检查约占 3%/67%/30%。求解器按预算分配阶段时间，
因此延长预算也可能改变搜索路径，并非沿原轨迹单纯多跑。全部重试约 446 秒，
核心源码、认证门槛及其他预算保持不变；计时对照复现了相同 certified policy hash。
本轮只检查求解成本，成功恢复的参考尚未重测 C/S，也未自动合入候选数据。

### 按序补齐：恢复测量、失败诊断、末段覆盖与统一格式（2026-10-04）

**该阶段的历史汇总是 [unified terminal candidates v1](../../new/local_data/strategic_slices_terminal_candidates_unified_v1/REPORT.md)，
47 个 parent、35 个 family、345 条候选、91 个保存的 reference。**
这不是 345 个独立游戏，也不是已完成的数据集；保持 `candidate-review-only`、
`training_compatible=false`。本轮按用户要求 **不运行 D**，没有模型调用或训练。

1. **8 个获救 case 的 C/S 已补算并纳入候选。** 复用 30 秒档保存的 reference，
   不重新求 equilibrium；294 个 S 比较的最大值约 5e-14，未产生新的正 S。
   [entry candidates v5](../../new/local_data/strategic_slices_terminal_entry_candidates_v5/manifest.json)
   从 28 parent / 195 条增至 36 parent / 259 条，新增 64 条 C 候选。
2. **剩余失败已具体诊断。** [诊断报告](../../new/local_data/strategic_slices_terminal_failure_diagnosis_v1/REPORT.md)
   区分 root deviation、local own support、response social ties 与 wall budget。
   原 joint-cell 超限的 case 20 在 30 秒新搜索中通过认证，reference 已保存且 C/S
   另行补算，新增 8 条候选。原 32 个随机 parent 现在 25 个认证；仍有 6 个未通过
   认证、1 个超时，全部不赋 C/S。部分 candidate 的 root deviation 已通过，但
   off-path support/tie 仍不满足；不能只看 optimizer residual，也未放宽 epsilon。
   这完成了失败归因，不代表已修好所有求解失败。
3. **补入真正长游戏的末段。** 复用此前 8 个三轮随机 parent 与 2 个调查对照
   parent 的已认证末段 reference，经 cap 保留 78 条 singleton 候选；原父游戏有
   6/9 次 proposal，入口剩余 1–3 次，完整执行 response 至 native terminal。
   所选 singleton 的 C/query S 均重算一致，并补测 future-public-history S。
   6 条 S>.05 全来自调查对照，S=1/6 或 1/4；随机长游戏仍未提供强正 S。
   非调查小正值仍只有已有机制的两个 prior × k=1/2，共 4 条，最大约 .015334。
   这一步整合已有已认证入口，没有把旧入口重新包装成新发现的随机机制。
4. **统一数据格式已实现。** [格式说明](ENTRY_INFORMATION.md#unified-terminal-candidate-distribution-format)
   与 `training.strategic_slices.terminal_candidates` 将 singleton 和 entry set
   都表示为 history/world 联合分布，保留 member C、独立 reference、belief regime
   和具名 S channels。collective S 不复制给各历史，未测通道仍为 null。
   完整初态 reference 的 prefix posterior，与外生公共路径后重新求解的入口 prior，
   明确分层，不能宣称后者延续完整初态 equilibrium。

统一包包含 267 条 reference-reach entry-set 记录和 78 条 late singleton。
train/validation/test 为 29/6/12 个 parent、213/44/88 条记录；family 不跨 split，
校准 family 仅 train，parent cap=8、family parent cap=8。
[readback audit](../../new/local_data/strategic_slices_terminal_candidates_unified_v1/audit.json)
重建 reference、验证 policy hash/native terminal、重放 member history，并重算所有
member C/V。新增联合采样检查与既有信息价值测试通过；源码快照和 checksum 随包保存。

复现本轮新增流程（输出目录使用新路径）：

```bash
python -m examples.strategic_slices.measure_rescued_entries --output /tmp/rescued-entries
python -m examples.strategic_slices.diagnose_terminal_failures --output /tmp/terminal-diagnostics
python -m examples.strategic_slices.unify_terminal_candidates \
  --entry-source new/local_data/strategic_slices_terminal_entry_candidates_v5 \
  --entry-source new/local_data/strategic_slices_cell_budget_candidates_v1 \
  --output /tmp/unified-terminal-candidates
python -m unittest training.strategic_slices.test_terminal_candidates \
  training.strategic_slices.test_native_entry_information \
  training.strategic_slices.test_behavior_information -q
```

仍待研究的是随机机制多样性、强正 S 的非调查案例，以及 7 个残留 solver failure 的
算法改进；当前无证据保证所有游戏都能求解，也没有 D/可学习性结果。旧 bounded
production v4 和现有训练入口保持不变。

## 既有 baseline 进度（2026-10-03，100/20/40 数据已冻结）

**共享父游戏已达到 100/20/40，共保留 1,035 个 slices。** 两组训练读取同一批父游戏。
冻结文件见 [production v4 manifest](../../new/local_data/strategic_slices_production_v4/manifest.json)，
完整分层统计见 [inventory](../../new/local_data/strategic_slices_production_v4/inventory.json)。

| 分割 | 父游戏 | 2 人 / 3 人 | Slices | 结构 family | 正 S 父游戏 / slices |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 100 | 67 / 33 | 659 | 30 | 12 / 23 |
| validation | 20 | 13 / 7 | 128 | 7 | 2 / 4 |
| test | 40 | 27 / 13 | 248 | 21 | 4 / 8 |

58 个 family 不跨分割，每个 family 至多 8 个父游戏，每个父游戏保留 2–8 个 slices。
所有父游戏均为三轮、从零承诺开始；共保存 317 个逐入口参考。
候选来源为 **144 个随机原生父游戏 + 16 个显式调查机制补充父游戏**。
18 个正 S 父游戏中，16 个来自补充池，另有训练集的一个随机双人和一个随机三人游戏。
`k=1/2/3` 窗口分别为 **236/450/349** 个。

首版范围明确限定：双人支持为 1/3/9/27 个世界，其中 10 个父游戏是完全信息控制；
三人固定一个可变偏好槽，即 3 个可能世界。三名玩家都参与实际目标，未添加无关玩家。
本数据不代表一般 27 世界三人游戏的求解覆盖。补充池的不同计分 family 共享调查机制，
因此也不宣称调查机制完全未见过。详细生成与恢复规则见下方“正式规模的可恢复冻结”。

[全量审计](../../new/local_data/strategic_slices_production_v4/audit.json) 已重建并认证全部
317 个参考、检查全部 1,035 个入口后验，分层独立复算 26 个 C 和 120 个信息价值比较。
[验收记录](../../new/local_data/strategic_slices_production_v4/acceptance_checks.json) 包括
91 项模块回归、两组训练入口、mock 收集与精确恢复、20 个验证父游戏的完整 team
mock，以及各取一个 2/3 人验证父游戏、覆盖全部焦点角色的 focal-reference 抽查。
后者不是全部验证历史的 oracle 可解性保证。可迁移包见
[production v4 数据包](../../new/local_data/strategic_slices_production_v4.tar.gz)，包内
`SHA256SUMS` 校验所有数据、参考、审计和源码快照文件。

Manifest SHA-256：`369e956000393537b7fc16a2ebbee5b3f551432950d30746261fd8306cf386d1`。
真实模型四副本信号检查、GPU 更新与等 token 预算的学习比较仍未执行；CPU/mock
验收不能证明学习效果或 slices–SP 效率提升。

### 小实验：bounded 与 terminal 标签对照（2026-10-03）

完成了 [7 个入口的 paired comparison](../../new/local_data/strategic_slices_terminal_pair_quick_v1/REPORT.md)，
固定 belief 和 k，使用同一求解器分别认证 bounded/terminal reference；最终一轮约 8 秒，
全部通过。21 对 k=1/2/3 窗口中，18 对 C 改变，6 对跨过 C>0.1 门槛，6 对正 S 标记改变，
12 对改变 parent cap 前的筛选结果。例如随机双人入口的 k=2，C 从 3 变为 0；调查
变体的 k=2，C 从 2.5 变为 2/3，S 从 0 变为 1/12，最优 root action 从 OFFER 变为
INVESTIGATE。两侧 reference 也重新求解，不能把差异全部归因于固定策略下的截断计分。
样本按小 terminal tree 便利选择，调查案例还共享机制，窗口彼此相关；这些计数不估计
总体差异率。结果支持继续把现有标签明确解释为 cutoff-consequential，而不假定其
自动代表 terminal consequence。正式数据未改动。

### 小实验续：短期最优策略能否保留 terminal 最优（2026-10-04）

对同一批 7 个入口完成了 [prefix recoverability 检查](../../new/local_data/strategic_slices_prefix_recoverability_quick_v1/REPORT.md)，
耗时约 8.5 秒。用信息集一致的 realization-plan LP，在所有 bounded-optimal prefixes
（包含并列选择）中寻找最好 terminal continuation，并用独立树上策略计算核对。
四个随机入口在 k=1/2/3 下都存在保留 terminal 最优的策略；调查 fixture 的 k=1
存在这样的策略，但 canonical PASS 会损失 0.25，k=2/3 则所有短期最优 prefixes
都至少损失 0.25。两个同-family 调查变体在所有 k 下分别至少损失约 0.0833/0.125。
因此 C/S 标签不同不等于无法拼接，需区分 objective-compatible、tie-sensitive 与
objective-conflicting 的短期策略。所有结论依赖指定 terminal reference；后续自身
决策允许 terminal 最优，属于可恢复性上界，并未验证模型学习或 repeated bounded
replanning。正式数据未改动，详细数值、定义与限制见报告。

### 2026-10-02：三个缺口的小型验收记录

以下保留正式扩展前的实现、诊断和小型验收证据。
**有限深度 oracle、正信息价值覆盖和训练衔接均已有实现与 CPU 验收。**

| 模块 | 当前实现 | 证据边界 |
| --- | --- | --- |
| Oracle 求解 | 从实际违反条件的信息节点开始，按完整审核扩大变量/行动支持；小问题数值精修，大问题使用无显式 Jacobian 的 Newton–Krylov；变量节点上限可配置，默认 4096 | 保留 `1e-8` 完整偏离、私有信息、局部行动支持和回应平局审核；无一般收敛保证 |
| 求解成本 | 候选最佳响应和数值残差按深度批量计算；不合并历史、信念或策略；最终认证仍使用独立的原完整树检查 | 与逐节点实现的随机策略结果对照一致；另有超过旧 192 节点限制的已知混合均衡回归 |
| 信息价值 | 每个入口可分别计算多个 RR 深度；窗口选择同时保留 C 增长和 S 首次明显增长的窗口 | 原生案例在 1 RR 时 S=0，2 RR 时自由选择 S=0.25；这是特定机制证据，不是随机产率 |
| 数据冻结 | `bounded-next-own-v1` 保存逐入口参考树、完整历史、先验、截止点、参数及认证；正 S 父游戏配额不足时不写 COMPLETE | 小型验收集 train/validation/test 各 2 个父游戏，均覆盖 2/3 人，family 分离，均有正 S |
| Slice 训练 | 模型控制接下来 k 次自身决定；其他玩家及模型窗口外的自身行动使用该入口认证策略，执行到同一截止点，奖励取当前承诺效用 | 提示明确截止点与剩余控制次数；不把截断收益写成终局收益 |
| SP 与评估 | SP 从相同父游戏初态跑到原生终局；完整游戏评估保留 team 和 focal_reference；slice D 单独按截断收益计算 | 截断训练与终局 SP 比较整套训练方法，不能单独归因于 C 筛选 |
| 实际训练信号 | `signal_probe` 支持真实模型 HTTP 调用，记录同世界四副本奖励差异、失败率、正 S 覆盖和生成 token；mock 单独标记 | CPU/mock 不代表真实模型奖励多样性、GPU 优化或恢复已验证 |

新版求解、数据与端到端证据见下方“本轮验收”。旧 RR-only、近视参考和终局奖励数据
保留其原始语义，不会自动转换成新口径。

### 本轮验收与复现

`diagnose_gaps` 重新求解之前选定的四个双人、两个三人三轮父游戏。
本轮每个问题使用 **300 秒**预算，早期配对诊断使用 **90 秒**；因此认证覆盖比较
同时包含求解器与时间预算变化，不能解释为相同时间下的加速倍率。
本轮 **双人 4/4、三人 2/2 全部通过**；两个三人问题分别有 91,579/56,259 个节点，
其中后一问题含 **541 个联合变量信息节点、2,168 个数值变量**。
完整结果、原始父游戏、认证、原生审核和源码指纹保存在
[`strategic_slices_gap_panel_final_v1`](../../new/local_data/strategic_slices_gap_panel_final_v1/summary.json)。

```bash
python -m training.strategic_slices.diagnose_gaps \
  --output new/local_data/strategic_slices_gap_panel_fresh --seconds 300
```

[`information_acquisition.json`](fixtures/information_acquisition.json) 是从已有原生调查机制
提取的可复现输入，不携带继承标签。`coverage_pool` 改变目标计分模式，并加入没有
无关玩家的三人混合动机三角目标游戏，形成 **16 个刻意设计的验收候选**。
它不是随机父游戏池，也不是正式研究数据。构建时分别重新求解 1/2 RR；所有参考
通过完整认证，父游戏从零承诺开始，指定入口通过公开合法 PASS 历史到达。
指定前缀是独立于隐藏世界的外生设置；随机前缀使用独立于隐藏世界的均匀合法行动。
两者的入口公共先验均有明确依据，再按焦点玩家自身类型和收到的私有答案条件化。

```bash
python -m training.strategic_slices.coverage_pool \
  --output new/local_data/strategic_slices_gap_pool_fresh.jsonl
python -m training.strategic_slices.build \
  --output new/local_data/strategic_slices_bounded_acceptance_fresh \
  --reference-policy bounded-next-own-v1 \
  --candidate-pool new/local_data/strategic_slices_gap_pool_fresh.jsonl \
  --train 2 --validation 2 --test 2 --three-player-fraction .5 \
  --max-entrances 1 --entrance-trajectories 1 --lookahead-depths 1 2 \
  --max-nodes 120000 --solver-seconds 90 --min-positive-s-parents 1
python -m training.strategic_slices.audit \
  --data new/local_data/strategic_slices_bounded_acceptance_fresh \
  --output /tmp/bounded-acceptance-audit.json
python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_bounded_acceptance_fresh --arm slices --check-only
python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_bounded_acceptance_fresh --arm selfplay --check-only
python -m unittest discover -s training/strategic_slices -t . -v
```

`--lookahead-depths` 明确指定要尝试的截断深度；每个入口/深度分别认证、保存，不能
把一个深度的收益搬到另一个深度。超出预算的候选保留失败记录且没有标签。
`--min-positive-s-parents` 是每个分割的自由选择正 S 父游戏配额，bounded CLI 默认 1；
未达到父游戏配额、正 S 配额或构建期间源码发生变化，都不允许数据被训练入口加载。
以上命令生成小型验收集；正式规模数据及 2:1 配额见本页顶部和下一节。

本轮完整模块回归 **86 项通过**；BENAC pilot、概率诊断、稳定化与课程采样相关回归
另 **22 项通过**（合计 108）。最终验收集见
[`strategic_slices_bounded_acceptance_final_v1`](../../new/local_data/strategic_slices_bounded_acceptance_final_v1/manifest.json)：
每个分割 2 个父游戏、7 个 slice，其中 2 个正 S slice 来自 1 个父游戏；各分割共有
6 个不同结构 family。全部 21 个入口 posterior 通过审计，并重新计算了各分层的
C/S。数据和完整诊断均检查构建/运行期间源码指纹不变。
两组 CPU 训练入口检查、mock 收集与采样恢复、完整 team/focal_reference 验证均通过；
详见 [验收检查](../../new/local_data/strategic_slices_bounded_acceptance_final_v1/acceptance_checks.json)
和 [mock 验证](../../new/local_data/strategic_slices_bounded_smoke_final_v1/COMPLETE.json)。

### 正式规模的可恢复冻结

`freeze.py` 的目标为 train/validation/test **100/20/40 个共享父游戏**，
每个分割的 2/3 人配额分别为 **67/33、13/7、27/13**，每个父游戏至多 8 个 slice。
父游戏均为三轮、从零承诺开始；同一结构 family 不跨分割，每个 family 至多 8 个父游戏。
候选池先包含 16 个明确标记的调查机制候选（8 种计分模式 × 2 种先验），随后使用
固定种子的随机原生父游戏。双人最多三个可变偏好槽；三人保留一个可变槽
（3 个可能世界），其余原可变槽由固定种子的 catalogue 抽样设为已知值。这个支持
限制在求解前施加并记录，未改变原生动作、玩家参与或三轮日程，不能声称覆盖
原 27 世界三人子域。补充候选在不同计分 family 间共享调查机制，因此
family 分离不代表调查机制完全未见过，也不能将筛选后数据解释为随机生成产率。

```bash
python -m training.strategic_slices.freeze \
  --output new/local_data/strategic_slices_production_v4 \
  --cache new/local_data/strategic_slices_production_cache_v4 --workers 6
```

中断后使用相同命令恢复。每个候选连同失败诊断、原始输入、配置、源码指纹和参考
文件哈希独立落盘；结果按候选序号入选，完成先后不影响分割。改变求解配置或源码
必须使用新目录，已完成数据不会被覆盖。`progress.json` 只是进度；仅在总量、玩家
配额、正 S 父游戏最低覆盖（5/1/2）和源码一致性全部满足后才生成 `COMPLETE.json`。
随机父游戏使用 1 RR 加下一次自身提案的截止规则，调查补充池尝试 1/2 RR；
这些深度分别记录于配置和每个参考。随机父游戏还要求初态参考通过认证，并排除
不参与任何目标的玩家。入口取初态及
一个独立于隐藏世界的公开合法历史；相同入口、相同绝对截止点只求解一次。
数值求解受时间预算和平台影响；精确复现实验应使用冻结文件及其哈希，而非假定
重新生成会逐字相同。实际构建源码保存在数据目录的 `build_source_snapshot.zip`。
已知 SciPy Jacobian 数值失败不产生标签，整个候选被排除；本次构建的三条原始
异常及处理记录另行保留。当前生成器已将此处理自动化，意外异常仍中止构建。

### 新训练与完整评估契约

[`bounded_data.py`](../../training/strategic_slices/bounded_data.py) 的 `CONTRACT` 随 manifest
冻结。Slice 的原生动作、分支和私有答案保持真实执行；控制满 k 次后，焦点玩家也
交回该入口的固定认证策略，直到 **固定的绝对截止点**。窗口内不重新移动截止点。
截断成功轨迹记为 `cutoff`，`objective_utility` 保存奖励，`terminal_utility` 保持 null；
完整游戏奖励另以 `native-terminal` 标记。即使某个 slice 截止点恰好等于终局，
也保留它的 slice 评价口径。非法/截断调用和失败组规则与旧流程一致。

完整 `team` 评估每个玩家均使用当前模型，直至真实终局。`focal_reference` 在每个
非模型玩家行动前调用相同、固定参数的有限深度 oracle，并重新认证；公共先验按
**参考方实际行动策略的似然**更新，焦点模型行动作为外生干预，不假装它由 oracle
生成。私有调查答案只进入各自信息分区。求解失败直接中止该次评估，不换近视对手、
不编造效用；oracle 调用次数和成本单独记录。这是公开声明的滚动参考算法，不是
原游戏终局均衡。完整游戏参考深度使用 manifest 的 `lookahead_rr`，与 slice 的
逐记录深度分别保存。

真实模型信号检查在训练前使用已部署的原生工具调用端点；需提供真实 checkpoint
身份。它不会因为奖励相同或模型失败而重新抽样。示例：

```bash
python -m training.strategic_slices.signal_probe \
  --data /absolute/path/to/bounded-dataset --output /new/actual-model-signal \
  --base-url http://127.0.0.1:8000/v1 --model MODEL --checkpoint-hash ACTUAL_WEIGHT_HASH \
  --groups 24 --replicas 4
# 仅 CPU 流程验收，不能作为模型信号证据：
python -m training.strategic_slices.signal_probe \
  --data /absolute/path/to/bounded-dataset --output /new/mock-signal --groups 8 --mock
```

下一阶段是执行真实模型信号检查、首次 GPU 更新及恢复，再运行等生成 token
预算的正式训练与冻结测试。100/20/40 数据已经冻结，不再是待补任务。

## Current oracle: include the next own decision, jointly certify mixed policies

The current agreed direction is an **all-player, private-information,
finite-horizon oracle**. The cutoff score is the utility of commitments already
made. [`bounded.py`](../../training/strategic_slices/bounded.py) implements this
as `BoundedPrivateWindow`; it does not use the fixed myopic opponent below.

* One step is a **completed proposal opportunity**. An OFFER and its native
  ACCEPT/REJECT response together consume one step. PASS and INVESTIGATE each
  consume one. A pending offer is resolved before stopping.
* `lookahead_rr=r` sets a base span of `r * n_players` proposal opportunities.
  The default `horizon_mode='rr-plus-next-own-proposal-v1'` extends that common
  endpoint when necessary to **complete the entrance actor's next proposal
  opportunity**, including its resulting response. From a proposer entrance,
  the ordinary 1-RR window therefore has three opportunities for two players
  or four for three players: `A investigates -> B [-> C] -> A acts again`.
  From a pending-response entrance, the responder's upcoming proposal can
  already fall inside the base span. `resolve_horizon()` records the actual
  proposal count, root actor and next-own position. Every branch has the same
  absolute endpoint; a query branch never receives extra depth on its own.
  The native terminal is always respected. `horizon_mode='rr'` retains the
  earlier RR-only objective, which stopped before the proposer acted again.
* At the common cutoff, score each player's own native utility
  `sum(preference * goal_satisfaction)` from current commitments. Binary goals
  earn their score only when all requirements are committed; linear goals earn
  their committed fraction. There is no bonus for potentially achievable goals,
  terminal rollout or estimated continuation value.
* Every player participates in the **same joint solving procedure** over every
  legal action and hidden world. `solver_mode='equilibrium'` starts from uniform
  policies and complete contingent best responses. If they cycle, the changing
  private-information cells become variables in a joint behavioral-probability
  complementarity problem. Deterministic initializations and player update
  orders provide additional candidates. Their observed native action supports
  seed the numerical variables; full-tree deviation checks expand a support
  whenever an omitted action is profitable. No native branch is pruned.
  Large trees initialize a working set from current local violations; complete
  native audits expand it. The default variable-cell limit is 4,096. Small
  systems use sparse least squares with boundary refinement; larger systems
  use matrix-free Newton–Krylov. Candidate responses and residuals batch
  independent histories without merging them. Exact constant subtrees are evaluated once during
  numerical search; their full world/player values remain intact. Additional
  violating cells expand the candidate problem. Histories are never merged.
  Synchronous and ordered candidate generation each target 20% of the
  remaining search budget, leaving a 60% target for joint solving and final
  auditing. These are soft limits checked between complete candidates; large
  trees also cap candidate sweeps. Root-only screening guides the search, while
  every accepted result receives a fresh complete certification below.
* Numerical optimization only generates candidates. A successful profile must
  pass complete-tree own-type/private-answer-conditioned unilateral deviation
  checks, private-information probability checks, and local own-optimal action
  support checks at every information cell. Default tolerance is `1e-8`.
  Zero counterfactual reach uses the declared prior conditioned on own type and
  received private answers. This is not a formal sequential-equilibrium claim.
  Native transition/payoff audits verify the enumerated tree separately.
* The response-only social tie convention remains independently audited:
  among own-optimal responses, prefer the largest other-player utility.
  Remaining admissible own-optimal actions may now mix nonuniformly; the old
  requirement of a uniform, completely unchanged strategy table is not the
  new acceptance condition. Certificates identify this new selection contract.
  `solver_mode='synchronous'` explicitly preserves the earlier selection method.
  The mixed numerical search is not globally guaranteed to find a profile;
  limits and failed checks still yield **no oracle label**.
* C/S are evaluated using **cutoff commitment utility**, with opponents and any
  remaining focal choices inside this tree following its selected profile. The
  focal control bound `k` remains separate from oracle depth `lookahead_rr`.
  All compared branches share one fixed cutoff; players do not independently
  shift that cutoff after each move within this diagnostic.

This solves an explicitly truncated game to a recorded numerical deviation
tolerance. It does not claim original-game
terminal optimality, a unique equilibrium, or an original-game subgame at an
arbitrary information-set entrance. In particular, a longer original parent
can now be studied without enumerating its complete terminal tree. This first
trial diagnoses the oracle; the existing terminal-reward training datasets
are not automatically reinterpreted as cutoff-reward datasets.

```python
from training.strategic_slices.bounded import BoundedPrivateWindow

tree = BoundedPrivateWindow(
    rules, root, rules.worlds, world_weights=public_prior,
    lookahead_rr=1, max_nodes=400000, seconds=60,
).solve()
audit = tree.audit_native()
```

[`equilibrium.py`](../../training/strategic_slices/equilibrium.py) implements
the mixed candidate search and independent certification. Unit tests include
a known Bayesian signaling equilibrium with nonuniform mixing, exhaustive
pure unilateral-deviation verification, off-path threat rejection, and
nonfinite/timeout rejection. The horizon tests also verify that two different
private investigation answers lead to different actual next-own proposals.

### Reuse with matching game, history, beliefs and endpoint

[`bounded_cache.py`](../../training/strategic_slices/bounded_cache.py) provides
`BoundedProblemCache.solve(...)`. An identical complete problem reuses its
certified result without enumerating or solving again. Keys include public
history, private delivery records, world support/prior, absolute cutoff,
backend versions and solver settings. Returns are mutation-isolated.
The cache uses LRU limits of two problems and 300,000 total nodes by default.

```python
from training.strategic_slices.bounded_cache import BoundedProblemCache

cache = BoundedProblemCache()
first = cache.solve(rules, root, rules.worlds, world_weights=public_prior)
again = cache.solve(rules, root, rules.worlds, world_weights=public_prior)
assert again.cache_hit  # No repeated enumeration or equilibrium search.
```

For an internal entrance, `parent_tree=...` and `parent_root_index=...` can reuse
the native descendant structure **only when its absolute endpoint equals the
new entrance's independently computed endpoint**. Information groups and
beliefs are rebuilt, policies start uniformly, and the new problem is solved
and certified again. A changed prior cannot reuse the parent's certificate.
Different endpoints or histories use fresh enumeration. Physical-state
memoization remains restricted to counting, never equilibrium-value reuse.

[`diagnose_bounded.py`](../../training/strategic_slices/diagnose_bounded.py)
pairs the same multi-round parents and the same reachable entrances across
requested RR depths. It checks both initial entrances and entrances after a complete
uniform-action RR. Uniform public prefixes are independent of the private
world, so public prior weights stay unchanged; each player's own received
query answers still refine its information partition. Diagnostic paths use
the solved-profile/uniform mixture, with recorded entrance posterior.

The exact unfolded node count is memoized over physical states **only for
counting**, to reject oversized trees before allocation. Policies, information
sets and action values are never merged by that physical counting cache.
Raw cases retain the parent, legal setup history, depths, failures,
certificates, audits, entrance beliefs and C/S measurements.
Internal sampled entrances explicitly record the original shared cutoff and
their remaining depth; they are not independently replanned one-RR problems.
Use `--max-entrances 0` to measure only the independently solved root cells.
`--cache-replay` measures certified-answer reuse without adding samples to the
C/S denominators.

```bash
python -m pip install -r examples/strategic_slices/requirements_oracle.txt
python -m training.strategic_slices.diagnose_bounded \
  --output new/local_data/strategic_slices_rr_cutoff_fresh \
  --seeds 12 --parent-rounds 3 --lookahead-rr 1 \
  --solver-seconds 60 --max-nodes 400000 \
  --max-entrances 0 --cache-replay
python -m unittest training.strategic_slices.test_bounded_solver \
  training.strategic_slices.test_equilibrium \
  training.strategic_slices.test_bounded_cache \
  training.strategic_slices.test_bounded_diagnostic -v
```

### Historical next-own v4 horizon checks (2026-10-02)

`new/local_data/strategic_slices_next_own_mixed_v5/` contains a completed,
source-fingerprinted paired diagnostic with backend
`private-behavioral-joint-epsilon-v4`. Six three-round parents were deliberately
selected from the earlier diagnostic: four two-player parents (including two
earlier cycles) and two three-player parents (including one earlier cycle).
Each is solved with the RR-only and next-own endpoints, using 400,000 nodes,
90 seconds and an unchanged `1e-8` deviation tolerance. This selected panel
does not estimate random dataset yield.

| Players | RR-only certified | Next-own certified | Next-own nodes per tree |
| --- | ---: | ---: | ---: |
| 2 | 3 / 4 | 3 / 4 | 6,060–8,428 |
| 3 | 1 / 2 | 0 / 2 | 56,259–91,579 |

The new solver recovers the RR-only two-player cycle at seed 20261005; the
next-own problem at seed 20261011 also certifies. Its three certified next-own
parents all have measured `C_span > 0.1`. The remaining two-player next-own
candidate fails certification with a last checked root deviation gain of `2.73e-8`,
still above the required tolerance. Its local support/tie audits have not
passed; proximity of the root gain alone is insufficient for certification.
The two three-player next-own searches now reach the joint stage, then exceed
its 192-variable-information-cell limit. Their native trees fit the node
budget; the numerical candidate problem remains too large for this solver
configuration. Failed candidates have no C/S labels. A computational limit
does not demonstrate absence of equilibrium. General mixed game convergence
therefore remains a limitation rather than a solved claim.

An independently designed **native three-player private-information fixture**
also passes with the new default horizon: 56,259 nodes, two hidden worlds,
all legal branches, and the entrance player's next proposal completed.
Its largest root/local support deviation is approximately `1.11e-16`;
native transitions, leaves, propagated values and response ties all audit.
Fresh construction plus solving takes 7.30 seconds; exact-problem replay
takes 2.62 seconds, including the isolated copy. This fixture demonstrates
native three-player support and measured reuse savings, not random yield.
The raw evidence is
`new/local_data/strategic_slices_next_own_native_smoke_v2/result.json`;
the directory also includes its raw parent and runnable smoke script.

`cases.jsonl`, `summary.json`, `COMPLETE.json`, `sources.json` and source
snapshots retain the paired diagnostic and its exact implementation. Earlier
working runs under `...mixed_v2/` through `...mixed_v4/` are superseded.
The v3 working run is explicitly marked incomplete because source files
changed during its run. Current failures explicitly report
`local_policy_audit_performed=false` and null counts when a root check fails
before local checks run. A reused structure or a fresh solve also clears
previous candidate audits, so a failure cannot inherit the parent's evidence.
The complete oracle, diagnostic, reuse, existing training pipeline and
probability/stabilization regression suite passes **91 tests**. CPU oracle
dependencies are listed separately in `requirements_oracle.txt`.

### Historical RR-only synchronous results (2026-10-02)

The following results use the **earlier** RR-only horizon and synchronous
uniform-tie selection. They do not describe the new default next-own horizon
or mixed solver. Their original artifacts and meaning are retained.

`new/local_data/strategic_slices_bounded_rr_diagnostic_v1/` contains 96 paired
cases: 12 seeds for each player count, three-round original parents, initial
and after-one-RR entrances, and search depths 1 RR / 2 RR. The node budget is
30,000, with an eight-second build/solve budget. Only the two time-budget
failures were retried with 30 seconds on identical parents, priors, histories
and cutoffs. One retry certified and one revealed a policy cycle.

| Players | Search | Entrance | Certified / 12 | Certified cases with C > 0.1 | Other outcomes |
| --- | --- | --- | ---: | ---: | --- |
| 2 | 1 RR | Initial | 10 | 10 | 2 cycles |
| 3 | 1 RR | Initial | 5 | 5 | 7 cycles |
| 2 | 1 RR | After 1 RR | 10 | 10 | 2 cycles |
| 3 | 1 RR | After 1 RR | 5 | 5 | 7 cycles |
| 2 | 2 RR | Initial | 0 | 0 | 12 tree limits |
| 3 | 2 RR | Initial | 0 | 0 | 12 tree limits |
| 2 | 2 RR | After 1 RR | 1 | 1 | 8 tree limits, 3 cycles |
| 3 | 2 RR | After 1 RR | 0 | 0 | 12 tree limits |

The one-RR oracle therefore produces exact cutoff-game signals in genuinely
longer original games. The successful three-player initial trees have roughly
7,000–19,000 nodes; two-RR initial trees are much larger and all exceed the
configured budget. Whole-tree enumeration does not resolve general-sum
best-response cycles: those candidates still have no certified oracle value.

For all certified initial cases, lowering C from 0.1 to 0.01 changes neither
the measured positive-entrance counts nor parent acceptance. In this sample,
the remaining bottlenecks are search size and solution convergence rather
than the C threshold. Selected query comparisons have free-choice `S=0`, with
maximum `S_given_query=0.0078125`; these comparisons do not exhaust every
information set or query.

`cases.jsonl` / `summary.json` retain the original eight-second run.
`timeout_recheck/` retains the two retries. `combined_cases.jsonl` /
`combined_summary.json` combine outcomes with each case's actual time budget;
`sources.json` fingerprints the relevant code. All artifacts explicitly say
`diagnostic_only=true` and `training_reward_unspecified=true`. They are not a
frozen train/validation/test corpus. Oracle and pipeline regression checks pass
61 tests; the new bounded solver/diagnostic account for 16 of them.

## Earlier myopic-reference diagnostic (2026-10-02)

**Status:** this version is retained as a computation/pipeline diagnostic.
The user did not accept its myopic reference as the primary supervision target;
the RR-cutoff all-player oracle above is the current direction. Its dataset and
results must retain their original reference label.

`new/local_data/strategic_slices_v4_fixed_2round/` is a separately frozen,
CPU-audited dataset. **All three-player parents have two complete proposal
rounds**; each player gets two proposal opportunities, plus actual responses.
Both arms use this same corpus. The training/validation/test entrypoints and
Slurm scripts accept it without different training settings.

| Split | Parents (2p / 3p) | Slices | Structural families |
| --- | ---: | ---: | ---: |
| Train | 100 (67 / 33) | 624 | 46 |
| Validation | 20 (13 / 7) | 127 | 11 |
| Test | 40 (27 / 13) | 249 | 23 |

Manifest SHA256: `20eec006e1353c77b4261efa6a10fce088dd942c2619430a5dfe127ec85473f4`.
The portable bundle `new/local_data/strategic_slices_v4_fixed_2round_bundle.tar.gz`
includes the corpus, audits, horizon evidence and mock CPU acceptance, with an
adjacent `.sha256` file. Generated files are ignored by Git; transfer the bundle
alongside the code when running on the cluster.
Generation took about 87 seconds, accepting 160 parents from 183 candidates.
The original `C_span>0.1` and extension `>0.05` thresholds were retained.
Train contains 116 delayed-consequence windows and three three-player windows
with private-answer `S>0.05`; validation/test still have no positive-S strata.
This remains primarily a consequence/efficiency experiment.

**Reference contract:** this alternative uses the explicit
`fixed-myopic-v1` policy in
[`reference.py`](../../training/strategic_slices/reference.py), rather than
requiring a whole-game equilibrium solver. A responder maximizes immediate
own commitment utility, then expected others' utility for own-score ties. A
proposer predicts those responses using its own-information-conditioned public
prior and maximizes immediate expected own utility. Residual ties use the first
native action. The policy sees only public physical state, its own preferences
and its own received query answers. It deliberately does not update its prior
from public behavior and is not terminal-optimal or an equilibrium.

[`sparse.py`](../../training/strategic_slices/sparse.py) retains **every native
focal choice and its actual subsequent branches**. It expands only compatible
fixed-reference choices for other players. After the focal bound it executes
the same reference to an actual native terminal, with exact world-specific
utilities. Thus C/S are exact **relative to this specified policy and window**;
the sparse calculation does not prove equilibrium behavior. Private answers,
public path likelihoods and the physical query cost are retained. SP continues
to use the current model for every player in the complete native game.

All 160 reference contracts and all 1,000 entrance posteriors pass the corpus
audit. Eight sampled exact C values and 18 query comparisons were recomputed.
Full-tree versus sparse tests agree on best/worst values, root-action values
and private-answer S. Both-arm CPU collection, deterministic sampling recovery
and full validation pass. The relevant combined suite passes **45 tests**.
These checks use native games and mock actors; GPU/model learning has not run.

### Why the previous larger games were rejected

The old v3 log has **zero** rejections for missing consequential slices.
Failures occurred before C/S selection: tree limits, wall-clock limits and
cycles in synchronous best-response iteration. Three-player rounds were also
explicitly hard-coded to one in the original generator.

A native three-player `[1,1,1]`, two-goal parent (seed 20261027) has 4,811
public-history nodes in one round, 6,287,343 in two, and 5,004,049,127 in three.
Equivalent physical states suffice to count this size, but cannot be used to
merge equilibrium strategies: different public histories can imply different
beliefs. Increasing the old 30,000-node cap or lowering C thresholds does not
resolve that bottleneck.

Paired fixed-reference diagnostics across 24 identical-seed parents at each
horizon successfully measure all 72 cases. At `k<=3`, 24/24 one-round, 23/24
two-round and 17/24 three-round parents retain consequential windows. For the
two-round sample, changing the C threshold from 0.1 to 0.01 adds only six
entrances (70 to 76 out of 144 measured entrances).

There is also a real **window-length effect**. On identical entrances for seven
weak/zero-C three-round parents, extending control from three to five own
decisions recovers three parents. In one recorded example, the three-decision
window has `V_star=V_min=3`: after it ends, the reference accepts an offer and
repairs earlier mistakes. With five controlled decisions the player can keep
rejecting; `V_star=3`, `V_min=1`, and `C_span=2`. Lowering a threshold cannot
recover the exact zero from the shorter window. All private-answer S values in
this targeted longer-window sample remain zero.

Raw evidence is under
`new/local_data/strategic_slices_horizon_probe/`: `baseline.jsonl`,
`fixed_paired/cases.jsonl`, `fixed_paired/summary.json`, `longer_k.jsonl`, and
`longer_k_summary.json`. C measures possible decision consequences; it does
not establish the current model's D or four-replica GRPO reward diversity.

### Reproduce the multi-round version

```bash
python -m training.strategic_slices.build \
  --output new/local_data/strategic_slices_multiround_fresh \
  --train 100 --validation 20 --test 40 \
  --three-player-fraction 0.333333333 \
  --reference-policy fixed-myopic-v1 --three-player-rounds 2 \
  --max-entrances 6 --entrance-trajectories 6 --solver-seconds 15

python -m training.strategic_slices.audit \
  --data new/local_data/strategic_slices_multiround_fresh --output /tmp/multiround-audit.json
python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_multiround_fresh --arm slices --check-only
python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_multiround_fresh --arm selfplay --check-only
python -m training.strategic_slices.diagnose_horizon \
  --output new/local_data/strategic_slices_horizon_fresh --seeds 24

# Same seeded entrances, extended control; reproduces the compensation example.
python -m training.strategic_slices.diagnose_horizon \
  --output new/local_data/strategic_slices_long_window_fresh \
  --seed 20261018 --seeds 1 --max-k 5
```

For a three-round exploration, use `--three-player-rounds 3 --max-k 5
--max-entrances 9`; the larger entrance cap covers all three proposal rounds.
Keep the reference contract explicit. The default generator still uses the
original synchronous contract, so this alternative requires the named flag.
The original v3 corpus remains usable with its own frozen policy.

## Original frozen local dataset (2026-10-02)

`new/local_data/strategic_slices_v3/` is complete and model-independently audited.

| Split | Parents (2p / 3p) | Slices | Distinct structural families |
| --- | ---: | ---: | ---: |
| Train | 100 (67 / 33) | 723 | 38 |
| Validation | 20 (13 / 7) | 145 | 11 |
| Test | 40 (27 / 13) | 299 | 16 |

Manifest SHA256: `73d6660d278f9facf9a3bd24351feac74e1c3ce7ed6a78ade360d2c4cb5bd703`.
Every parent has 5–8 retained windows. All 160 reference identities and all
1,167 entrance posteriors were checked, with six additional independently
recomputed exact window values. Train includes 79 windows whose one-decision
span is flat but whose longer span is consequential. Both train entrypoints
pass CPU data checks; the full corpus passes mock collection/validation and
sampling recovery. The new tests and related pilot/probability/sampling checks
pass 26 tests. Actual GPU optimization has not run.

**Coverage limit:** all selected windows have `S=0` for the specified private
investigation-answer intervention. Train also has zero `S_given_query`; tiny
positive conditional values occur in development/test below the 0.05 stratum
threshold. This is a first **consequence/efficiency pilot**, not a positive
private-information-value curriculum. It does not imply that public behavioral
inference is unnecessary. Before making information-use claims, expand the
parent horizon/support and explicitly require positive-S coverage.

An additional legacy regression run found two pre-existing failures outside
this isolated corpus: the old `test_core` prompt-source hash is stale, and
`test_next_training` expects different one-checkpoint retention. The involved
`core.py`, `checkpoints.py` and `social_named_probe.py` match HEAD and were not
modified here; those failures are not represented as passing checks.

## Existing pipeline for terminal utility (historical corpora)

The following protocol and commands describe the existing pipeline for the
previously frozen reference corpora. `build` and the slice rollout still use
their terminal-utility contracts; they do not freeze or train the current
next-own cutoff oracle. A corpus and reward/continuation contract under that
new objective must be defined and integrated before a current-protocol run.

### Frozen protocol

* Generate a larger model-independent candidate pool. Keep solvable native
  parents with at least one retained consequential window. Both training arms
  use the exact same 100 parents and public prior; both sample hidden worlds
  from that prior. Record every rejected candidate, including solver cycles,
  tree/time limits and zero-slice parents. This tests the selected solvable
  domain, not the population of unrestricted generated BENAC games.
* Train/validation/test have 100/20/40 parents. The constructed quick version
  uses the authorized approximately **2:1 two-player/three-player ratio**.
  Canonicalize public topology under player, action and goal renaming, including
  schedule, scoring modes and coordinate counts. Assign a whole family to one
  split using deterministic player-count quotas; at most eight parents per
  family. Model responses never enter generation or split assignment.
* Parents start with zero commitments and untouched per-player investigation
  budgets. Preferences use explicit independent public type supports and four
  background priors. Every player wants at least one goal; every goal has a
  fixed non-neutral player, and every player participates in a public goal.
  Goals have unique requirement sets. Keep binary, linear and mixed scoring.
* Entrances are sampled from **all-player 0.25-uniform/0.75-reference** reach
  trajectories. Record the entire legal path, focal player's own type/private
  answers and exact posterior over compatible worlds. The sampled actual
  hidden world is never placed in a model prompt. This is a declared entrance
  distribution, not exhaustive enumeration of all information sets.
* Test `k=1,2,3` focal decisions on every reached branch. Compute exact
  `V_star`, `V_min` and `C_span=V_star-V_min` against fixed other-player and
  exit policies. Keep `C_span>0.1` goal-completion points; retain longer
  windows when span increases by more than 0.05. Cap eight windows per parent,
  round-robin across focal roles, lengths and information-value strata.
  Overlapping windows can remain within a parent and their identity is recorded.
* S is the ex-ante value of a named private investigation answer, with the same
  physical tree and reference opponents. Store free-query S and
  `S_given_query`. It is a diagnostic stratum, not a positive-S requirement.
* Parent sampling uses shuffled uniform cycles across updates. Slices sample
  uniformly within each selected parent. **No D weighting** or adaptive
  curriculum in this first comparison. Optional slice evaluation reports D
  as `V_star` minus mean model terminal utility, alongside completion rates.

### What each arm learns

**Slices:** the model controls the focal player's next `k` actual decisions.
Other players follow the certified fixed reference. After the window the
reference also controls the focal player until the native terminal. Reward
is the focal player's **own terminal utility**, not a static action label or
a sum of regrets along a recorded oracle path.

**SP:** every player uses the current model from the same parent's initial
state to the native terminal. Each player receives its own terminal utility.

Within each group, four replicas share the sampled hidden world. Other-player
reference sampling in slices and model generation have separate recorded seeds.
Group-center/standardize terminal rewards; average each player's trajectory
over its decisions. If any replica fails, disable that entire group's task
advantage; give only the observed invalid/truncated call the independent -0.2
protocol advantage. Both arms have **no retry**, no fabricated terminal reward,
and no positive-only resampling. Infrastructure errors stop the run.

This comparison measures the entire slice training procedure. Reference
opponents/continuation, entry selection, shorter trajectories and repeated
visits all differ from complete SP. It does not isolate C-selection as the
only cause of a possible improvement.

### Build and CPU acceptance

Run from repository root; generated corpora remain under ignored `new/local_data/`.

```bash
python -m training.strategic_slices.build \
  --output new/local_data/strategic_slices_fresh \
  --train 100 --validation 20 --test 40 \
  --three-player-fraction 0.333333333 \
  --max-entrances 6 --entrance-trajectories 6 --solver-seconds 5

python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_fresh --arm slices --check-only
python -m training.strategic_slices.train \
  --data new/local_data/strategic_slices_fresh --arm selfplay --check-only
python -m unittest training.strategic_slices.test_pipeline new.benac_slice_pilot.test_pilot -v
python -m training.strategic_slices.audit \
  --data new/local_data/strategic_slices_fresh --output /tmp/corpus-audit.json
```

Tests solve six checked-in native fixtures afresh; they do not depend on a
local generated dataset. A smaller end-to-end mock check:

```bash
python -m training.strategic_slices.build \
  --output new/local_data/strategic_slices_smoke_new --train 4 --validation 2 --test 4
python -m training.strategic_slices.smoke \
  --data new/local_data/strategic_slices_smoke_new \
  --output new/local_data/strategic_slices_smoke_run_new
```

An interrupted build keeps its accepted parent/slice files, references and
generation log. `--reuse-qualified /path/to/old-build` can reuse references
produced by this generator in a fresh output directory. Each reused policy
is independently checked for fixed-point stability, deviations, privacy and
all native transitions; changed policies are rejected. Incomplete corpora
never receive `COMPLETE.json` and cannot be loaded for training.

The quick domain bounds private support to at most three variable preference
slots and public geometry to one/two commitments per player and two/four
goals. Three-player games have one proposal round; two-player games have
one/two rounds. This is deliberately small enough for exact all-branch
reference evaluation. Longer three-player negotiations are not certified by
these CPU checks.

### GPU training

Use the existing provisioned SoC environment; no automatic installations or
model downloads. Copy the generated dataset with `references/` and its
manifest along with the new source code. The data is ignored by Git and must
be transferred separately. Two separate submissions:

```bash
bash examples/strategic_slices/submit.sh h100-96 slices /absolute/path/to/dataset
bash examples/strategic_slices/submit.sh h100-96 selfplay /absolute/path/to/dataset
```

Single-H200 execution uses `h200-141`. For a first real GPU update, set
`STRATEGIC_PAUSE_AFTER_UPDATES=1`; this is an optimizer-boundary acceptance
run, not a training result. Resume with the completed checkpoint as the fourth
argument and omit that pause variable. Native resume requires unchanged
arm, data hash, base model, token horizon, sampling/validation protocol and TP.

The Python entrypoint can also run directly:

```bash
python -m training.strategic_slices.train --data /absolute/path/to/dataset \
  --arm slices --model /local/Qwen3-4B-Instruct-2507 \
  --output /new/run-directory --profile h100-96
```

Both arms use BF16, LR 1e-6 with the existing response-token cosine schedule,
PPO clip 0.2, frozen-base KL coefficient 0.01, one policy update per batch,
4096 total context / 1024 generated tokens, temperature 1 and unfiltered
top-p 1. Default budget is 6,553,600 response tokens, target 65,536/update;
finish the current complete group at the boundary and report overshoot.
Validation and oracle computation are **separate costs**. The identical
budget is a nominal stopping target, not a claim of byte-exact token equality.

`experiment.json`, `source_manifest.json`, `model_hashes.json`, `calls/`, `games/`, `units/`,
`metrics.jsonl`, `parent_exposure.json` and native checkpoints retain the
protocol and evidence. Nonfinite actor/behavior probabilities stop training;
finite numerical discrepancies are logged using the existing runtime policy.
Q0 validation runs before the first update, then every ten updates and at the
final budget boundary. Test files are never loaded by the training entrypoint.
Use `LAST_CHECKPOINT` as the primary result, not a test-selected checkpoint.

### Frozen test and paired efficiency report

Export each arm's final native checkpoint using the existing HF export tooling
and serve each export on an OpenAI-compatible **native tool-calling** endpoint.
Keep the same server profile, parser, seeds and 1024-token output cap for both.

```bash
python -m training.strategic_slices.evaluate --data /absolute/path/to/dataset \
  --split test --base-url http://127.0.0.1:8000/v1 --model MODEL \
  --checkpoint-hash ACTUAL_WEIGHT_HASH --output /new/SP-test --repeats 4
# Repeat for the slices final model, writing /new/slices-test.
python -m training.strategic_slices.compare --sp /new/SP-test \
  --slices /new/slices-test --sp-training /SP-training-run \
  --slices-training /slices-training-run --output /new/comparison.json
```

Test modes are complete **same-model teams** and a **focal model at every seat
against fixed reference counterparts**. The latter makes individual utility
comparable independently of changing teammate behavior. Report completion,
conditional player utility, conservative full-cohort utility bounds, and
paired differences with parent-level bootstrap intervals. Failures never
receive invented utility. `--modes team focal_reference slices` additionally
measures window D. The comparison also collects validation learning curves
against actual training response tokens and records paired coverage.

CPU mock execution does not validate Megatron updates, CUDA memory, weight
synchronization or GPU checkpoint recovery. Those require the first real
GPU acceptance run; this change does not submit training jobs automatically.
