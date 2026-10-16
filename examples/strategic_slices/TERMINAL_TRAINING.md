# Terminal slices v6：同节点连续奖励 GRPO

2026-10-16：已实现已确认的协议 `terminal-node-regret-grpo-refill-v6`。冻结的 v4 数据、
Qwen3-4B-Instruct-2507 和初态完整终局 reference 不变；需要从 base 开新 run。
CPU 验收与遗漏清单见[本轮记录](../../new/terminal_refill_readiness_20261016/README.md)。
**本轮没有提交 GPU 任务。旧 GPU smoke/resume 属于旧协议，不能替代 v6 验收。**
[旧 v4 文档](TERMINAL_TRAINING_LEGACY_V4.md)完整保留历史合同、命令和结果。
研究仍是 slices/SP 效率；只采用这一种已定 credit，不增加方法对照。

## 采样、评分与 loss

1. 从冻结选集100题打乱循环，按题声明的分布采 entrance、world、focal。
2. 每个实际 focal 决策上下文采8个回答。输入 messages/tools、可见信息 posterior、
   剩余 k 和 Oracle 相同，独立模型随机种子。hidden world 只用于环境执行。
3. 合法回答 `r=Q(h,a)-max(Q)`；非法/截断 `r=min(Q)-max(Q)`，min 遍历
   **全部合法动作**。Q 是相对同一冻结终局 profile、剩余窗口最优决策的价值。
4. 本节点内 `A=(r-mean(r))/(sample_std(r)+1e-8)`，std 使用 correction=1。
   组内 reward range ≤ Oracle 数值容差1e-7时 task A=0，不放大求解噪声。
   该容差不是允许次优损失的语义阈值。失败另有独立 protocol A=−0.2，
   不进入 task reward 的均值/std。
5. 生成前从8个**原始样本的位置**均匀抽定1个，重复动作不去重，不看分数。
   选定回答完成即可执行并准备下一节点，其他兄弟回答仍继续生成；它们全部收齐后
   才计算本节点组内优势。评分保留原节点的actions/Q/posterior快照，不受链推进影响。
   未选回答只评分，不展开其后缀。抽中失败则终止，无重抽/补答/Oracle修复。
   reference 推进后到下个 focal 节点再采8个，最多 k=1/2/3，提前终局不补齐。
6. 所有回答训练，各节点组等权、组内8回答等权、回答内 token 平均。
   task、protocol、KL 同权；取消旧入口链 `1/T`。本节点 A 仅作用于本回答，
   无跨状态 baseline、后续 A 回传或整轨迹奖励混合。

沿用 ROLL 的 ratio/clipping=0.2、frozen-base KL=0.01、单次 optimizer update；
全批 microbatch 梯度累积，同批只训练一遍，采样期间模型权重固定。
原生 task reward 保留效用尺度；归一化会改变节点相对权重，不能据此声称等价于
整局 terminal-return policy gradient，也不保证有限训练必然得到最优动作。

## 批次、预算与记录

- `--node-groups-per-update` / `TERMINAL_NODE_GROUPS_PER_UPDATE` 默认20：
  是**实际节点组数目标**，不是入口题数，也不是非零优势组数。约160个回答。
  已开始的链采完再更新；用剩余 k 预留名额，默认最多超2组，即160–176回答。
  输出长度和提前终止影响入口数；不能再宣称每5 updates遍历100题。
- 并发32是全局未完成回答上限，采用 `completion-refill-v1`，不再是整批barrier。
  某个回答完成就释放名额，优先填已准备的节点回答；有预算时再接新入口。
  不等最初32个全完，也不只允许4个入口链。已提交但未完成的长回答始终保留。
  较低并发也能把一个8回答组分批生成后统一评分。
  不筛零方差组、不补采、无自适应 G。所有回答及失败 tokens 都计入预算。
- 训练6M response tokens，完成当前批次后停止，允许超出一批。输出1024 /
  context16384、temperature=1、top_p=1、top_k=−1。context 超限报错不裁剪。
  token-progress cosine LR 1e-6→1e-7；max_steps=10000只是安全上限。
- 验证每500K训练 tokens，恢复保存每1M。base、正常结束评测；新 best、
  结束/暂停立即保存。同一步去重，保留 best+latest/final。默认无每步验证/保存。
  显式 `--eval-every` / `--save-every` 只在 smoke 覆盖更新步数调度。
- `calls/step-N.jsonl`：所有回答、实际 prompt、token/logprob、Q/posterior、
  reward/advantage、scoring identity、selected 标记；私有评分字段不进入模型请求。
- `units/step-N.jsonl`：每个实际节点组的8个 reward、std、选中序号、动作数、
  task/protocol活跃状态；`games/`：每入口**一条实际推进链**，含所选节点引用。
- `metrics.jsonl`：实际组/入口/回答数、超额、task零信号组、单动作/平坦Q组、
  root与信息题严格正确数、连续regret、失败和completion；另记 collection、
  action-value查询、等待生成回收耗时。记录`scheduler_peak_inflight`和
  `scheduler_native_ticks`；reference恢复/构建等耗时包含在collection剩余部分。
  `collector.exposure`分开记录每题entries/node_groups/responses/completed。

基础设施、Oracle 或 behavior tokens/logprobs 错误中止 collection，不提交 cursor。
恢复仍从最近完整 optimizer checkpoint 开始；数据/版本/种子/采样/预算/source
合同严格一致。旧二分/local-LOO checkpoint不兼容，不能直接续跑旧job915731。
旧 `--questions-per-update` 已移除，旧环境变量显式报错，防止静默更改含义。
v6记录新的调度合同；v5 checkpoint/source也不能静默续跑，reward和loss没有变。

