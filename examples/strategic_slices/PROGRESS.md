# Strategic slices：当前进度与历史 checkpoint

## 2026-10-16：v6训练完成即补位

已移除训练的wave barrier和底层整批generate barrier。全局32个未完成回答，
vLLM增量提交、原生ID/token/logprob回收；driver不等全部worker。预选均匀样本
一完成即可推进，剩余兄弟保留原评分快照并继续生成；8齐才算优势，整批排空才
更新。20节点预算预留、奖励/loss和恢复语义保留；旧source/checkpoint拒绝混续。
59项CPU回归通过，包含长短交错、跨worker回收、失败abort/flush、完成顺序
不改变采样/奖励/批次/恢复；GPU吞吐和显存待smoke。validation/test本轮未改调度。
详细记录和新source overlay见[补位验收](../../new/terminal_refill_readiness_20261016/README.md)。

## 2026-10-16：v5实现与训练准备

已将训练入口替换为同节点8回答、负regret、节点内mean/std GRPO、随机推进1条。
节点/回答等权、token平均；默认20实际节点组，剩余k预留使默认最多超2组。
所有候选/失败计费，失败task取全部合法动作最差值，独立protocol −0.2。
保留500K验证/1M恢复保存、best+final与自动final-test；新增regret、信号/动作
重复、真实链/节点曝光和耗时日志。离线native replay适配新采样种子并保留旧D审核。
旧checkpoint和旧入口题数参数不兼容；从base开始。当前仅本地验收，未提交GPU。

验收证据和剩余问题统一见[准备检查](../../new/terminal_node_grpo_readiness_20261016/README.md)，
实际命令见[当前训练文档](TERMINAL_TRAINING.md)。真实模型信号、GPU显存/速度与
optimizer恢复待smoke；匹配SP训练臂和强信息held-out仍未补齐。下方是此前讨论历史。

## 2026-10-16早先：文献核对与协议决定（实施前历史）

**最新决定：连续oracle价值reward已采纳，尚未实现。**合法动作使用Q/负regret，
保留严格0/1最优率评测，等值组task优势为0；标准节点GRPO及随机单路推进不变。
连续reward恢复已采到的价值差异，不自动解决重复错误动作。用户随后确认：
节点组/回答等权、回答内token平均；update目标20个实际节点组、完整采完已
开始的链后一次更新；失败task取最差合法动作的负regret，另加独立−0.2协议
惩罚。20是实际组数目标，不是有效组目标；不默认动态过滤补采。记录与证据见
[专项记录顶部](MULTITURN_GROUPING_REVIEW_20261016.md)，本轮仅更新文档。

**已定采样方案：**同上下文采8个回答、连续oracle价值、组内优势，均匀抽1个
原始回答推进，最多k个focal节点；固定采样期权重。
只选此credit方案，不增做方法对照；原slices/SP比较保留。尚未实现，当前旧
local-LOO不等于新方案。节点权重、batch和失败评分均已确定；选集信号/信息held-out/
新sampler验收待完成，详见[协议顶部](MULTITURN_GROUPING_REVIEW_20261016.md)。

**此前batch/二值零方差组文献补充（历史，reward已更新）：**已区分原论文rollout batch、mini/microbatch与
optimizer step；20×8仍只是候选尺度。DAPO带上限过滤补采有直接针对性，但
不能教会持续全错题，且需明确protocol/KL及成本口径，尚未采纳。旧14道全错题
均k=1，不能期待多轮分组自动修复；先检查训练设置下binary contrast及D/native
差异，记录见同页“更新batch与二值奖励零方差组”。本次未修改训练代码。

**最新讨论：保留中间oracle监督，先查清多轮如何形成可比组。**当前local-LOO
不是同决策上下文的局部GRPO；但跨状态baseline不等于普遍无效的策略梯度。
已核对GiGPO/HGPO与Tree-GRPO/ARPO的论文及关键公开实现，见
[多轮采样与分组专项记录](MULTITURN_GROUPING_REVIEW_20261016.md)。同上下文
追加采样、重复状态复用与有限分叉预算均未实现为新合同；不默认采用下述早先
outcome-only建议，不将专项诊断直接宣称为训练退化的已证实原因。

**同日研究边界澄清：研究slices相对SP的效率，不研究新的GRPO方法。**固定成熟
训练算法、两臂保持一致；没有充分项目动机，不引入其他论文的算法改版或新组合。
下述初次文献讨论中的算法候选尚未采纳，不作为实施清单。“不标准GRPO”的笼统
说法已更正为原论文outcome/process与当前local-LOO之间的具体差别，见报告顶部。

