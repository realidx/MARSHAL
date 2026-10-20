# Terminal slices v8：可读题面与同节点连续奖励 GRPO

**原100父游戏的新机制检查已有结果：**[70等价、29新认证、1缺失](OFFER_QUOTA_ORIGINAL_POOL_RESULTS_20261021.md)。
99个有效配对真实调查见证6→16。报价额度仅在研究代码实现，尚无新的训练兼容slice/C/S/D/prompt版本；
以下v8入口仍使用旧规则，不可用这次机制统计声称新训练管线已就绪。

**当前机制研究方向：调查保持原样，只检查OFFER个人报价额度，dependent preference暂缓。**
[独立14次终局认证研究](GAME_OFFER_QUOTA_RESEARCH_20261021.md)已完成；尚未证明提高调查价值。
未将规则接入本训练入口，以下v8配置不含报价额度，不能用旧checkpoint/prompt静默运行新规则。

**2026-10-21核对：当前响应平局评分未与用户明确的游戏规范完整对齐。**参考策略有
response-only social tie，focal训练/验证却只看own Q。真实日志已验证相同自身收益、
不同others收益仍同reward的情况。下方保留v8配置及历史准备记录，不代表此缺口已修复。
[V9题面草案](versions/terminal_v9_state_draft_20261021/PROMPT_PREVIEW.md)尚未激活，
需先统一求值、训练评分和评测；见[审阅记录](PROMPT_PROTOCOL_REVIEW_20261021.md)。

2026-10-18当前版本：`terminal-node-regret-grpo-readable-v8`，prompt为
`terminal-readable-named-v2`。完整输入见[v8预览](versions/terminal_v8_readable_20261018/PROMPT_PREVIEW.md)，
逐段解释和修改见[审阅记录](PROMPT_REVIEW_20261018.md)，
全部配置见[v8快照](versions/terminal_v8_readable_20261018/SNAPSHOT.json)。公开/私有事实分表，
调查答案保留，额外来源提示删除；support在证明概率等价后改成简单抽样说明；
规则/状态/窗口文字简化。原v7保留。85项CPU测试通过；未GPU训练，不可resume v7/v6。

2026-10-17当时版本：`terminal-node-regret-grpo-named-v7`，prompt为
`terminal-september-named-v1`。完整system/user/tools见[新prompt预览](versions/terminal_v7_named_20261017/PROMPT_PREVIEW.md)，
历史和当下的逐项参数见[独立配置对照](PIPELINE_CONFIG_COMPARISON_20261017.md)，
全部默认值/source hash见[冻结快照](versions/terminal_v7_named_20261017/SNAPSHOT.json)。
恢复9月可读表格/时间线/具名工具及末尾解释要求；当前Oracle、奖励、采样和超参沿用v6。
增加explanation出现率/字符数观测，不新增解释奖励。376个context/2045动作映射和81项CPU测试通过。
尚未GPU训练；必须从base新开，不能续跑v6/job960070。每次实际run额外写
`pipeline_snapshot.json`；未登记源码或prompt变更时启动/打包失败。

2026-10-16基础协议为 `terminal-node-regret-grpo-refill-v6`。冻结的 v4 数据、
Qwen3-4B-Instruct-2507 和初态完整终局 reference 不变；需要从 base 开新 run。
CPU 验收与遗漏清单见[本轮记录](../../new/terminal_refill_readiness_20261016/README.md)。
**用户当前无法运行独立GPU smoke：不将其作为训练准备的前置条件。**
本轮采用CPU一致性/性能验收；GPU吞吐、显存和实际恢复明确保留未验证状态，
未来在同一个正式任务的前几步观察，不要求另开smoke任务。
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
的保证。训练、validation和final-test现在均已接入native完成即补位。

## 验证/测试完成即补位

- Slice评测不再按parent逐个等待：按原固定题目/replica顺序懒加载，跨parent
  共享并发名额；每条评测链同时只有一个待生成回答，完成即可推进/补位。
- 完整游戏将team与focal-vs-reference、不同parent和固定repeats放入同一个
  有界池，不再逐parent或逐mode等待最长轨迹。默认最多32个活跃episode/回答，
  episode完成立即释放树引用；不会一次性构建全部test repeats。
- 两个阶段（slice cohort、完整游戏cohort）依次执行，均使用训练已有NativeStream，
  temperature=0、1024上限、原seed/reset/Oracle和题目范围不变。不丢弃长回答
  或失败样本，不过滤困难题；最终报告仍按原固定顺序汇总，保留原parent macro统计。
- `validation/step-N.json`和`test/report.json`增加`execution`，分别记录slice/
  full-game的jobs、calls、response tokens、peak_inflight、seconds、native ticks
  和prompt tokenizations；metrics中用`eval_execution/...`单独记录验证执行成本。
  这些执行字段不进入best排序，验证/测试token不消耗6M训练预算。
- v8 final-test使用执行身份`terminal-final-test-v5-readable`，完整cohort排空
  后才写COMPLETE。中断/基础设施失败会abort/flush，保留原checkpoint，不能写成
  完成测试；已完成同身份报告复用，不重复评分。旧source不能混续。
- 旧同步实现保留作CPU报告对照及独立调用兼容；正式TerminalPipeline的validation
  和final-test明确绑定native stream。独立HTTP评测CLI不自动获得此项改动。

[评测补位验收](../../new/terminal_evaluation_refill_20261016/README.md)包含长短交错、
不同完成顺序的新旧报告一致性、native桥接CPU替身及中断/重试检查。仍不要求
独立GPU smoke，不将CPU结果写成真实GPU吞吐或显存验收。

