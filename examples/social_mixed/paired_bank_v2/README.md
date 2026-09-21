# Social reasoning 四臂：PRO 训练前评审说明

目标是学习并保持“可见社会证据 → 伙伴判断 → 条件行动 → 反馈更新”的行为依赖。CalBench与diagnose用于发现问题和审查机制，没有将它们的案例或模型输出加入训练题，也不以某个benchmark分数或预设的四臂排名选方案。

**下一次目标已收敛为 SP 与 O 两个独立pipeline，分别启动、各自从同一 Q0 开始。** 不是把 SP/O 混入同一次更新；C/D 暂缓。不要求并行提交，不额外加载固定 Q0 伙伴模型。下面保留四臂设计供后续审查；本轮不直接启动四臂。

## 2026-09-22 撤回未经确认的默认配方

默认归一化恢复为 `standard_sequence`：合法且可评分的组内奖励减均值、除标准差加1e-6，任务损失按实际回答长度平均。`centered_fixed`仅保留为显式选择的历史实验选项，不再默认启用。SP恢复同reset四条轨迹、固定8组并发（每组4条，共32条轨迹）；固定曝光、连续采样游标、完整游戏预算结转保留。这不是恢复全部旧数据/采样器，而是撤回这两项优化公式和SP并发改动。

概率偏差改为报警：有限的平均绝对log-prob差>0.05或clip比例>0.01时，写入 `probability_warnings.jsonl`、标准输出和训练metrics，继续更新；非有限差值/ratio仍硬停止。原始行为概率仍作为PPO分母。按用户随后要求，完整评测与checkpoint恢复按更新次数的节奏：默认每10次更新评测并保存，预算结束或步数上限结束也评测保存，不再限于四个预算点。所有这些已评估checkpoint保留并参与同一开发指标选择；静态监测不额外保存模型。已接入Q0及第4/8次更新完整交互监测；第4/8次仅监测，不额外保存或参与最佳checkpoint选择（若同时为正常结束点则按正式评估处理）；四个正式候选点不应被解释成只能评测四次。完整评测是静态O/B/P面板加选定原生游戏从头到终局或协议失败的多轮交互，不是整个验证集或CalBench。交互仍是current-team，验证temperature已改为0；训练temperature保持1。

## 本轮 SP/O 准备与验收

- **SP 改进**：保留完整终局奖励、同reset四条轨迹、按固定8组并发（每组4条，共32条轨迹）采样、上一批历史 baseline 和独立协议处罚；将原来每个更新重新洗牌的 reset 采样改为跨更新连续推进，游标与 baseline 一起保存和恢复。保留既有短/中/长局 2:1:1 配额，不按成功与否重采样。108 个训练 reset 在一个192组周期内全部覆盖，每个出现1–3次；这不代表一个固定token预算必然走完整个周期。新增每块唯一 reset 数和累计采样游标。
- **O 对照**：使用373个训练局面的无辅助历史→行动请求，覆盖134个parent；不加入 B/P 训练。保留现有六个配对槽位和独立 O 覆盖流，以便以后衔接 C/D。两臂生成token预算相同，不意味着游戏数、有效梯度剂量或更新次数完全相等，必须结合实际日志解释。
- **漂移监测**：同一25题 O 开发面板，在Q0、第2/4/6/8次更新、此后每5次更新运行；第4/8次完整监测及每10次正式评估复用 O 结果。记录正确率、parent macro、合法率、regret、上一点正确→错误、历史曾正确→错误，并把新遗忘拆成格式失败和合法但错误。报告放在 `static_o_monitor/`，使用当前actor，不加载伙伴模型、不进入候选checkpoint列表，也不因监测额外保存权重。监测失败会报错停止；**能力下降尚不触发自动停止/回滚**。
- **优化边界**：保留完整6553600生成token的cosine LR horizon，前8次更新作为同一训练的观察阶段，不把总预算缩到8块。保留每次更新前的actor/behavior概率偏差报警与非有限值门禁；暂不额外做四臂校准、固定伙伴评测或完整GPU梯度等价性专项。
- **本地校验**：新增 `sp_o_preflight`，检查全周期覆盖、恢复后的采样一致性、108个初始SP请求渲染及O来源构成，结果见 [sp_o_preflight.json](sp_o_preflight.json)。数据/标签校验通过，39项相关CPU回归测试通过；Python编译、启动脚本语法和diff空白检查通过。它不运行模型，也不认证P隐藏世界集合的完备性；该问题在恢复C/D前仍需处理。
- **训练机上仍必须完成**：真实tokenizer检查（启动入口会检查O/B/P及SP初始输入；SP后续每次请求由运行时长度门禁检查）、Q0 O可训练性探测，以及首次真实更新的现有概率偏差监测/非有限值门禁。Q0完整互动评估由训练启动时执行，可观察SP终局、非法动作与截断情况。没有这些结果，目前保持 `formal_training_ready=false`，尚未提交作业。