**同日追查：**已对照七篇接近的工作及当前适配的仓库记录。多轮并不阻止使用
整轨迹outcome GRPO；目前没有local-LOO必要性的本项目对照证据。建议回到有
明确出处的基线定义，并区分算法选择与reward目标，详见报告“同日追查”。尚未
将此建议实现为新训练合同，未运行新实验。

已阅读并对照原论文及代码，见[训练protocol review](TRAINING_PROTOCOL_REVIEW_20261016.md)。
本次没有新模型运行；旧训练、数据和候选v4合同不改。主要结论：连续oracle Q
在理想单步目标下仍以最优动作集为最大值，但固定KL可能保留次优概率；不能直接
用这个结论证明现有多步local surrogate收敛。此前提出的RLOO/固定长度归一化与
同state适配等均为未采纳候选，现阶段先明确现有实现及其出处，不默认切换算法。
不再以继续调batch或重复次数替代目标、credit和探索审计。

## 当前进度（2026-10-08 仓库核对）

**当前已完成 terminal v4 候选池、真实 base-model D、100 题首版选择，以及
逐步 binary reward 训练入口、真实 GPU smoke/resume，以及部分预算训练和导出评测。
训练已到 550 updates / 3,500,783 response tokens，尚未完成 6M 目标。**
本节合并当前远端执行证据与本地进度文档，不代表新增实验结果。
下方按日期保留历史 checkpoint，其中“待测 D / 尚未选题”等只适用于当时阶段。

**同日训练审核与代码修订：**已检查全部 550 次更新、55 次训练后 validation
及 base，见 [完整审核/曲线/复现](../../new/terminal_training_review_20261008/README.md)。
中期输出失稳、后期验证下降；2,200 组仅 699 组有非零 task advantage，信息题
2,112 条轨迹只有 17 次首步正确。新训练合同 v4 默认改为 20 题 × 8 trajectories，
500K tokens 验证 / 1M tokens 恢复保存；并发32，best/结束/暂停立即保存。
新批次 30 项 CPU 检查通过；真实 v4 数据 mock 为 20 题 / 160 trajectories /
242 controlled calls，下一批恢复一致，待 GPU 验收。旧 v3 运行的结果和
checkpoint 保留原身份。

**逐题诊断补充：**对齐100题的22轮历史，27题永久无task advantage（14全0、
7全1、6整组对错切换），73题至少一次active。最后5轮连续无信号的65题中，
38题此前有过信号；14道持续全错题的后4轮全部固定于错误动作。信息题227/264
组active，但7/12题始终未选对首步，见 [逐题采样证据](../../new/terminal_training_review_20261008/signal_history/README.md)。

### 当前口径与完成情况

当前采用 `initial-terminal-oracle-consistent-v1`：每个 parent 保存一个从原生
初态求解并独立认证的完整终局参考剖面。入口概率、posterior、partner 行为及
focal 离开 k 步窗口后的 continuation 都使用同一保存剖面，窗口内不重新求均衡。
k=1/2/3 计 focal 实际 decisions，包括 proposal、调查和 response；C/S/D 的
效用基准仍为 native terminal utility。它与 10-02/03 的 bounded cutoff 方案
是不同合同，旧数据与结果保留各自身份。

