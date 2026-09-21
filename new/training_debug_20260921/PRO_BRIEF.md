  # 新旧 B/P 训练排查：供 PRO 审阅

日期：2026-09-21。当前阶段只整理证据与排查问题，不修改训练配方。
本地 HEAD：20d0156bdfe35b0dae50c9bb6f993d9252cc7ffa。
训练配置、metrics和抽样calls已由 training_chain_evidence_20260921 核查；CalBench/diagnostic数值仍来自Sol摘要，本包不包含其完整原始运行。下文新增实现对照优先于此前待核查描述。

## 1. 必须分清的三个版本

| 名称 | 数据/用途 | 当前证据状态 |
|---|---|---|
| 远端“旧 B/P” | 摘要称使用 data_reasoning_v5_candidate | run、代码和数据哈希待确认 |
| 远端“新 B/P” | 摘要称使用 data_reasoning_v6，增加 B bridge 和有效组补采样 | 已跑 BP99/BP139；不是本地最新 O/B/P+ 配对实验 |
| 本地尚未训练的配对库 | paired_bank_v1；258 train +239 validation canonical cases；O/B/Pplus 三视图 | CPU 检查；不能用已有新 BP 结果评价这份库 |

本地核查结果：v5 train 594题=294 B+300 P；v6 train 742题=442 B+300 P。
**v5 的594道题在v6中逐条完全相同（不只是input/teacher相同）；没有删除，新增148道B scaffold。**
P分布均为P1=88、P2=90、P3=24、P4=98。原B分布B1=113、B2=52、B3=129；v6为157、156、129。
因此“v6删掉/修改了原P策略题”不符合本地数据；是否改变了实际P曝光、有效梯度、prompt或参数更新，需要远端证据。

训练文件 SHA256：
- v5 bp_train.jsonl: 3049247f91c5826ac7972fd5ce0e6d250574d46ca8088361899a015813981d66
- v6 bp_train.jsonl: a63b71bdc9bd6483ec1b66cd789ca0dea54cc42489a26905f88b304f8222d7c8
- paired tasks.jsonl: 000ff312e0bed7434cc9db60c307266ba594e947396011f6429323804c9056df

配对库是另一个训练设计：O不给oracle belief；P+提供同信息条件下的完整joint posterior；B保留可配对来源查询。O/P+共用复算行动标签，D采用O:B:P+=1:1:1。没有B bridge；不能与v6 bp臂混称“新版B/P”。已修复的19条状态重复标记及20条调查历史属于配对转换产物，原v6文件未被改写，不能假设远端受益于这些修复。

## 2. 远端报告的核心观察（待逐文件核实）

冻结24局CalBench，temperature=0；摘要称base复跑24/24一致：

| 模型 | response tokens | 协调成功 | 最优成功 | headline |
|---|---:|---:|---:|---:|
| Base | 0 | 5/24 | 3/24 | .488 |
| P-only65 | ~1.7M | 5/24 | 3/24 | .522 |
| 旧BP99 | 2.52M | 10/24 | 8/24 | .593 |
| 新BP99 | 4.43M | 5/24 | 5/24 | .479 |
| 新BP139 | 6.09M | 6/24 | 5/24 | .518 |
| 新SP39 | 6.34M | 4/24 | 2/24 | .447 |

同协议diagnostic_v5摘要：

| 指标 | 旧BP99 | 新BP99 | 新BP139 |
|---|---:|---:|---:|
| B exact | .063 | .156 | .156 |
| correct-B P regret | .839 | .916 | 1.144 |
| model-B P regret | .786 | 1.013 | 1.138 |
| end-to-end regret | .556 | .891 | .945 |
| B repair gain | -.075 | +.041 | -.037 |

观察支持“该批测试上显式B与行动表现没有同步改善”。但不能证明v6数据是原因：数据、采样、更新数、token剂量、loss和运行代码可能同时变化。也不能从5/24到6/24或单次行为翻转确定能力变化的机制。
旧12题CalBench、当前24局stream必须分开，不能拼成同一学习曲线。内部current-team SP utility与固定伙伴单体收益也不是同一指标。

### 2.1 diagnostic regret／repair 的即时一致性核查

若 `model-B P regret` 与 `correct-B P regret` 使用相同正确posterior、相同参考值、相同有效记录和相同权重，则逐记录以及同权聚合都必须满足：

`B_repair_gain = model-B P regret - correct-B P regret`。