准备 O-only Q0 请求（32题×8次，不调用模型）：

```bash
python -m training.social_mixed.reasoning_probe --views O --prepare-only --output /tmp/sp-o-q0-requests
SOCIAL_DATA_DIR=examples/social_mixed/data_reasoning_v6 python -m training.social_mixed.sp_o_preflight --output /tmp/sp-o-preflight.json
```

执行真实Q0探测时，在新输出目录去掉 `--prepare-only`，提供 `--base-url`、`--model`、`--checkpoint-hash`。检查合法率、全对/全错组和语义对比组；没有采样到奖励差异时，先排查是否具备可学信号，不能仅凭静态标签有正负动作就启动长跑。

验收后供训练机分别使用的独立入口（**此处未执行**）：

```bash
bash examples/social_mixed/start_training.sh h100-96 outcome
# 独立启动SP，不要求与O同时提交
bash examples/social_mixed/start_training.sh h100-96 selfplay
```

`sp_o` 明确展开为 `selfplay outcome`；旧 `both` 仍是 `bp selfplay`，不要混用。新采样配方版本为 `social-reasoning-tristate-exposure-v5`，不静默恢复旧v2/v3优化器状态。

## 过去失败的现象与原因：简述

| 现象／已核实事实 | 当前解释与证据边界 |
| --- | --- |
| frozen CalBench的旧BP99优于新BP99：完整成功10/24→5/24，会议完成44/72→36/72；新版不是所有场景都差，差距主要出现在约束较强及后续协调。 | 轨迹出现共同确认分叉、误记伙伴约束、执行与目标相反的状态变换。说明完整交互的推断、规划、执行连接有问题；不是“显式B准确率下降”这一种解释。评测是同模型四人团队，不是固定Q0伙伴。 |
| strengthened decision-sufficient v6中，两模型B exact同为5/32；voluntary exact同为0/16。共同24例的correct-B regret旧.802、新1.130。 | 即使提供正确且经该诊断认证充分的B，新模型仍不会更好地行动。修正B不能稳定转成收益；但不能由此证明B训练本身有害，或所有社会推断能力都无用。 |
| v6保留原594条B/P并新增148条B scaffold；它们来自74个parent，不是148个独立结构。 | “新版P题本身变坏”不是首要解释。数据接口、实际曝光与优化配方同时改变，无法直接把退化归因于bridge。 |
| 新旧改变了组内advantage归一化、长度分母、有效组采样／权重、每次更新tokens与LR。新训练已经有cosine decay。 | 相同token预算或名义KL系数不等于相同P更新次数、任务梯度强度或task/KL比例。新版达成的4个有效B组也混入bridge，不等于4个无辅助B组。曝光稀释、辅助与O/P梯度干扰、任务梯度过弱／过强均是待检验假设。不能再写成“因为没做LR decay”。 |
| 已观察到能力波动及部分后期诊断退化；用户关注遗忘与漂移。 | 尚未确诊普遍灾难性遗忘。部分diagnostic与CalBench后期变化方向不同；单次交互里的状态遗忘也不等于训练参数层面的遗忘。需要同题同协议跨checkpoint复测及优化统计。 |

证据入口：[既有训练核查简报](../../../new/training_debug_20260921/PRO_BRIEF.md)、[CalBench与diagnose机制核查](../../../new/calbench_bp99_mechanism_audit_20260921/README.md)、[原始结果统一索引](../../../new/bp99_checkpoint_results_20260921/README.md)。简报包含历史排查过程，应以其后补充的原始记录核查及strengthened v6为准。