| 阶段 | 已完成的进度 | 证据入口 |
| --- | --- | --- |
| Terminal v4 候选池 | 100 parents / 800 questions；train/validation/test 为 63/12/25 parents、504/96/200 questions；双人/三人为 50/50，含 30 个双人双轮 parent | [候选与信息覆盖](README.md)、冻结 v4 manifest |
| 信息案例 | 6 个强主动调查 structural families，保护 12 个 k=2/3 acquisition windows；保留 10 组 entry-answer contrasts | [入口信息定义](ENTRY_INFORMATION.md)、[v4 分析](TERMINAL_D_V4_ANALYSIS.md) |
| 真实 D | v2 的 722 道相同题与 job 915300 的 78 道 delta 题组成 800 题 / 6,400 trajectories；6,200 到达 terminal，153 truncated、47 invalid | [v2 原始运行](../../new/strategic_slices_terminal_d_20261005/README.md)、[v4 delta](../../new/strategic_slices_terminal_d_v4_20261006/README.md) |
| 逐步 native 审核 | 全部 6,400 trajectories 重放；每个受控 decision 核对 posterior/Q/action gap；9,929 calls 通过同题面 Q 一致性审核 | [完整审核与选择报告](TERMINAL_D_V4_ANALYSIS.md) |
| 首版训练选集 | 100 道 train 题，来自 56 parents / 37 families；k=1/2/3 为 52/29/19；双人/三人及 proposal/response 均为 54/46 | [选集与打包说明](TERMINAL_D.md) |
| 在线训练、验证与最终测试 | 数据加载、k-step rollout、逐步评分、sampler resume、best/final 保留与预算完成后的自动 test 均已接入 | [训练合同与手动命令](TERMINAL_TRAINING.md) |
| 历史 v3 本地验收 | 29 项回归通过；真实数据 mock 一次 update 为 4 题 / 32 trajectories / 60 controlled calls，下一批恢复结果一致 | `new/local_data/terminal_training_mock_v3_fixed_batch/CHECK.json` |
| GPU smoke/resume | 单 H100-96、TP=1；jobs 915648 / 915674 均退出 0，真实 optimizer 更新、权重同步、checkpoint 与 native resume 通过 | [GPU 验收记录](../../new/terminal_training_single_h10096_smoke_20261006/README.md) |
| 部分预算训练与评测 | job 915731 暂停于 550 updates / 3,500,783 tokens；best 为 checkpoint-379，latest 为 checkpoint-549；两者已导出并评测 frozen terminal test 与全部 24 个 CalBench cases | [原始训练、评测和审核](../../new/terminal_hf_test_calbench_20261008/README.md) |

选集保留全部 12 道强 acquisition windows，以及 9 组完整 train entry-answer
对照（27 道题）。其中 88 题观察到 decision-gap 或完成状态差异；12 题为
完整信息对照保留，在这八次抽样中未观察到同题差异。不要求每个 parent 各选一题，
不使用 validation/test 的结果选择 train 题。

### 当前训练配置

新运行 contract：`terminal-step-binary-shared-reset-loo-fixed-questions-v4`；已归档的 job 915731 使用 v3。

- 模型：Qwen3-4B-Instruct-2507；新默认每 update **20 道题 × 8 trajectories**，并发容量 32。
- 同组共享 entrance、hidden world 和 focal；model/reference 随机流分别独立。
- 每个受控 decision 的 oracle-correctness reward 为 0/1，所有最优平局动作均接受，容差 `1e-7`；其他 replicas 的平均得分作 baseline，不做 std normalization。
- 截断/非法调用得 0，并仅在失败 call 上加独立 **−0.2 protocol advantage**；保留有效 prefix 的局部得分，失败 terminal utility 为 null，无 retry。
- 训练/validation 输出上限 **1024 tokens**，context 16,384；历史 D 使用 4096 输出 tokens 和独立 resets，不能直接当作共享-world训练组的活跃率。
- 总预算 **6,000,000 response tokens**，完成当前 update 后停止，可超出目标；validation/test/oracle 成本另计。
- 默认每 500K tokens 与正常结束时 validation；恢复保存每 1M tokens，best/结束/暂停立即保存。best 按整段成功率，平局选较晚评估点，保留 best + latest/final 并去重。
- 预算正常完成后仅用 **final** 自动测试 200 slices / 25 parents，默认 8 repeats；预算未完成或暂停不触发，test 不选择 checkpoint。

这里训练的是在线局部决策正确率 surrogate；terminal utility 和 whole-window
success 是评价指标。当前实现针对选定的 slice 训练，等 token 的正式 SP 对照与
学习效率结论仍待落实及实跑。

### 最新训练结果与解释边界

GPU smoke 已验证 native optimizer/RNG/sampler 恢复。首轮 device peak 约 87.38
GiB；实际序列较短，16K 是配置容量，最长序列显存尚未验证。29/30 项相关 CPU
检查通过，一项历史 social-mixed prompt-source hash 检查失败，详见 smoke 原记录。

部分预算训练的 best/latest 已分别执行独立 HF 评测，每个模型 200 test slices ×
8 个实例和 696 局完整游戏，另有全部 24 个 CalBench cases。终局 slice 整段
成功率为 **63.6875% / 63.1875%**；25-parent paired bootstrap 的 best-minus-latest
95% CI 为 **[−6.8125, 8.0625] 个百分点**，不能由均值近似判定行为相同或谁更优。
原 Validator 重放核对两者 4,349 / 4,418 个请求，reward、score 和游戏结果匹配。

仍待完成：