Sol摘要中的三组数不满足该恒等式，且无法由三位小数舍入解释：旧BP99的regret差为-.053而repair报-.075；新BP99为+.097而repair报+.041；新BP139为-.006而repair报-.037。**当前不能将其写成实现bug**，因为本包仍不包含这三个checkpoint的diagnostic原始`results.json`、`summary.json`与`protocol.json`，无法区分条件特定失效、不同macro权重、不同评分belief或摘要串运行。

已对本地可用的最终q0-v5运行 `runs/diagnostic/q0-v5-t0-no-cache-serial-868698/structure_v5` 做同样核查：

- 96行中93行双条件有效；逐行恒等式失败0，最大绝对残差 `2.22e-16`；
- structure-macro：model-B regret 1.215625，correct-B regret 1.2572917，差为-.0416667，与repair -.0416667一致；
- 三项在配对记录上的权重完全相同。

这说明当前本地评分定义在共同样本上满足代数恒等式，但不能替代三个训练checkpoint的原始记录。v5聚合器会对每个指标分别丢弃无效行再做structure macro；若两个P条件的有效集合不同，两个headline regret均值就不能直接相减，repair必须在共同有效配对上单独报告。复算脚本为 `audit_diagnostic_consistency.py`，逐记录表为 `diagnostic_record_audit.csv`，报告为 `diagnostic_consistency_audit.json`。

本地较早的三个v5运行直接复现了这种“逐行恒等式成立、headline均值不成立”的情形：逐行失败均为0，但独立structure-macro的恒等式残差分别为-.0112、+.0234和+.0314；原因正是两个条件及repair的有效行／权重不同。这使“条件特定缺失或macro权重”成为远端三组差异的具体高优先级解释，但在拿到其原始记录前仍不能断言就是该原因。

同一离线审计还检查了“正确semantic B”是否足以唯一确定行动排序。对每个case，在符合其`possible_preferences/favored`及0.1 favored margin的0.01概率网格上搜索：32个case中17个允许多个行动价值排序，14个允许不同最优动作集合（13个preset、1个voluntary）。这是构造性反例：至少这些case中，正确semantic摘要并非决策充分的完整belief。故：

- `correct-B`只能称“correct semantic summary”，不能称完整修复B或oracle posterior；
- 其regret混合了planner行为与semantic接口丢失的概率信息，不能单独解释成纯P缺陷；
- `B exact`只检查possible set与favored两个字段。若所有B输出有效且replica确定，摘要中的.063与.156分别很可能对应2/32与5/32，但其确切分母仍须由原始记录确认；它们不是posterior accuracy。

上述结论适用于旧v5 case inventory。论文版v6现已替换结构，而不是复用这14个歧义case：对native semantic judgment的完整连续posterior区域做有理数凸多面体顶点枚举，并保守纳入零质量与0.1阈值边界；仅保留所有顶点具有相同精确最优动作集合的case。冻结集仍为16个matched structures（8 binary、8 linear，32 cases），32/32均通过，且每对voluntary/preset的不变最优集合不相交。旧v5的B/P数值和failure trace不得迁移；新v6的`correct-B P regret`可解释为**给定决策充分的原生semantic接口后的规划regret**，但仍不是posterior预测准确率。

### 2.2 强化版v6最终结果（本地原始记录复核）

最终run已同步到：

- `runs/diagnostic/old-bp99-v6s-biinv-v1-870332/structure_v6`
- `runs/diagnostic/new-bp99-v6s-biinv-v1-870333/structure_v6`

两者均为96/96 rows、408/408 calls、三次重复逐字段一致；manifest/runtime hash相同，temperature=0，batch-invariant，32/32 decision-sufficiency certificates通过。paired-scoring逐行失败均为0，最大逐行残差0。

主要复核结果：

| 指标 | 旧BP-99 | 新BP-99 |
|---|---:|---:|
| semantic B exact | 15.63% | 15.63% |
| voluntary B exact | 0/16 | 0/16 |
| possible-set exact | 43.75% | 50.00% |
| correct-B P有效case | 25/32 | 29/32 |
| correct-B P regret | .828 | 1.135 |
| model-B P有效case | 20/32 | 27/32 |
| model-B P regret | .568 | .845 |
| end-to-end P有效case | 28/32 | 32/32 |
| end-to-end regret | .690 | .854 |
| paired case（structure） | 16（11） | 24（14） |
| action changed under repair | 7/16 | 16/24 |
| repair负／零／正 | 3/13/0 | 6/18/0 |
| paired repair mean | -.144 | -.310 |