我们本轮实现中也纠正了两项设计错误：一度让P保留O历史，模型可绕开supplied belief；随后一度提供数值联合posterior，与B的简单输出接口不一致。这两种接口均已撤回。当前P无历史、无概率数字，采用与B相同的定性结构；不继续通过复杂化B标签来掩盖P的信息不足。

## PRO需要判断的核心问题

1. 固定teacher世界集合与后续价值表的LP认证，是否足以支持当前P辅助训练范围？是否应先只用直接终局题做更严格的小规模验证？
2. 保留全部有效O/B、按资格限制P，并采用正／负／屏蔽监督，是否比统一删题更适合本研究？如何避免masked比例造成新的有效梯度剂量差异？
3. 当前D相对C是**用B替代部分O监督**，而非在相同O剂量上净增加B。四臂能回答训练配方比较，但不能单独识别B的因果收益；是否需要一个最小的剂量匹配补充对照？
4. 两个验证B→行动对照仅涉及三个局面，覆盖有限；主选择指标又是current-team交互。是否需要扩大固定局面／伙伴评测，才能支撑机制结论？
5. 遗忘／漂移的短程诊断应先检验哪些变量？是否接受当前归一化与评测频率？本轮尚未形成经验证的防遗忘训练方案，见后文专节。

## 当前已启用的方案

已接入三态P评分、独立语义屏蔽和角色采样，详见`training_plan.json`。保留全部497个原生局面的O/B（373 train / 124 validation），所以175个原父题包与原来源组合完整保留。P只使用审核过的角色：

| P用途 | train | validation | 合计 |
| --- | ---: | ---: | ---: |
| 有明确正负动作，可进入训练采样 | 314 | 106 | 420 |
| 无明确负动作，只做评测 | 29 | 4 | 33 |
| 未通过原正标签稳健性检查，隔离 | 30 | 14 | 44 |

453题仍是可评分P池；420是含验证题的训练资格总数，实际P训练池只有314题。44个隔离P的请求记录仅供溯源，不进入采样或开发评测。原O/B有效，故保留它们解决来源缺失与残缺父题包；这不等于恢复44个不合格P。P3/linear只保留有效O/B，不声称已有合格的同源P监督。

P正/负动作参与语义奖励；masked动作不进入组内任务均值、标准差，也没有任务advantage，仍独立接受协议与KL处理。masked在验证中记作未判分，报告覆盖率，不当作错误或遗忘。O与B继续原评分。

已将验证对照中的B查询改到实际改变、并导致稳健动作集合不相交的偏好上；使用原query_candidates认证答案，不增加B字段或概率数字。共同开发面板强制包含这2个对照（3个局面），分别检查B和行动。对照规模仍小，不等于充分覆盖所有social reasoning能力。

历史审计文档保留筛选前结论；当前实现以本节和`training_plan.json`为准。CPU检查与训练机制测试通过不代表模型已经学会；本机缺少Hydra、Transformers/tokenizers及GPU训练环境，正式训练仍待环境验收。

## 数据与标签

沿用 v1 的已认证局面来源，重新逐例执行 native replay，复算完整固定后续策略下的 per-world 行动价值，并检查与原 teacher 一致。按来源家族重新划分为373个train、124个validation canonical cases（约75%/25%），共1491个视图；这是已有局面的重新组织，不是新增497个独立结构。本次输入/划分修订复用已回放认证的标签，逐例核对源teacher并重新检查全部P行动接口；缓存标签来源hash记入manifest。

- `tasks.jsonl`：O、原生无辅助B、Pplus三个视图及角色标记；是否实际训练由角色策略决定。
- `cases.jsonl`：各动作价值、own regret、精确自身最优动作集合、原acceptable集合、一步动作后的承诺/时间/终局状态、全部候选B查询及条件价值分支。
- `packages.json`：175个parent packages，父题与source family均不跨train/validation。属于来源隔离，不声称完全消除了所有抽象结构重合。
- `relations.jsonl`：相同物理决策问题的匹配关系。train有53个最优集合不相交对、406个最优集合相同对、31个部分重合对；validation对应6、136、5。它们共享case且不独立，不是637个独立反事实实验。

关系另记录`fixed_continuation_payoffs_match`：只有世界对齐后完整payoff表一致的对才进入验证中的条件关系指标；不把prior改变了teacher continuation的对误称为只改变belief的介入。53个train和6个validation的must-change对均满足该条件。