1. 6M 预算尚未达到；目前保留的是 best/latest，不是正常预算完成后的 final。当前评测为独立导出评测，不能写成自动 final-test 已完成。
2. 共享-world训练实际活跃组及学习曲线已审核，见本页顶部链接；下一步验收新批次、改善首步信息学习并落实等 token SP 对照。现有 best/latest 结果本身不证明训练优于 base 或 slices 优于 SP。
3. held-out 信息覆盖和长程迁移仍不足：当前 validation/test 的信息正值入口字段均为零，强 acquisition family 仅在 train；历史 D 已查看 test，不能称为完全盲测。

强 acquisition 的 96 条历史轨迹中，80 次调查只有 9 次目标选择最优；71 次
次优调查询问的偏好在当前题面下已经可知。真正遇到 answer-dependent 最优集合
变化的 decision 只有 6 个。它们支持进一步训练与诊断，尚不能证明模型已学会
调查或使用答案。八次独立-reset D 的分离度也不等于当前训练组的学习信号。

### 仓库内复现入口

- 主导航：[README.md](README.md)；D 与数据包：[TERMINAL_D.md](TERMINAL_D.md)；训练：[TERMINAL_TRAINING.md](TERMINAL_TRAINING.md)。
- 真实模型输出归档：`new/strategic_slices_terminal_d_20261005/` 与 `new/strategic_slices_terminal_d_v4_20261006/`。
- 可通过 Git 传输的数据包：[selected-v4 archive](strategic-slices-terminal-selected-v4.tar.gz) 及 [SHA256 sidecar](strategic-slices-terminal-selected-v4.tar.gz.json)。它包含 pool、selection 和分析，不含模型权重或原始模型输出归档；包内代码是当时快照，训练应使用当前 repo。
- 解包数据、原始离线分析与 mock 在被 Git 忽略的 `new/local_data/`。冻结 manifest 中 `D_measured=false` 等是生成时的历史字段，后续 D/selection 进度以运行、分析及选择的完成记录为准，不改写旧 manifest。

```bash
# 使用当前 repo 与已解包的 v4 数据；仅离线检查，不启动 GPU。
python -m training.strategic_slices.train_terminal --check-only
```

本次 2026-10-08 核对重新执行该命令，退出码为 0：100 train slices / 56
parents、96 validation slices，final test 为 200 slices / 25 parents。
pool+selection 训练身份 SHA256 为
`6080bc30f1a70b995bb9d7bfcdc3ed633bd0ff64bfd759691cf758f4533c4379`。
输出明确记录 `model_path_checked=false`、`gpu_started=false`、`submitted=false`；
这是离线数据与配置校验，不增加 mock、GPU 或模型学习的通过项。

## 2026-10-06: accepted binary training pipeline

The selected 100 windows now have a dedicated online training collector:
shared entrance/world/focal per eight replicas, local 0/1 oracle correctness,
other-replica baseline, retained correct prefixes on later failure, and the
same frozen terminal continuation. The v2 training contract restores the old
-0.2 protocol advantage only on failed calls. Native capacity is 32, output
1024/context 16384. The previous ROLL optimizer/sync/checkpoint loop is reused. CPU checks
and manual GPU smoke/resume commands are in [TERMINAL_TRAINING.md](TERMINAL_TRAINING.md).
No GPU task is submitted; hardware memory and actual optimizer resume remain
unverified for this new configuration. Older reward proposals are superseded.
Prior v1 local evidence (4096 output, no extra penalty): 29 related checks passed; the full synthetic sweep covered
100 selected questions / 800 trajectories / 1,248 calls, with an exact repeated
next-collection resume check. Two validation questions and full-game team/focal
modes also ran under the mock generator. These are CPU plumbing results, not
model performance or GPU optimizer evidence; local Hydra is unavailable.

Final-test follow-up: training budget now exactly targets 6,000,000 response
tokens (complete-update overshoot permitted). The current v3 contract uses
four questions × eight trajectories per optimizer update; the earlier
65,536-token batch rule is superseded. Normal
budget completion saves the final checkpoint, syncs final weights and evaluates
all 200 test slices / 25 test parents, default eight fixed-seed instances. Test
tokens are separate; no checkpoint selection uses test. Pauses, early gates and
incomplete budgets skip test. Interrupted test retains the completed training
checkpoint for resume without additional optimizer updates. Fifteen focused
training/final-test checks passed; no GPU run was launched.