aggregate B exact的5个正确项全部来自preset；两个模型在16个真正需要利用voluntary行为证据的case上均为0/16。新模型possible-set的2题净增也只来自preset（preset 16/16 vs旧14/16）；voluntary possible-set仍均为0/16。因此不能把headline的set改善写成行为推断改善。

为避免跨模型有效子集不同，另在共同有效记录上比较：14个paired cases／10 structures的repair为旧-.158、新-.550；24个correct-B cases／全部16 structures的regret为旧.802、新1.130；28个end-to-end cases／14 structures为旧.690、新.887。故新模型的格式覆盖更好，但共同题上的决策质量仍更差。

负repair不是“忽略B”：动作分别在7/16与16/24 paired cases中改变，说明P会响应semantic B。更准确的结论是响应方向失配和错误抵消。没有任何case因repair提高效用；旧3题、新6题下降，其余效用不变。典型`binary-20796:preset`中，新模型的错误favored=want恰好诱发认证最优offer；换成正确undetermined后，模型明知是最后一步仍选择INVESTIGATE，使regret从0升至2。该模式具有重复性：correct-B条件下旧模型7次、新模型14次INVESTIGATE全部为正regret。

## 3. 实际训练实现与参数（证据包核查后更新）

### 3.1 运行链与可恢复范围

- 旧BP：860494（commit 1a691483…，0–102），从checkpoint99续训到861241（c4c74ac1…）。100–102有分叉，主续训应取861241，不能重复相加。861241有105条含generated_tokens的更新记录（100–204）；calls另存step205，不把有calls当作已完成optimizer更新。
- 新BP：865319的0–29已删除；866677从checkpoint29恢复，保留30–99；868798从checkpoint99恢复，保留100–149。两段commit dbd4585…，recipe=social-stable-v2-b-bridges。
- 新SP：865319的0–9已删除；866677保留10–41，同一dbd4585…。
- 存活run manifest均记clean=true，恢复的是native checkpoint路径，不是仅加载HF actor的新训练阶段。不能用其他run的step0补成新run基线。
- 本地可读取dbd4585完整git对象；两个旧commit对象当前不可读，包内只有各自单commit patch，不等于完整旧训练源码。因此旧配方仅将config/calls能证实的部分作为确定事实。

### 3.2 共同参数：不要把框架占位batch参数误当真实采样量

| 项目 | 实际记录 |
|---|---|
| 模型 / seed | Qwen3-4B-Instruct-2507 / 42 |
| 更新 | PPO clipped surrogate，clip=.2，每批1 PPO epoch、1次optimizer更新 |
| Optimizer | Megatron backend；Adam beta=(.9,.95)，weight decay=0 |
| Warmup | steps=0，ratio=0 |
| KL | loss coefficient=.01；reference配置为原始pretrain；不是reward KL（init_kl_coef=0） |
| 生成 | temperature=1，top_p=1，top_k=-1，repetition_penalty=1；max_new_tokens=1024 |
| 上下文 | sequence_length=4096，prompt_length=3072 |
| 精度/并行 | BF16，train TP=2，sequence parallel，全量recompute，microbatch=1 |
| 硬件 | 每臂两个H100-47 MIG分区、cross-parent；不能写成两张完整H100 |
| 推理 | vLLM，infer TP=1配置，max_num_seqs=16，memory=.5，prefix cache关闭 |
| 预算 | total response tokens=6,553,600；tokens_per_update=65,536是目标/配置，不是每步硬等量 |
| 保存/验证 |配置save_steps=eval_steps=10；实际记录以各segment文件为准 |

框架resolved config虽然写rollout_batch_size=1、num_return_sequences_in_group=1，B/P由自定义collector逐题生成8个replica；所有抽样B/P calls组大小均为8。worker把完整采样批累积后才step，microbatch=1不等于每响应更新一次。

### 3.3 数据语义：不是监督答案文本的SFT

B/P是可验证奖励的在线RL：模型自行生成解释及工具调用，然后评分，不是用teacher答案做token交叉熵。
B要求possible_preferences与favored的语义判断；P要求原生行动，命中teacher可接受集合得1，否则0。P不是全都给belief：既有supplied-belief题，也有history→action/P4调查结果利用等题，不能把P-only概括为只练已知belief。

数据来自人工构造的可求解小局：显式公开状态、目标—承诺依赖、自己的偏好、伙伴可见行为及私有调查结果；binary/linear，无mixed目标规则。Teacher后端枚举偏好世界、按声明的selected policy更新belief并计算行动价值；回答时可见信息取决于题型。B1/B2/B3覆盖形成/行为推断/更新保持；P1–P4覆盖行动规划、belief条件及调查时序等。目录行数不代表独立结构数。