B查询优先选择条件答案会改变最优动作集合的伙伴变量，其次选择不确定性更高的变量；没有这种变量时保留控制题。按当前选定query，train有90个、validation有24个满足这个旧条件指标；此外，匹配对选出的query可在单题内已经确定，却在同状态对照间发生变化。相关性来自固定后续策略下条件分布重加权，**不是执行揭示动作后的VOI，也不是内部因果依赖证明**。

B不再接收正确previous belief，也不接收likelihood/procedure scaffold。B当前均按完整可见历史形成判断；原来的source kernel保留作来源审计，不能把它称为保留了原先所有B3教学接口。

P（内部视图名暂保留`Pplus`）**不提供历史**。实际模型输入仅保留当前决策状态、规则、行动工具、自身偏好和正确定性belief（与B相同的possible_preferences/favored结构，不含概率数字）；移除历史事件、原始prior、私人调查结果及证据来源。当前承诺、待响应offer、剩余轮次和调查次数是行动所需的当前状态，不是历史推断任务。O/P保留同一原生teacher价值表和行动工具；**当前实际reward不再完全相同**：O使用完整信息的原二元评分，P使用审核后的三态监督。P通过独立的允许字段渲染器生成，不能从内嵌O输入重新拼接历史。任务文件中的原始source input仅为原生评分和标签回放保留，不等于发送给模型的请求；回归测试检查实际请求不受这些历史字段影响。

B从历史预测所查询变量的`possible_preferences`和`favored`；P直接接收每个伙伴偏好对应的同结构正确答案。例如：`possible_preferences=[want, neutral], favored=want`，表示want与neutral均可能，目前更支持want；没有明确倾向时使用`undetermined`，已确定的偏好则使用单元素集合。P不接收精确概率或联合分布。原始数值posterior仅保留在后台标签中用于认证和价值计算。

497个局面中，212个没有剩余不确定偏好，203个有1个、58个有2个、24个有3个。B与P的表示格式现在一致；B每题仍查询一个偏好，P按需使用多条同格式判断。全库重复输入检查未发现相同定性P请求对应不同reward标签。逐题LP审计已覆盖全部497个局面，见[逐题报告](QUALITATIVE_CASE_AUDIT.md)：按当前文字的保守范围，394题评分集合稳健、103题有评分变化反例（80 train / 23 validation），其中27题存在与原标签不相交的动作集合。即使按B标签器内部规则，仍有86题评分变化，其中19题不相交；407题稳健，4题仍有严格边界未决问题。174个所有直接后继均为终局的题在两个范围下都稳健。

上述结论限定于现有teacher世界集合与固定后续策略价值表，并使用浮点LP；不保证替代posterior能由原历史产生或未来策略重新求解后仍相同。稳健不是无限范围的语义充分性证明。`qualitative_review_queue.json`列出103个待修订/复核题，逐题反例与动作边界保存在`qualitative_case_audit.jsonl`。这是未分角色时的历史审计；当前已按开头说明接入P屏蔽和隔离策略。正式训练仍需完成模型与GPU验收。

复现逐题审计与可读报告：

```bash
python -m training.social_mixed.audit_qualitative_cases
python -m training.social_mixed.write_qualitative_case_report
python -m unittest training.social_mixed.test_qualitative_case_audit
```

划分记录见`manifest.json`的`split_policy`：原train保留，原validation按完整source family迁入train，保留验证集原有source-kernel/completion-mode组合覆盖。选择使用数量、来源、teacher标注的行动相关性，并要求验证集保留must-change题对；不使用模型表现。所有同父题视图一起迁移；这是重新冻结的开发集，不是从未使用过的独立测试集。数据版本与hash已经更新，旧配方checkpoint不能静默续训。

O/B训练reward仍是原二元正确性；P使用后述三态监督。精确own最优集合与原acceptable集合分开保存，因为原reward含容差及response tie约定。新状态/价值标签先用于测量和后续独立监督比较；本轮没有把它们全部混成新reward，也没有监督未经认证的长推理文本。

## 394 + 59 候选池审计