Checkpoint follow-up: user chose validation full-window success rate to select
best. Ties prefer the later evaluated checkpoint, including final. During
training retain best plus latest recovery point; after normal completion retain
best plus final, deduplicated to one if identical. Test remains final-only and
never selects checkpoints. Earlier-run artifacts are not automatically deleted.
Current v3 checks: 29 relevant tests passed; one stale generic retention test
now requests two slots when expecting two checkpoints (prune implementation
unchanged). Real-data mock produced exactly four questions / 32 trajectories /
60 controlled calls in one update and exact subsequent collector resume.
No native GPU optimizer/checkpoint smoke was submitted.

## 2026-10-06: v4 D complete, first train selection frozen

Real delta results are in `new/strategic_slices_terminal_d_v4_20261006`.
The offline union contains 800 questions / 6,400 original trajectories; 6,200
reach terminal. All trajectories and every controlled call were independently
replayed against the frozen native reference. Initial oracle policies were not
re-solved. Full-window analysis finds 139 train questions with same-prompt action
value contrast (116 at the root), plus separately recorded mixed completion.

The first selection has 100 train windows from 56 parents / 37 structural
families, with k counts 52/29/19 and 2p/3p and proposal/response both 54/46.
Twelve strong acquisition windows and all nine train entry-answer groups are
retained. Eighty-eight selected questions show decision-gap/completion contrast;
twelve preserve the complete answer groups without observed within-question
contrast. No test/validation outcomes drive selection. The original 100-parent
pool remains unchanged. Training and supervision export have not begun.

Acquisition diagnosis: 80 investigations across 96 strong-S trajectories, only
nine optimal query choices; 24 of 93 subsequent valid actions are suboptimal.
Only six visited decisions have a certified answer-dependent change in the
optimal action set (five valid, two optimal, one failed). This is evidence of
training opportunity, not evidence that answer-use competence has been learned.
See [TERMINAL_D_V4_ANALYSIS.md](TERMINAL_D_V4_ANALYSIS.md) for exact definitions,
checksums, selection exceptions and reproducible commands. All older sections
below are historical checkpoints.


2026-10-06 launcher update: the dedicated `terminal_d_soc_v4_delta.json` pins
the v4 manifest and automatically selects 78 pending questions (624 trajectories).
It preserves the user's 32-worker completion-refill scheduler and 4096-token
output budget. The original v2 default config and archives remain unchanged;
use the new `strategic-slices-terminal-D-v4-refill32.tar.gz` transfer bundle and
the manual commands in [TERMINAL_D.md](TERMINAL_D.md). No job is submitted.

## Historical work: game mechanism and information acquisition (2026-10-05)

The user supplied the completed v2 Qwen D results on 2026-10-05: 800 questions,
eight trajectories per question. Evidence is in
[`new/strategic_slices_terminal_d_20261005`](../../new/strategic_slices_terminal_d_20261005/README.md).
The current task improves information-dependent entrance coverage using the
paper-era training bank as a calibration, preserving the v2 checkpoint and its D.
The sections below record earlier milestones; their statements that D was not
run apply to those historical stages. No new remote jobs are authorized here.

The [v4 integration](../../new/local_data/strategic_slices_oracle_consistent_candidates_v4/audit.json)
now keeps 100 parents x 8 questions while adding six distinct certified active
acquisition structural families (five 3p, one 2p). Twenty-five canonical native
neighbors were attempted, 24 certified and one timed out; four positive families
join the two earlier witnesses. These are variations around two base mechanisms,
not six independently invented mechanisms. All six references were reloaded and
independently re-certified, with scalar-BR full/masked checks.

Six unprotected, redundant training parents were replaced, preserving exact
player/round/split quotas and all ten entry-answer groups plus four collective
controls. The 48 new questions protect 12 k=2/3 acquisition windows with S>.05
and C>.1. The other 752 v3 question records are byte-identical. New public-history
channels are unmeasured/null, and new calibrated families remain train-only.
The opt-in initial-terminal-local-decisions-v2 contract permits the certified
2p four-proposal initial entrance, with k<=3 unchanged and full-terminal guards.
The historical default three-proposal API and old records remain intact.

Against the actual v2 model run, 722 question/reference identities are reusable
and 78 need new D (30 from v3 plus 48 new). The explicit subset CLI prepares
624 trajectories, recording exact subset IDs in its resume identity. This is a
reuse plan, not an automatic merge of prior model results. No real model call or
Slurm submission has been made, and no final 100 training slices are selected.
Forty-four tests pass. All 624 delta-run mock trajectories reached native
terminal; completed-run resume generated nothing. A separate 384-trajectory
check covers all 48 new questions and verifies controlled-k handoff. The final
source-snapshot metadata update preserves every runtime input; its manifest
lineage and checksums are recorded in
[`runtime.json`](../../new/local_data/strategic_slices_acquisition_v4_validation/runtime.json).