v6新增148条=74 parent各两种bridge：likelihood提供推断中间信息，procedure提供步骤提示，raw是原题；**不是新增148个独立局面**。原题和P标签没有变化，但渲染与采样配方会影响实际训练分布。

### 3.4 新旧B/P的关键算法差别

旧BP calls验证：每题8次，组内标准化advantage。例如4对4错时约+/-0.999998，对应(R-mean)/(std+1e-6)。无效/截断task advantage置0，另给-.2协议advantage；有loss_weight，未记录新配方的task_denominator/task_weight分项。resolved loss为seq-mean-token-mean。完整旧采样器和worker源码仍需补充才能彻底核查归一化及调度。

新BP（dbd4585源码+calls）：
1. 目标B、P各4个reward非恒定组，最多32候选组，每组8回答；原题每步不重复。
2. B在likelihood/procedure/raw阶段轮换；coverage与active交替。active选择最近32step访问且mixed EMA>=.05的题；EMA=.8旧+.2当前。cell按kernel/completion_mode/information_role分层选择，再选题。不是单纯文件行均匀抽样，也不是完全没有回访。
3. 有效组定义max(reward)>min(reward)，可能含格式失败造成的差异；合法响应内部的语义有效组另计。
4. 有效组中合法响应A=R-mean，无std归一化；无效/截断A_task=0，A_protocol=-.2。无效记录仍进入均值计算，不能把均值写成仅合法样本均值。
5. 设总行数N，域d有效组数E_d、候选数C_d：有效组task_weight=N*0.5/(8E_d)，其他task_weight=0；protocol/KL weight=N*0.5/(8C_d)。保留候选组上的KL/协议信号。
6. task的token loss求和除固定1024；protocol与KL除该响应实际长度，然后按权重和全batch行均值聚合。

新loss精确定义：rho=exp(logpi-logpi_old)，S(A)=-min(rho*A,clip(rho,.8,1.2)*A)。
L_task=mean_i[w_task,i * sum_t mask_it*S(A_task,i)/1024]。
L_protocol=mean_i[w_protocol,i * sum_t mask_it*S(A_protocol,i)/length_i]。
L_KL=.01*mean_i[w_KL,i * sum_t mask_it*(exp(delta_it)-delta_it-1)/length_i]，delta=logpi_ref-logpi。

**因此新旧不仅数据不同，还改变了advantage尺度、长度归一化、有效组选择/权重和LR。** 相同名义KL系数不意味着相同task/KL相对强度；不能直接归因于B bridge。

### 3.5 LR已核实：新训练确实cosine，不是constant

后端config仍写constant_with_warmup，但dbd4585 worker在train_step前逐optimizer param_group设置social_lr。pipeline按已消费token计算：
LR=1e-7+0.5*9e-7*(1+cos(pi*min(consumed/6553600,1)))。
metrics中的actor/applied_lr与这一路径对应：
- 新BP30:9.1482e-7；99:3.2107e-7；100:3.1346e-7；149:1.00484e-7。
- 新SP10:8.8524e-7；41:1.00133e-7。
旧BP没有applied_lr字段，config为constant 1e-6；尚缺完整旧worker源码。
**不能再把“新训练没做LR decay”列为问题；cosine已经存在但没有阻止所报告的退化。**

### 3.6 已从完整存活metrics算出的信号量

| segment | updates | 平均response tokens/update | B有效组 | P有效组 |
|---|---:|---:|---:|---:|
| 旧860494 0–102 |103|25,196|1.816|3.427|
| 旧861241 100–204 |105|28,819|1.448|3.981|
| 新866677 30–99 |70|44,667|4|4|
| 新868798 100–149 |50|41,424|4|4|

新两段平均候选组12.53/12.78，所有存活更新都达到4+4。但raw B有效组只有平均1.357/1.14，其余来自bridge（likelihood:1.286/1.64，procedure:1.357/1.22）。所以“有效B变成4组”不意味着“无辅助B变成4组”。以上旧段含重叠分叉，表是segment统计，不可直接相加为主链。

抽样15步calls：旧P1/P2/P3/P4组数17/8/12/43；新7/17/11/35。窗口时点和token剂量不匹配，只能证明该样本中分布不同，不能代替全程曝光统计。

### 3.7 新SP具体实现