已完成[453题候选池审计](CANDIDATE_453_AUDIT.md)。保留原split后为343 train / 110 validation；其中33个P题（29 train）没有明确负动作，正确屏蔽后不能产生当前GRPO的语义对比梯度。验证集没有保留下“仅被查询B变化且正确动作不相交”的匹配对。这是历史候选池的审计结论。当前已按本页开头的角色方案接入三态评分，并修复查询对照；没有直接删除全部44个局面的O/B。

## 四臂与实际曝光

| 名称 | CLI | 任务损失系数 |
|---|---|---|
| SP | selfplay | 自身终局收益减历史baseline |
| O | outcome | O=1 |
| C | conditioned | O=2/3，Pplus=1/3 |
| D | decomposed | O=B=Pplus=1/3 |

默认6553600 response tokens，100个65536-token名义块。每组8个首次回答：

1. 每块选三个共同case：两个B-action相关case和一个控制case，各自在固定覆盖序列中轮转。这是预先指定的初始配比，尚未证明最优。
2. 第一组槽位：O臂看O；C/D看相同case、相同seed槽位的Pplus。候选仅来自有明确正负动作的P训练池。
3. 第二组槽位：前两个沿用对应P的case，第三个从完整B覆盖序列轮转，保住无合格P来源的B曝光。O/C在同槽位看对应O，D看B。
4. D至少有一组与上述case关联的O；其余生成额度继续完整O覆盖序列。

C/D每块恰好各有3个Pplus候选组（24个回答），D有3个B候选组；相同辅助case与出现阶段不由模型reward改变。O的实际回答数和tokens可能不同，分别记录；损失系数不是token份额。

父题成员在完整覆盖序列中相邻；相关/控制子序列及块边界可能拆开一个较大parent，不能声称每个parent必在同一optimizer batch里完整出现。每块前两组B/Pplus同case配对是显式的；第三组B用于完整来源覆盖。

不再为补满mixed组追加B/Pplus。域内按全部候选组平均，全对/全错组任务梯度为0，保留协议与KL。任务advantage只在合法且可进行语义判分的回答间居中：正确+非法不再冒充语义对照；无效回答只有独立协议惩罚。协议/KL与任务的候选分母均显式保存。

完整组跨token边界的超额在下一块扣回。SP恢复一个reset四条轨迹，并发组数沿用8；历史baseline仍按完整player episode更新。SP可能因完成整局超过边界，其超额同样结转。SP保留原完整局数据源；没有声称其根局与paired库逐一同构。

## 优化实现与遗忘／漂移：尚未解决的部分

- 非默认实验选项 `--normalization centered_fixed`：仅在合法且语义可评分的回答中减均值，任务token和除1024。
- 当前默认 `--normalization standard_sequence`：同一可评分集合内减均值/标准差，任务按回答长度平均。
- 其余沿用已核查配置：token cosine 1e-6→1e-7、KL .01、clip .2、一批一次更新。未宣称这些超参数最优；两个normalization选项也是组合比较，不隔离两个归一化因素的单独因果效应。
- 保存每域候选组、语义有效组、回答tokens、正确/合法数、任务系数绝对量；系数量不是参数梯度。
- 更新前抽样比较actor/behavior同token概率，默认有限的平均绝对logprob差>.05或clip比例>.01仅报警并继续；非有限差值或ratio停止在optimizer前。这是可配置工程报警阈值，仍需GPU验证，不是理论稳定性保证。
- `gradient_acceptance.py`支持O/B/Pplus分项参数梯度与两两cosine。仍只是HF两个norm张量的诊断，不能称Megatron全参数梯度认证。
- recipe、normalization、bank hash、token horizon与概率阈值在resume时锁定；旧配方不能静默恢复进新配方。

### 已处理到什么程度

我们讨论并实现了**可观测性与部分风险控制**，没有解决“如何稳定保住能力”的研究问题。

- 固定辅助候选与记录真实曝光，减少模型reward驱动的采样偏移；它不保证O/B/P梯度彼此兼容。
- 分离合法性、语义正确性和masked，避免错误负监督；它不保证有足够的正负样本或有效梯度。
- actor/behavior更新前检查可记录并报警一类概率不一致，但每次只抽样至多8条，不是全batch一致性认证，也不检查所有更新后的过大变化。
- 固定面板记录上一点正确→错误、曾经正确→错误及masked变化；这能发现退化信号，不会自动防止遗忘。
- 保存多个checkpoint并选开发集最优点，有助于保留候选；它不是训练稳定性的修复。