## CPU可验收的复用优化

- Reference树从固定2棵LRU改为估算字节预算：`--tree-cache-mb`默认512，
  `--oracle-cache-mb`默认128，分别对应`TERMINAL_TREE_CACHE_MB`、
  `TERMINAL_ORACLE_CACHE_MB`。Q/延续值缓存独立，树淘汰不再清掉它们。
  超预算单项不保留，0可关闭保留；预算不是进程RSS上限，活跃rollout还会持有树。
  缓存仅在内存，不存入checkpoint，恢复重建不改变采样/Oracle定义。
- 控制窗口外查同一frozen profile的精确终局延续值，按需计算并跨posterior/k
  复用，控制窗口内仍完整枚举。不是截断utility或改变对手策略。旧完整遍历
  `extreme_value`保留用于独立CPU审核；新求值器`cached_extreme_value`用于训练
  和slice validation后续决策，冻结的root_Q和数据文件不改。
- 同stream的相同messages/tools只编码一次，prompt编码缓存预算16MiB。8个
  回答各自seed/输出上限不变，每次仍独立检查context，新增tokenization/hit日志。
- `metrics.jsonl`新增tree/oracle cache的bytes/预算/hit/miss/eviction、累计
  reference恢复时间；与已有collection墙钟和生成回收等待同看。缓存身份
  限定当前冻结dataset/reference，Q key继续包含player/node/remaining k/posterior。

[CPU验收与实测](../../new/terminal_cpu_reuse_20261016/README.md)记录新旧Q/策略
一致性与CPU求值时间，不把CPU加速写成GPU或端到端训练提速。

## 本地验收与源代码同步

在有 numpy、torch 的现有 Python 环境运行（本机 `/opt/anaconda3/bin/python`）：

```bash
python -m training.strategic_slices.train_terminal --check-only
python -m unittest training.strategic_slices.test_terminal_training training.strategic_slices.test_terminal_schedule training.strategic_slices.test_terminal_final_test training.strategic_slices.test_terminal_checkpoints training.strategic_slices.test_terminal_analysis training.strategic_slices.test_terminal_d training.social_mixed.test_native_limits training.social_mixed.test_probability_diagnostic training.social_mixed.test_efficiency.EfficiencyTests.test_padding_preserves_weighted_gradient_for_all_profiles training.social_mixed.test_native_stream training.strategic_slices.test_terminal_refill training.strategic_slices.test_cpu_reuse training.strategic_slices.test_evaluation_refill
python -m training.strategic_slices.train_terminal --mock --mock-updates 2 --output /tmp/terminal-node-mock
```

`--mock`使用同步adapter，只验证协议/数据/恢复；长短交错补位由上述stream测试验证。
mock 使用真实冻结题/Oracle和合成模型回答、tokens/logprobs，验证下一批精确恢复。
它不是实际模型信号、真实 tokenizer、GPU optimizer 或收敛证据。reference树恢复
有CPU成本，mock也可能需数分钟。`--check-only`只核验数据和配置，不检查本地权重/GPU。
已有 selected-v4 数据包仍可使用；**只复制其中 `new/local_data/` 数据到当前 repo**，
不要用包里的旧 source 覆盖 v8。新 source overlay 可由
`python -m examples.strategic_slices.prepare_terminal_training_bundle --output /tmp/terminal-node-v8.tar.gz`
生成，用于已有完整 MARSHAL checkout/环境；不含数据、权重或依赖。

## 正式任务启动（无独立GPU smoke）

沿用SoC已有conda/CUDA/ROLL环境和本地权重。默认2×H100-47；如果实际分配单
H100-96，同时设置`SOCIAL_GPU_PROFILE=h100-96-single`并覆盖Slurm gres。
脚本不安装/下载，不自动选择硬件。当前没有提交任何任务。

正式6M从base新开，清除此前smoke/resume限制，只需一个正式任务：

```bash
unset TERMINAL_QUESTIONS_PER_UPDATE TERMINAL_NODE_GROUPS_PER_UPDATE TERMINAL_TOTAL_TOKENS TERMINAL_MAX_STEPS
unset TERMINAL_EVAL_EVERY TERMINAL_SAVE_EVERY TERMINAL_VALIDATION_LIMIT TERMINAL_PAUSE_AFTER_UPDATES TERMINAL_RESUME
sbatch examples/strategic_slices/sbatch_terminal_train.sh
```

独立GPU smoke不是前置步骤。正式任务自带初始validation、第一步norm参数变化
记录、behavior/actor概率对照、有限loss/梯度相关诊断、阶段耗时、显存记录和
原生checkpoint。出现基础设施/Oracle/非有限数值错误会中止；有限概率偏差
仍沿用warning机制，不自动停止。需查看`metrics.jsonl`、`phases.jsonl`和
`probability_warnings.jsonl`；日志存在不代表所有GPU性质已在CPU上验证。
保留正常500K验证/1M恢复保存，不为前几步额外提高验证或checkpoint频率。
CPU精确恢复不等于GPU逐位浮点复现；16K最长序列显存、实际速度和GPU恢复仍未知。

普通恢复从最近完整checkpoint开始，保持代码、数据、profile、预算、采样及缓存
配置一致，使用新output目录并设置`TERMINAL_RESUME`；v7/v6或修改前source不能混续。

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
查看过的盲测。这些限制影响论文的泛化/效率结论；本轮仅完成CPU验收。