同模型全局自博弈，各玩家只以自身终局utility为outcome，不优化总社会福利。新stable collector用自身terminal utility减历史bucket baseline：bucket按人数、binary/linear、round_robin长度；至少16次观测使用bucket均值，否则global；完整player episode更新EMA（.9旧+.1当前批均值）。合法行动共享该玩家advantage；失败调用只有-.2协议项，未完成局无terminal task advantage，不伪造正常零收益。玩家轨迹等权，轨迹内调用平均、调用内token平均；KL另项。配置的grpo标签不能替代这一实际历史baseline公式。

new SP每update平均160,552 response tokens；与BP step数量不可比。SP终局广播可能导致高方差，但不是算法不合法的证据；仅终局reward、gamma=1时改称turn-level return不会自动分配不同信用。

### 3.8 Validation与外部测试不能混用

新源码：B/P temperature=0、每题1响应；优先periodic_validation标记；45个B/P题。SP temperature=1，从validation池分层选8个reset，每个1局、所有玩家用当前模型。不是摘要所写的2 reset×2 replica。应以每次snapshot protocol最终确认为准。内部utility不是固定Q0对手指标。
CalBench的冻结推理设置也不是训练设置，不能把其temperature=0或batch-invariant直接写进训练参数。

## 4. 需要PRO分析的问题，按优先级

1. **运行身份和优化链路**：确认新旧run的模型起点、resume方式、代码、数据哈希、reference、loss归一化、LR与KL实际生效。先排工程错误，再谈训练方法。
2. **在原P题完全保留的条件下，什么发生了变化？** 对齐累计token和更新数，比较逐task/kernel/stage曝光、全对/全错/有效组、合法语义有效组、task/protocol/KL权重。是否补采样选择偏向易产生奖励差异的题，而降低其他能力覆盖？
3. **B bridge是否迁移到raw B？** 将三种stage分开；检查raw B原题与未见题，而非只看混合B分数。检验B改进与P变化是否时间相关，但不能用相关性证明梯度干扰。
4. **规划下降还是评测接口/失效分母变化？** 旧diagnostic_v5既保留history，又有14/32个semantic摘要决策不充分，不能作最终规划隔离。新v6已同时移除两项混淆并冻结32/32决策充分case；须在新inventory上重跑，不能搬用旧数值。仍需检查所有条件合法率、截断、缺失及有效样本数量；headline regret若使用不同有效集合不得相减。负repair gain本身不证明belief无用或内部B→P链断裂。
5. **训练后期是否发生可复现的退化？** 固定case、seed、prompt、checkpoint来源后比逐题变化。不能将小validation的波动直接确诊为灾难性遗忘，更不能据此直接认定KL太弱或LR是原因。
6. SP暂列次优先：终局reward广播是合法的Monte Carlo策略梯度做法，信用分配粗可能增加方差，但不是算法错误的充分证据。仅终局reward且gamma=1时，turn-level return仍相同；要解释不同信用必须说明中间reward或baseline。按动作统计advantage mass也受动作频率/长度/权重影响，不能单凭正PASS mass认定PASS被错误奖励。

## 5. 已有证据与仍缺的最小补充

已收到：存活segment的manifest/config/environment、全部metrics、validation、三个训练call窗口、数据hash、单commit patch。新初始865319已删除（BP0–29、SP0–9），不再要求下载不存在的文件。

仍建议补：两个旧commit的完整源码归档（git archive，尤其core/curriculum_sampling/workers/pipeline及所调用optimizer/loss代码）；单commit patch不足以重建祖先。外部CalBench/diagnostic原始结果另取，当前数字仍标记Sol摘要。若需全程曝光分析，补每组轻量task/stage/reward/weight索引；不需要模型权重，也不需重跑训练。

可复算脚本：summarize_evidence.py；输出evidence_summary.json。当前只统计证据，不改训练参数。

## 6. 当前不应直接下的结论

- 不能把本地未训练的paired-bank修改归因到远端“新BP”结果。
- 不能认定新P题更差：本地原P题没有改变。
- 不能仅凭config声明constant LR、KL太弱、没有任何回访或SP信用算法错误。
- 不能把某个checkpoint的测试优势当成已证明的训练配方优势，也不据CalBench继续选择正式主模型。
- 不能概括为“后期所有能力都在退化”：新BP99→BP139时diagnostic若干regret上升且B exact不变，但CalBench headline .479→.518、协调成功5/24→6/24，方向并不一致。当前最多写“部分诊断出现退化信号”。
- 本轮先核查事实，不立即追加reward、改温度、扩大validation或加入新保持约束。