### 尚未验证的原因假设

| 候选原因 | 应如何区分 | 当前状态 |
| --- | --- | --- |
| O有效训练剂量不足，辅助任务挤占无辅助行动学习 | 按真实O生成tokens、可评分组、语义对比组及更新量比较，而非只看总tokens；必要时做剂量匹配对照 | 已有主要曝光日志；没有完成模型实验 |
| B/P与O的梯度方向冲突 | 在相同冻结batch上比较分域梯度范数与cosine，同时观察O保持；不要由loss系数直接推断参数梯度 | 有局部HF诊断工具，未完成真实训练后端验收 |
| 固定1024分母、回答长度变化与KL改变了更新平衡 | 联合检查长度、task/KL项、ratio/clip、实际参数更新量；归一化比较需注明目前同时改变两项因素 | 两种模式已实现，优劣未知 |
| actor/rollout不同步、恢复或梯度累积存在工程偏差 | 同权重概率检查、恢复前后同batch结果、累积batch与等效batch比较 | 部分门禁及CPU测试已有，GPU验证未做 |
| 小面板、单次生成或current-team伙伴同步变化造成测量波动 | 固定输入跨checkpoint配对；必要时重复rollout／训练seed，并分开静态能力与交互成绩 | 固定面板已有；未完成重复性实验 |
| 长程训练真实丢失已获得的能力 | 用同题、同渲染、同评分与覆盖统计，确认多个checkpoint可复现的退步；区分masked、格式失败、动作错误 | 有保持计数，没有建立防遗忘干预的证据 |

### 历史四臂验收建议（本轮以开头SP/O范围为准）

1. 先完成Q0探测及GPU工程验收，确认314个P训练候选中实际采样能产生多少语义对比；“存在正负动作”不保证模型会生成两者。
2. 从同一Q0、相同输入计划开始短程O基线，再比较辅助配方。现有8-block校准命令可用，但尚未指定它足以判定稳定性，也未确定所有比较预算。
3. 结合O正确率／regret、同题遗忘、格式合法率、P覆盖／屏蔽率，以及每域有效曝光、长度、task/KL和ratio变化判断。不能只看总reward或B准确率。
4. 若出现重复退化，一次检验一个主要因素：有效O剂量、辅助系数、归一化因素、LR或KL。不要同时改多项再将恢复归功于其中之一。
5. 明确更密集评测、可接受退化幅度、重复次数以及是否停止／回滚，再进入长跑。这些阈值与策略**尚未决定，也没有实现基于能力退化的自动停止／回滚**。当前已增加本页开头所述静态O密集监测；完整交互在Q0及每10次更新评估；训练结束点也评估，训练后的这些评估点均保存为候选checkpoint。

目前没有加入新的能力保持回放、监督锚定、梯度投影、动态任务权重或自动调KL方案；这些是可能的研究选择，不能写成已有功能。已有KL参考约束和B/O覆盖序列也不等于这些干预已经得到验证。

## 共同开发评测

所有四臂用同一原生完整交互dev和同一paired panel。paired panel按整个parent选择，当前25个canonical cases；原记录75个视图，实际发送73个视图（隔离2个不合格P）。报告B/O正确率、P条件正确率及可评分覆盖／masked数、parent macro、合法率、有效样本上的regret，以及同题相对上一checkpoint/历史曾经正确的遗忘计数。P的regret仍是源posterior下的诊断值，不替代三态奖励或代表整个定性范围的worst-case regret。

主选择规则：current-team完整交互的全样本自身utility保守下界优先；O parent-macro正确率打破平局；相同则保留更早点。**这里所有座位是当前模型，不是固定Q0伙伴。** 终局未完成的下界沿用现有保守全局收益界，没有伪造terminal reward。B/Pplus分数不参与主模型排名。

Q0起点做同协议评测；此后默认每10次更新完整评测并保存，预算结束或步数上限结束也评测保存，保留这些native checkpoints以及最新恢复点。SP完成整局可能超过边界，按真实tokens披露，不能称完全相等剂量。比较时同时报告预算末端、共同dev选出的模型和逐项保持曲线。P不含历史，因此P正确/O错误可帮助定位证据推断或端到端组合问题；B/P现在使用相同定性表示，但仅凭各项准确率仍不能证明模型内部形成了有效推理链。