The optional `goal_structure='multi_action'` mode is now available in
`sample_parent` and the generic build config; default `legacy` identities are
preserved. The frozen terminal candidate pipeline still uses its original mode.
One same-player requirement is added with a separate RNG, keeping catalogues,
priors, schedules, goal modes and all rules identical within each pair. A game
with no eligible addition is unchanged and cannot count as a distinct parent.

The [paired calibration](../../new/local_data/strategic_slices_goal_structure_calibration_v1/summary.json)
completed 8 pairs at a 45-second solver budget per arm: 4/8 old and 4/8 expanded
parents certified, only 3 pairs certified on both sides, no strong first-proposal
acquisition witness among the certified parents. Failed sides have unavailable
values, not zero S. This pilot does not establish a population yield effect;
structure expansion alone is not sufficient. Forty tests pass, including legacy
seed identities and the paired intervention contract. Next recommended milestone:
5–10 distinct positive information-acquisition structural families, then candidate
integration and D on changed questions. The three-proposal entrance limit merits
a separate review for already-certified parents; it has not been changed.
No frozen candidates, references, D records or transfer bundle were modified.

The [native acquisition search](../../new/local_data/strategic_slices_native_acquisition_review_v1/summary.json)
now supplies two independently re-certified initial-state witnesses. Of 130
attempts, 15 initial drafts failed native validation (generator corrected), 94
complete trees were certified, and 21 valid games failed solver certification.
The three-player witness has 18,799 nodes, entrance mass/query probability 1,
k=2 C=.45581 and S=.08333. Its answer changes the next response from REJECT
(AVOID) to ACCEPT (NEUTRAL/WANT), with strict conditional action gaps. The
two-player witness has 143,014 nodes, k=2 C=.375 and S=.10714; full-terminal
S=.21429. It starts four proposals before terminal and is therefore only a
mechanism prototype under the present three-proposal entrance rule. Both saved
profiles were reloaded, re-certified and checked with an independent scalar BR.

Six three-player controls all certify: prior changes retain S=.0625–.125;
removing the second focal action from the bonus goal yields S=0; making that
goal linear gives S=.02778; adding a public WANT to the avoid-only goal leaves
S=.08333. These findings concern selected profiles and include equilibrium
selection changes. The generator currently excludes multiple requirements from
the same player within one goal, despite their legality in the native game.
Both witnesses include that missing structure. This is a concrete calibration
direction, not a claim that public-WANT anchors universally suppress information.
Fixtures and diagnostic generation/verification/control scripts are preserved;
36 tests passed at that stage, without changing production rules, generator,
candidates, references, or D. The subsequent opt-in generator extension is
recorded above. The two base structures and their prior variants are not a new corpus.

The [mechanism diagnostic](../../new/local_data/strategic_slices_mechanism_diagnostic_v1/conclusions.json)
adds six convenience parents with fixed partner profiles: 249 free single-slot
information comparisons yield only three positive gains (max .03661), all in
one three-player parent. Free revelation of every partner type has zero early
gain in the five selected two-player parents and up to .09117 in the three-player
case. Removing the opportunity cost alone is therefore not a sufficient
explanation for this sample. These are information interventions, not modified
game equilibria. Legal unilateral offers, rejection without extra penalties,
linear payoff separability (37 parents), public-WANT anchors and repeated turn
order are structural hypotheses; their individual causal effects remain open.
The old external-PASS fixture retains S=.25, but its full initial reference
failed certification twice. The native schedule comparison is incomplete and
does not establish a schedule effect. Production artifacts are unchanged;
34 regression tests and independent signal-conditioned BR checks passed.

The [early-investigation audit](../../new/local_data/strategic_slices_early_investigation_v1/summary.json)
is complete: all 100 parents, 250 parent/player pairs, and 8,357 reachable first
proposal information cells, including 88 excluded by the three-proposal entrance
neighborhood. Full-terminal focal best responses show 2,573 query/non-query ties,
5,783 query-inferior cells, and just one strict advantage of .0138533; none exceed
.05. Prohibiting all future focal investigations preserves optimum value in all
but that same cell. Even its gain survives masking the selected private answer
through terminal (S=0), so it is an action/continuation advantage, not evidence of
positive private-answer value. Partners remain on the same saved oracle profile.
528 cells have both an unknown query answer and a subsequent focal proposal;
none have strict acquisition-action advantage. The active-acquisition coverage
gap is therefore still open after restoring early entrances and full lookahead.
No dataset, game, reference, or model job was changed by this audit. 31 tests and
independent native subtree/action-removal checks passed.