底层复用现有vLLM adapter的`add_requests/fetch_output`，独立request ID匹配
原生tokens/logprobs。每个worker最多一个RPC在操作engine；有完成就返回，
没有完成也最多16次engine step即交还控制，driver用`ray.wait(...,num_returns=1)`
回收任一worker，不等所有replicas。同组请求不做DP虚拟padding。收集失败先abort/
flush engine，再离开session；所有候选排空后才允许optimizer、offload或权重同步。
GPU始终有工作还取决于CPU能否准备新节点、剩余预算和链依赖；不是32条永远满载
的保证。本轮只替换训练采样路径，低频validation/test暂沿用原同步生成路径。

## 本地验收与源代码同步

在有 numpy、torch 的现有 Python 环境运行（本机 `/opt/anaconda3/bin/python`）：

```bash
python -m training.strategic_slices.train_terminal --check-only
python -m unittest training.strategic_slices.test_terminal_training training.strategic_slices.test_terminal_schedule training.strategic_slices.test_terminal_final_test training.strategic_slices.test_terminal_checkpoints training.strategic_slices.test_terminal_analysis training.strategic_slices.test_terminal_d training.social_mixed.test_native_limits training.social_mixed.test_probability_diagnostic training.social_mixed.test_efficiency.EfficiencyTests.test_padding_preserves_weighted_gradient_for_all_profiles training.social_mixed.test_native_stream training.strategic_slices.test_terminal_refill
python -m training.strategic_slices.train_terminal --mock --mock-updates 2 --output /tmp/terminal-node-mock
```

`--mock`使用同步adapter，只验证协议/数据/恢复；长短交错补位由上述stream测试验证。
mock 使用真实冻结题/Oracle和合成模型回答、tokens/logprobs，验证下一批精确恢复。
它不是实际模型信号、真实 tokenizer、GPU optimizer 或收敛证据。reference树恢复
有CPU成本，mock也可能需数分钟。`--check-only`只核验数据和配置，不检查本地权重/GPU。
已有 selected-v4 数据包仍可使用；**只复制其中 `new/local_data/` 数据到当前 repo**，
不要用包里的旧 source 覆盖 v6。新 source overlay 可由
`python -m examples.strategic_slices.prepare_terminal_training_bundle --output /tmp/terminal-node-v6.tar.gz`
生成，用于已有完整 MARSHAL checkout/环境；不含数据、权重或依赖。

## GPU smoke 与正式启动（供手动执行）

沿用 SoC 已有 conda/CUDA/ROLL 环境和本地权重。默认2×H100-47；之前验证过的
单H100-96需同时设置 `SOCIAL_GPU_PROFILE=h100-96-single` 并覆盖 Slurm gres。
脚本不安装/下载，不自动选择硬件。保持正式32并发、20节点预算、16K/1024，
先完成一次更新、保存并暂停（验证限制2题仅用于 smoke）：

```bash
export TERMINAL_NODE_GROUPS_PER_UPDATE=20 TERMINAL_TOTAL_TOKENS=6000000
export TERMINAL_MAX_STEPS=3 TERMINAL_EVAL_EVERY=1 TERMINAL_VALIDATION_LIMIT=2
export TERMINAL_PAUSE_AFTER_UPDATES=1
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

保持同样配置和 source，恢复至新的 output（不要更改节点预算/profile/max_steps）：

```bash
export TERMINAL_RESUME=/absolute/path/to/first-run/checkpoints/checkpoint-0
export TERMINAL_PAUSE_AFTER_UPDATES=2
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

检查 COMPLETE、RESULT、LAST_CHECKPOINT、cursor/曝光递增、实际节点组数和生成token
对应；optimizer每批只更新1次、norm参数确实变化；task/protocol/KL梯度有限。
核对 `behavior_probability_warning` 和 `probability_warnings.jsonl`：继承的概率检查
对有限偏差只报警，不自动停止。新sampler在真实模型下的task_active、重复动作、
信息入口命中率、输出/截断、CPU/GPU耗时和显存需实测；16K最长序列尚未验收。
CPU精确恢复不等于GPU逐位浮点复现。

正式6M运行清除 smoke/resume设置，从 base 新开：

```bash
unset TERMINAL_QUESTIONS_PER_UPDATE TERMINAL_NODE_GROUPS_PER_UPDATE TERMINAL_TOTAL_TOKENS TERMINAL_MAX_STEPS
unset TERMINAL_EVAL_EVERY TERMINAL_SAVE_EVERY TERMINAL_VALIDATION_LIMIT TERMINAL_PAUSE_AFTER_UPDATES TERMINAL_RESUME
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

正式validation覆盖96 slices /12 parents，另做完整team SP和focal-vs-reference。
严格最优率接受所有1e-7内并列动作，并报告合法regret、失败按最差动作计regret、
root/信息root、whole-window success、completion、utility与失败bounds。
best只按validation整段成功率，并列选较晚checkpoint；base不参与best选择。
正常6M完成后只对final自动test：200 slices /25 parents、默认8 repeats，test不选best。
验证token累计、test token单列，不消耗6M训练预算。暂停/步数上限未完成预算不跑test。

## 仍未完成的实验条件

当前是 slice 臂的完整训练入口，**匹配的正式 SP 训练臂未由此实现或运行**；
旧通用SP模块还有label-review prompt哈希不匹配，不能据此宣称两臂已可直接开跑。
训练选题不保证每次8采样都有价值差异；重复同一错误动作仍可能没有task信号。
强信息 acquisition 的独立held-out family不足；test曾用于base D分析，并非从未
查看过的盲测。这些限制不阻止本轮slice smoke，但影响论文的泛化/效率结论。