## 实现文件与可复查证据

| 内容 | 文件 |
| --- | --- |
| 原生回放、题组、分割、定性B/P构建与面板 | [reasoning_bank.py](../../../training/social_mixed/reasoning_bank.py) |
| P无历史、无数值belief的实际请求 | [history_free_requests.py](../../../training/social_mixed/history_free_requests.py) |
| 逐题LP审计与原453题筛选分析 | [QUALITATIVE_CASE_AUDIT.md](QUALITATIVE_CASE_AUDIT.md)、[CANDIDATE_453_AUDIT.md](CANDIDATE_453_AUDIT.md) |
| 角色资格、B查询修复、审计值绑定 | [apply_reasoning_policy.py](../../../training/social_mixed/apply_reasoning_policy.py)、[training_plan.json](training_plan.json) |
| P三态工具调用评分 | [reasoning_scoring.py](../../../training/social_mixed/reasoning_scoring.py) |
| 辅助槽位、语义屏蔽、组内advantage | [reasoning_training.py](../../../training/social_mixed/reasoning_training.py) |
| 条件评测、覆盖、保持与选择 | [reasoning_validation.py](../../../training/social_mixed/reasoning_validation.py)、[pipeline.py](../../../training/social_mixed/pipeline.py) |
| 100块预定辅助曝光 | [planned_exposure.json](planned_exposure.json)；B/P各300组，分别覆盖142/164个不同case，不保证每题均被训练 |
| 本地54项测试及环境限制 | [implementation_checks.json](implementation_checks.json)、[cpu_preflight.json](cpu_preflight.json) |

损失系数、候选数、可评分数和参数梯度不是同一概念。当前不会因屏蔽而补采至mixed；按全部候选保持固定任务权重，因此masked较多的组会贡献更小的有效任务信号。这是需PRO评审的剂量取舍，不是日志显示组数相同即可忽略的差别。

## 复现与训练入口

重建及CPU标签检查：

```bash
python -m training.social_mixed.reasoning_bank
# 重建后自动应用已冻结的角色策略；若价值/候选belief变更则拒绝复用旧审计
python -m training.social_mixed.reasoning_preflight --output examples/social_mixed/paired_bank_v2/cpu_preflight.json
```

在有本地Qwen tokenizer的训练环境检查全部实际prompt长度（不联网、不截断）：

```bash
python -m training.social_mixed.reasoning_preflight --tokenizer "$SOCIAL_MODEL" --output /tmp/reasoning-context.json
```

准备32个训练case的Q0探测请求，每视图8回答；不合格或无负例P不发送。当前共712个请求（O=256、B=256、P=200），不调用模型：

```bash
python -m training.social_mixed.reasoning_probe --prepare-only --output /tmp/reasoning-q0-requests
```

实际探测使用同命令去掉`--prepare-only`，显式提供`--base-url http://127.0.0.1:8000/v1 --model <served-name> --checkpoint-hash <sha256>`，并换一个空输出目录。该服务需支持原生工具；请求temperature=1、max_tokens=1024。零成功是风险信号，不是成功概率为零的证明；探测不自动按结果筛训练题。

本轮不使用缩短 `--total-tokens` 的8块校准命令，因为这会压缩cosine学习率过程。按完整预算启动SP/O，通过前8次更新的密集O监测观察早期稳定性。

已有SoC环境中的四臂入口：

```bash
bash examples/social_mixed/start_training.sh h100-96 four
```

该命令会提交GPU任务；本次本地工作没有执行。脚本提交前运行完整tokenizer检查及配置测试。`SOCIAL_NORMALIZATION`控制共同归一化；原BP及原配方可使用`--recipe legacy`。不要将旧checkpoint续训冒充新四臂共同Q0起点。

## 当前验收边界

CPU重算与接口检查不等于模型已经学会social reasoning。本轮SP/O启动前还需Q0可训练性、精确tokenizer长度与现有GPU概率监测及非有限值门禁；完整GPU恢复/累积梯度专项和B/Pplus保持验收暂不列为本轮必做项。当前manifest保持`formal_training_ready=false`。本机没有Hydra、Transformers/tokenizers及训练GPU环境，未报告这些GPU/配置检查为通过。