The [v3 candidate revision](../../new/local_data/strategic_slices_oracle_consistent_candidates_v3/audit.json)
keeps all 100 original parents/references/splits and exactly eight questions each.
An exhaustive reachable-entrance scan found 220 strong existing-answer contrasts
in ten parents, among 9,209 measured groups. None of their members occurred in
the original 800-question subset. The revision retains ten complete must-change
groups (30 fixed-information questions; train 9 groups, test 1, validation 0).
Selected conditional entry-answer S ranges from .05357 to .31884. Query-acquisition
S is unchanged. A group S is not a singleton label and is not counted 30 times.

770 questions are unchanged; 30 require new D. `D_reuse.json` records this mapping,
but the existing v2 run cannot be resumed directly against a changed manifest.
The revision independently checks selected S through masked dynamic programming
and verifies new member C/posteriors against the saved oracle. No new equilibrium
solves, model calls, training, or final 100-question selection were performed.
See [definitions and selection](ENTRY_INFORMATION.md#existing-private-answers-one-decision-entry-contrasts-2026-10-05).

## Historical milestone: prepared base-model D pipeline

The user requested a complete SoC pipeline using Qwen3-4B-Instruct, with **no
automatic job submission**. [TERMINAL_D.md](TERMINAL_D.md) documents the launcher,
historical environment provenance, offline bundle and explicit manual commands.
The configured checkpoint is Qwen3-4B-Instruct-2507, matching recorded SoC runs.
Each of 800 candidates receives eight independent resets/rollouts, not two groups.
The current user-requested serving profile is **16 workers and 4,096 output
tokens** (context remains 16,384); the full mock below used the earlier 4-worker,
1,024-output-token profile. Updated defaults receive local regression/config checks.
Partners and post-k focal actions use the saved initial terminal reference.
The pipeline reports D, D/C, uncertainty, protocol failures and observed signal
diagnostics; it performs no training or final 100-slice selection.

The new CPU runtime/transport/recovery tests plus candidate/oracle consistency
regressions passed (22 tests). The full CPU mock completed all 6,400 trajectories;
independent native replay verified all final utilities, 10,261 model decisions
and 1,269 post-k focal reference decisions, including all 32 collective-control
trajectories. Complete-run resume made zero new generation calls. The transfer
archive passed all 1,045 file hashes and an offline check from an isolated extracted
directory. [Local validation record](../../new/local_data/strategic_slices_terminal_d_validation_v1.json).
These are engineering checks, not model D or learning evidence.
Actual GPU/model execution remains untested locally.
No Slurm submission or remote operation has been performed.

## Completed working milestone

[Current balanced subset](../../new/local_data/strategic_slices_oracle_consistent_candidates_v2/REPORT.md):
**100 unchanged parents, exactly 8 candidates per parent, 800 candidates.**
This is an unchanged-record subset of the audited v1 pool below. All references,
parents, splits and C/S values are preserved; the original 1,596-row pool remains available.
Exhaustive within-parent selection balances player counts, then k, then decision
kind; diversity and cumulative distribution break ties. All available player/k/kind
categories and all four collective controls are preserved. See `balance.json` and
`selection_ledger.jsonl` for the complete policy, counts and selected IDs.

- k=1/2/3: **365/279/156**; proposal/response: **396/404**.
- Two-player seats 0/1: **200/200**; three-player seats 0/1/2: **136/130/134**.
- All 30 multi-round parents retain k=2 and k=3. There are 728 distinct public
  entrance nodes and 812 member records (collective controls have multiple members).
- Subset integrity and loader validation passed. Original independent audit
  evidence is inherited, not presented as a new 800-row solver/C/S audit. No D run.

### Original verified pool (preserved checkpoint)

[Verified candidate pool and report](../../new/local_data/strategic_slices_oracle_consistent_candidates_v1/REPORT.md):
**100 distinct parents, 62 structural families, 100 full initial terminal references,
1,596 candidates across 1,268 distinct public entrance nodes.**

All 100 references independently re-certified; 1,608 candidate members had their
C/V values and prefix posteriors rechecked; 104 S records were remeasured.
Maximum retained-window deviation over the reference is approximately 1.60e-9.
The final related regression suite passed **62 tests**.

Coverage: 30 two-player/two-round, 20 two-player/one-round, and 50 three-player/one-round
parents. Every multi-round parent has retained k=2 and k=3 candidates. No D was run;
the final 100 slices are **not** selected. The working 30-parent multi-round floor
does not establish the final research coverage requirement.

## Objective

Collect 100 canonically distinct parent games, retaining multiple representative
oracle-consistent slice candidates per parent. Final selection of 100 slices
requires future D evaluation. **Do not run D in this attempt.**

Every parent uses one saved, independently certified initial-state terminal
profile. Prefix likelihoods, entrance posteriors, partner policies and focal
continuation all refer to that profile. No random-prefix belief reset, independent
entrance re-solving, cutoff payoff substitution, or support shrinkage.

## Starting checkpoint

[Checkpoint metadata](../../new/local_data/strategic_slices_checkpoint_20261004_before_optimization/checkpoint.json)
and its SHA-256-addressed archive preserve the pre-optimization code and active
candidate corpus. Unrelated working-tree changes are excluded.

- 70 selectable parents: 28 two-player and 42 three-player.
- Only one multi-round parent; 1,116 retained candidate windows.
- These are generated/review candidates, not a fully audited final dataset.
- No retained row currently exceeds the S > .05 information-positive threshold.
  This must remain visible as a mechanism-coverage limitation.
- The previous 47-parent mixed-reference corpus is historical and is not the
  current progress count.

## Current attempt

New results are written to
`new/local_data/strategic_slices_oracle_consistent_search_v2/`; v1 is preserved.

Working generation coverage target: at least **30 multi-round parents**, where
multi-round means at least two complete proposal rounds. This is an operational
target chosen for this attempt, **not a quota previously fixed by the user**.
The existing 50/50 player balance, canonical duplicate checks, family cap of 8,
and up to 16 candidates per parent applied to the original generation pool.
The subsequent user-requested balanced subset retains exactly 8 per parent.
Generation selection prioritizes multi-round
parents; packaging refuses to complete if the coverage floor is unmet.
Three-player multi-round coverage and horizons beyond two rounds remain open.
Native round count alone does not demonstrate multi-step strategic difficulty;
the retained k and decision-capacity distribution must also be reviewed.

Short-parent expansion was held while the multi-round search was validated.
After reaching 50 two-player / 42 three-player parents with 25 multi-round
parents, short sampling resumed only to fill the three-player quota. Two-player
short jobs skip automatically at quota; the multi-round packaging floor remains.
The first new batch comprises 24
independently seeded two-player, two-round native games, using the existing
generator without altering their supported worlds or payoffs after sampling.
Budget: 240s solver, 8 ordered sweeps per start, 8,192 joint cells; each accepted
profile still requires the original complete scalar certification and native audit.

That first batch finished with **16 verified and measured parents / 8 uncertified**,
and no solver timeouts. Canonical duplicates and family caps are applied after
measurement, so successful attempts do not each add a distinct selected parent.
Further independently seeded batches filled the working count/coverage requirements;
generation stopped at a completed batch boundary once both were met.

## Verified engineering progress

A vectorized local-support/tie screen rejects clearly invalid candidates before
full certification. It batches array operations, not histories or information
sets. Passing the screen never grants a certificate. The original scalar
`certify_policy` and its numerical tolerances remain unchanged.

- Existing failed two-round case 47: 90.62s before versus 20.73s with screening
  at the same two-sweep cap; both reject the candidate.
- Case 47 with eight ordered sweeps: 20.18s including full certification/native
  audit, now certified. Re-measurement produced 16 candidate windows.
- Case 41 remains certified; its saved policy hash is exactly unchanged in the
  two-sweep comparison. Total time fell from 20.07s to 16.31s.
- Cases 37 and 48 still failed certification with eight sweeps. Optimization is
  not a claim of general convergence.
- Final candidate-screen/equilibrium/bounded/oracle/distribution/information suite:
  62 unique tests passed, including restoration with nondefault search budgets.

Results and source snapshots:
[optimization manifest](../../new/local_data/strategic_slices_solver_optimization_v1/manifest.json).

## Remaining research questions

- Whether this preliminary coverage is sufficient: three-player multi-round and
  horizons longer than two rounds are not covered.
- Strong information value: no measured S exceeds .05. Four collective records
  have small positive S (maximum .015334); other entry-history channels remain
  unmeasured/null. These limits are recorded in the manifest, not hidden by the count.
- Model usefulness and long-horizon generalization remain unmeasured. D and the
  final 100-slice selection are explicitly deferred until requested.
