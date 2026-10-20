# 9月与当前 pipeline 配置快照及逐项对照

**远端CPU交付：**[新100父游戏完整求解指南](REMOTE_SOLVER_20261021.md)及
[本地验收](REMOTE_SOLVER_VALIDATION_20261021.md)已完成；明确记录预算/初始化/恢复与验收差异。
远端尚未运行，不改变以下旧训练配置，也未将父游戏认证当作Q/S/D或训练完成。

**2026-10-21新设计研究：**用户已同意[调查目标新规则](KNOWN_QUERY_RULE_20261021.md)。
[新100原始父游戏](PARENT_POOL_V1_20261021.md)已冻结，全两轮、2/3人67/33；
[预定12例](PARENT_POOL_V1_PROBE_20261021.md)7例终局认证、5例缺失，88未尝试。
旧100、旧checkpoint和下文历史配置身份保留；新池未接入训练/prompt，未测新S/D，active仍v8。

**报价额度整批结果：**[原100父游戏检查](OFFER_QUOTA_ORIGINAL_POOL_RESULTS_20261021.md)完成：70局等价、29局新认证、1局仍缺失。
99个有效配对的真实调查见证6→16；预算/初始化重试各自留痕。独立偏好、调查、生产prompt/评分/训练未改，未生成新slice或D。

**研究对象澄清：**[固定原100父游戏](OFFER_QUOTA_ORIGINAL_POOL_SCOPE_20261021.md)研究报价额度，
保留不需调查的题，不以额外控制题替代正式对象。额度1在30个两轮局生效、70个一轮局冗余；
仅完成身份/合法性审核，未重求整批profile、重测C/S/D或改生产配置。

**2026-10-21当前决定：**调查保持原机制，先单独研究提出OFFER立即扣除个人报价额度，dependent preference暂缓。
[首轮研究](GAME_OFFER_QUOTA_RESEARCH_20261021.md)已完成7父游戏×2条件的14次CPU终局认证：部分报价承压，
尚未增加这批样例的最优调查优势。仅独立机制研究，生产active/prompt/Oracle/题库/训练配置不变。

**2026-10-21免费调查补充：**[时机精确诊断](GAME_FREE_INVESTIGATION_TIMING_20261021.md)已运行：
一次额度本身不能排除开局必用；后续公开信息帮助选目标时，等待可以严格更优。
仅新增机制诊断记录，生产游戏/Oracle/题库/prompt/active及训练配置不变，未重测D。

**2026-10-21工作顺序更新：**先解决游戏机制，再继续prompt。[机制提案](GAME_MECHANISM_PROPOSAL_20261021.md)
及独立toy验证已记录，但当前生产游戏/Oracle/题库/prompt/active版本不变，不把新原型标签混入旧数据。

**2026-10-21核对：**active仍为v8，但参考策略响应平局规则与focal own-only评分尚未对齐；
真实训练上下文有自身收益0/0、其他玩家收益2/4却同得0reward的例子。见
[审阅与证据](PROMPT_PROTOCOL_REVIEW_20261021.md)。V9为状态化输入草案，未激活、未改生产配置，
不得将以下历史CPU检查或结果当作这个新发现已修复。

**2026-10-18更新：当前为v8。** 本文以下保留2026-10-17的v7对照记录；
本轮按逐段审阅简化题面的差异、概率/信息核验及全部解释，见
[PROMPT_REVIEW_20261018.md](PROMPT_REVIEW_20261018.md)，
[v8完整prompt](versions/terminal_v8_readable_20261018/PROMPT_PREVIEW.md)及
[v8配置快照](versions/terminal_v8_readable_20261018/SNAPSHOT.json)。v7快照未覆盖。

记录日期：2026-10-17。**当前待运行版本是 v7；最近实际训练是 v6/job960070。** 本文用原始 experiment、resolved config、实际调用日志和归档源码核对，不能用今天的默认值倒推旧实验。原始配置缺失的字段标“未记录”；配置声明、实际生效覆盖、实际运行结果分别列出。

此次纠正：此前把9月可读题面及具名工具改成 JSON/`act(action_index)`，没有单独向用户说明和确认。这是实验接口变更，不能当作内部实现细节。v7恢复9月的呈现方式，并保留已经确认的当前游戏、Oracle、连续奖励及同节点采样协议。之后每个版本必须登记完整快照；不得覆盖旧版本或继续使用旧版本号。

## 1. 对照对象与原始记录

| 简称 | 实际身份、状态 | 完整原始配置及实际 prompt |
|---|---|---|
| 9月 BP | job866677，`social-stable-v2-b-bridges`；由865319/checkpoint29恢复，非从base开始的独立新run | [experiment](versions/september_bp_866677/experiment.json)、[resolved](versions/september_bp_866677/resolved_config.json)、[request](versions/september_bp_866677/prompt_request.json)、[信号样例](versions/september_bp_866677/call_signal_example.json) |
| 9月 SP | job866677的另一训练臂，`social-stable-v2-b-bridges`；实际恢复位置见原始options | [experiment](versions/september_sp_866677/experiment.json)、[resolved](versions/september_sp_866677/resolved_config.json)、[request](versions/september_sp_866677/prompt_request.json)、[信号样例](versions/september_sp_866677/call_signal_example.json) |
| 9月 D | job881010，`micro-learning-frozen-v1`，`micro24_v1_partner_choice_v1`，40-update micro实验 | [experiment](versions/september_d_881010/experiment.json)、[resolved](versions/september_d_881010/resolved_config.json)、[request](versions/september_d_881010/prompt_request.json)、[信号样例](versions/september_d_881010/call_signal_example.json) |
| 10月旧terminal | job915731，`terminal-step-binary-shared-reset-loo-fixed-questions-v3`；550次更新后暂停 | [experiment](versions/terminal_v3_915731/experiment.json)、[resolved](versions/terminal_v3_915731/resolved_config.json)、[request](versions/terminal_v3_915731/prompt_request.json) |
| 最近实际 v6 | job960070，`terminal-node-regret-grpo-refill-v6`；307次更新后取消，最后保存为270次更新 | [experiment](versions/terminal_v6_960070/experiment.json)、[resolved](versions/terminal_v6_960070/resolved_config.json)、[request](versions/terminal_v6_960070/prompt_request.json) |
| 当前 v7 | `terminal-node-regret-grpo-named-v7`；prompt=`terminal-september-named-v1`；已实现，CPU检查，尚未GPU训练 | [完整prompt](versions/terminal_v7_named_20261017/PROMPT_PREVIEW.md)、[全部默认参数/合同/硬件/YAML/source hash](versions/terminal_v7_named_20261017/SNAPSHOT.json)、[相对v6修改清单](versions/terminal_v7_named_20261017/CHANGELOG.md) |

9月不存在唯一的一套“旧配置”：BP/SP与后来的D micro实验在算法、数据、批次、硬件上本来就不同。上表的历史文件均从原始证据复制，sha256及出处保存在各自 `SNAPSHOT.json`，不是重新生成的历史配置。

**逐字段核对入口：**[历史全部 resolved 字段 CSV](versions/HISTORICAL_ALL_RESOLVED_FIELDS.csv)，涵盖5个历史实验的412个不同嵌套字段路径，包括优化器、模型、推理、并行、checkpoint和环境配置；缺失值为 `NOT_RECORDED`。当前v7全部CLI默认值、四套硬件profile、完整YAML和source哈希保存在v7快照。v7尚无真实GPU运行的resolved config；下一次实际启动会额外写 `pipeline_snapshot.json`，记录真实CLI覆盖和最终resolved config。环境变量解析值不能凭本机CPU环境代填。

## 2. 研究问题、游戏、决策单位和Oracle

| 项目 | 9月 BP / D | 9月 SP | 10月terminal v3 / v6 | 当前v7 |
|---|---|---|---|---|
| 研究训练对象 | 分开监督的belief、planning；D含O/B/Pplus配对域 | 原生完整self-play | 不分开监督；native terminal slices | 同v6 |
| 模型 | Qwen3-4B-Instruct-2507 | 同左 | 同名base；原文件身份另存 | 同v6；实际启动重新核验权重/tokenizer hash |
| 环境 | 当时的data_reasoning_v6 / micro问题定义 | 全体模型行动的整局 | 当前冻结候选与终局reference，不等同9月题库 | 同v6 |
| teacher / 对手 | B/P/O的对应teacher判分，非当前C/S定义 | 全员当前模型，按实际终局效用评分 | 每父游戏一个初态全终局求解、认证并冻结的profile；伙伴和窗口外focal均照此行动 | 同v6；没有换成近视对手或有限深度评分 |
| 严格正确 | B精确集合/偏好判断；旧P含当时0.1容差与响应目标，不能移植为当前定义 | 不以逐步Oracle正确作为训练reward | 当前自身Q的全部并列最优，容差1e-7 | 同v6 |
| 窗口 | 单题/配对题的当时定义 | 完整游戏 | k=1/2/3个实际focal决策，proposal和response都计数；原生提前终局不补齐 | 同v6 |
| 窗口外价值 | 当时teacher / 完整SP实际终局 | 实际完整轨迹 | 固定profile继续到原生终局；窗口内最优contingent policy，非短期承诺utility | 同v6 |
| 私有信息 | 当时各任务的可见信息和工具要求 | 各玩家仅自己的信息 | 私有调查回答只给调查者；隐藏world用于环境，Q/posterior用于评分 | 同v6 |
| 均衡声明边界 | 不能用今日的certificate代替旧teacher定义 | SP不是冻结均衡对手 | 初态自身效用epsilon-Nash及本地support/response检查；不保证唯一或形式上的sequential equilibrium | 同v6 |

当前三人父游戏仍为1轮；多轮覆盖来自30个两人两轮父游戏。v7只恢复prompt，未声称解决三人多轮求解。父游戏原始支持、reference策略概率、Q、C/S、入口、窗口与split文件本轮均未修改。

## 3. Prompt、工具与输出接口

| 项目 | 9月 | terminal v3 / v6 | v7恢复结果 |
|---|---|---|---|
| system | D为“You are answering a reasoning question about a negotiation game…Briefly explain…exactly one requested tool call.”；SP为对应self-play system | 通用短system：brief reasoning +一个act call | 直接复用9月D的完整system原文，不另写替代system |
| 题面 | 自然语言规则、具名玩家/行动/目标、偏好/目标表格、按顺序事件、当前decision | user整体为JSON；native向量、重复game/public_state、按index列合法动作 | 复用9月规则、表格、时间线和当前decision布局；当前support/prior/窗口与目标另明确展示 |
| 解释位置 | 临近作答要求，调用前简述 | brief要求主要在system，离generation位置较远 | system及user末尾 `RESPONSE INSTRUCTIONS` 均明确brief explain再调用工具 |
| 动作工具 | OFFER / PASS / INVESTIGATE / ACCEPT / REJECT；B题另有B专用工具 | 单一 `act({action_index: i})` | native行动按当前局面的具名工具enum注册；不接受旧act作为新接口的备选 |
| offer语义 | self/partner NEW commitment names | native动作是接受后的完整target bitvector，但未在JSON充分说明 | 具名参数只含NEW additions；decoder映射回同一个native target，不会重复追加已有承诺 |
| investigation | player/goal names | 原生整数player/goal藏在action menu | player/goal names；当前私有回答照常显示，仅己方可见 |
| 当前科学目标 | 各历史任务目标不同；部分旧response含social tie要求 | 自身terminal utility与固定reference窗口 | 明说自身终局utility；**未复制旧0.1容差、social tie或不同的调查条件** |
| 输入泄漏 | 看原始各任务request | 旧日志376个上下文核查无Q/hidden-world字段泄漏 | 同样不放Q、Oracle action、隐藏world；公开catalogue是可能性，不是对手真实偏好 |
| explanation评分 | 无“未解释即错误”的独立质量reward | 无独立解释奖励；工具合法仍可得分 | 没有增加解释长度reward或格式惩罚；新增explanation presence/长度观测字段 |
| 解析/生成 | chat template + Hermes工具解析；没有强制仅tool语法 | 同类template/解析，未发现强制tool-only前缀 | 保留底层template、EOS、生成参数与解析器；改的是messages/tools和动作映射 |

可直接逐字查看：

- [9月D原始实际输入](../../new/terminal_node_v6_training_960070/review_20261017/prompt_interface/september_D_rendered_prompt.txt)、[9月SP原始实际输入](../../new/terminal_node_v6_training_960070/review_20261017/prompt_interface/september_SP_rendered_prompt.txt)。
- [旧v6原始实际输入](../../new/terminal_node_v6_training_960070/review_20261017/prompt_interface/terminal_first_rendered_prompt.txt)。
- [新v7完整预览](versions/terminal_v7_named_20261017/PROMPT_PREVIEW.md)：proposal、已有commitments、response、私有调查四种情况，完整system/user/tools，无省略。
- 正式实现：[named_prompt.py](../../training/strategic_slices/named_prompt.py)。训练、slice验证、完整游戏验证、最终test及新D CLI均接入该接口。历史分析API保留显式legacy renderer，旧证据不重写。

输入审计的事实：9月D首批128个base回答全部有解释；v6首批176个仅44个有解释。9月D解释指令到生成位置中位29 tokens，旧v6入口中位985 tokens。9月BP留存2616/2616有解释，D5120/5120，SP4723/5321有非空文本。**这证明接口存在实质差异，不是已隔离因果的模型实验；v7恢复后是否持续解释须由真实训练日志确认。**

## 4. Reward、advantage与credit

| 项目 | 9月 BP | 9月 D micro | 9月 SP | 旧terminal v3 | v6与v7 |
|---|---|---|---|---|---|
| task reward | B/P二分teacher正确 | O/B/Pplus相应二分teacher | 玩家实际终局utility | 每个focal决策Oracle最优0/1 | 合法 `Q(a)-max(Q)`，native连续utility尺度 |
| 对比对象 | 同题8回答，stable recipe挑mixed有效组 | 固定schedule同题8回答 | 终局utility减按游戏bucket历史EMA baseline，非当前同节点8样本GRPO | 本步reward减其他replica的轨迹平均reward；不同后继节点混入baseline | **同一实际节点、同可见题面/posterior/剩余k的8回答** |
| baseline/scale | group mean，非全局标准差白化；task使用固定1024 token分母 | 合法回答组内均值/std，population std+1e-6；不含非法回答 | bucket需累计16个；否则用global；EMA .9/.1 | leave-one-trajectory-out；无std归一化 | `(r-mean)/(sample_std+1e-8)`，correction=1；range≤1e-7时task A=0 |
| 零方差组 | 为有效组目标做自适应候选尝试；task权重0 | schedule固定，等值自然无task差异 | 非同节点组，历史baseline可能非零 | 全对全错可无有效差异，且credit基准不匹配 | 不筛掉、不补采；保留KL，连续值只保留已采到的差异 |
| 非法/截断 | task A=0；独立protocol A=-0.2 | task A=0；独立protocol A=-0.2 | 失败call不分配task credit；独立protocol惩罚 | task reward=0；独立protocol A=-0.2，终止 | task reward为全合法菜单最差 `min(Q)-max(Q)`；独立protocol A=-0.2；抽中失败终止 |
| 多turn credit | 单题组 | 单题组 | 同一玩家episode的terminal advantage分配到其调用 | local reward结合轨迹baseline；trajectory等权、1/T | 每个node独立归一化，只给该回答tokens；无后续A回传、无trajectory baseline |
| loss权重 | B/P各.5；mixed组task权重与protocol/KL权重分开 | O/B/Pplus各1/3；partner版row weight4/3 | 玩家episode task权重归一化；protocol/KL另按call | trajectory等权→decision均值→token均值 | node等权→8回答等权→回答token均值；task/protocol/KL同权 |
| 目标解释 | 历史bridge训练recipe | 冻结micro protocol | whole-episode terminal learning | 不是terminal utility policy gradient | sampled-context Oracle action-value surrogate；不声称等价整局policy gradient或有限训练保证最优 |

当前选择来自此前用户已确认的“每个节点采8次、随机推进一个、连续reward”的方案。这次v7没有借恢复prompt增加GRPO变体、动态过滤、best-of-8推进、长度奖励或额外credit方法。

## 5. Reset、采样、组数、批次与预算

| 参数/流程 | 9月 BP / SP（866677） | 9月 D（881010） | terminal v3（915731） | v6（960070） | v7 |
|---|---|---|---|---|---|
| seed | 42 | 42 | 42 | 42 | 默认42 |
| G | BP同题8；SP按原reset/seat与历史baseline | 同题8 | 同入口8条完整k轨迹 | 每实际node8回答 | 同v6 |
| reset共享 | BP题面固定；SP环境reset按旧代码 | 固定题面 | 每组共享入口/world/focal，replica各自推进 | 每条链一次入口/world/focal；本node8回答共享信息 | 同v6 |
| 下一步推进 | 单题或全SP实际动作 | 单题 | 8条轨迹各自走完 | 生成前均匀选定一个**原始样本位置**；不去重、不看分数；选定者完成可推进 | 同v6 |
| 每更新目标 | BP争取B/P各4 mixed有效组，最多32候选组；SP目标65,536 response tokens | 固定16题组×8=128回答 | 4入口×8条轨迹；回答数随k/失败变化 | 20实际node组，包括零信号组；已接链走完，20–22组/160–176回答 | 默认同v6 |
| 并发 | 实际engine max_num_seqs16；旧批量generate按wave等待 | 32，旧批量generate | 32，旧批量generate | 全局32未完成请求，completion-refill，无整批最长回答barrier | 默认32，同v6 |
| 同批更新次数 | PPO epochs1，按历史batch loss累计 | 1 | 1 | 所有回答，完整batch microbatch累积一次，一遍 | 同v6 |
| 训练预算 | 6,553,600生成response tokens | 5,242,880计划tokens；40-update schedule先停止，实际2,438,815 | 6,000,000；暂停时3,500,783 /550更新 | 6,000,000；取消时1,123,499 /307更新 | 默认6,000,000；尚未运行 |
| 单update token目标 | 65,536；BP实际受有效组流程决定 | options中仍有65,536，但micro固定schedule决定实际批次 | 无固定token/update目标 | 无固定token/update目标 | 同v6 |
| max_steps | 1000安全上限 | micro schedule40 | 10000安全上限 | 10000安全上限 | 默认10000 |
| retry | 旧SP曾有一次协议重试；BP/D按其固定请求流程 | 无当前树式推进 | 抽中失败终止，无retry | 抽中失败终止，无重抽/补答 | 同v6 |
| train tokens计数 | 入训练的response（含旧retry）；整批边界 | 所有训练回答 | 所有回答含失败 | 所有回答含失败；不计validation/test | 同v6 |

“20×8”是已确认的批次目标，不是文献给出的唯一最优配置；它与train_microbatch=1不是一回事。更换prompt会改变response长度，因此相同6M预算下更新数、题目曝光和耗时均可能改变；不能写成这些量也相同。

## 6. 优化器、生成、长度与数值参数

| 项目 | 9月 BP / SP | 9月 D | terminal v3 | v6实际 / v7计划 |
|---|---|---|---|---|
| 底层训练 | ROLL PPO/GRPO适配，Megatron actor，HF frozen reference，vLLM生成 | 同类适配，micro credit入口 | 同一基础栈，terminal subclass | 同一基础栈；这次未换训练器 |
| ppo_epochs / clip / KL | 1 / .2 / .01 | 1 / .2 / .01 | 1 / .2 / .01 | 1 / .2 / .01 |
| reference model | frozen base参数；不同于环境Oracle | 同左 | 同左 | 同左 |
| loss aggregation | resolved为seq-mean-token-mean；实际另受task_denominator/weights覆盖 | seq-mean-token-mean + micro row weights | trajectory权重 | node/candidate/response-token均值 |
| whiten_advantages | false | false，micro自身组内std | false | false，node自身组内std |
| LR | 实际driver按response token cosine：1e-6→1e-7；resolved的constant_with_warmup不是完整生效描述 | `frozen-by-update`，使用冻结schedule每步LR；不能用配置中的1e-6代替整条schedule | token-progress cosine1e-6→1e-7 | 同v3 |
| optimizer | Adam beta(.9,.95)，weight_decay0，warmup0 | 同左 | 同左 | 同左；其余所有字段见resolved CSV/YAML |
| BF16 / recompute | BF16，full | BF16，full | BF16，full | 同左 |
| train context / prompt cap | 4096 /3072 | 4096 /3072 | 16384 /15360 | 16384 /15360；超限报错不截断 |
| engine max_model_len | 4096 | 32768；不能误称训练也支持32768 | 16384 | 16384 |
| max response | 实际native SamplingParams1024 | 1024 | 1024 | 1024 |
| train generation | temp1，top_p1，top_k−1，repeat_penalty1，n1 | 同左 | 同左 | 同左 |
| validation generation | greedy | greedy | greedy | greedy，temperature0 |
| template / parser | 原生apply_chat_template，普通assistant generation prefix；Hermes parser | 同左 | 同类，prompt接口已变 | template/parser参数不变；具名tool enums恢复 |
| stop | native tokenizer EOS；未强制仅输出tool | 同左 | 同左 | 同左 |
| behavior概率检查 | options阈值未全部显式记录；完整resolved见原文件 | mean delta .05 /clip fraction .01 | .05 /.01 | .05 /.01，有限偏差warn；基础设施/非有限错误abort |
| engine优化 | 各resolved不同，逐字段CSV可查 | prefix cache开，chunked prefill关，cascade attn关 | 实际配置见resolved | prefix cache开、chunked prefill关、cascade attn关；completion-refill只改调度 |

注意部分resolved里 `generating_args.max_length=512` 是通用默认字段，原生worker实际调用传 `max_tokens=1024`；不要把512写成实际回答上限。当前也未改成4096输出。独立D测量用自己的温度/长度配置，和训练不是同一套生成参数。

## 7. GPU、并行、microbatch、offload与环境

| 项目 | 9月 BP/SP实际 | 9月 D实际 | terminal v3/v6实际 | v7 CLI默认 |
|---|---|---|---|---|
| profile / GPU数 | h100-47 /2 | h200-141 /1 | h100-96-single /1 | h100-47 /2；**不是v6实际单卡配置** |
| actor train TP | 2 | 1 | 1 | 2 |
| infer TP | 1/worker，两GPU worker | 1 | 1 | 1/worker；全局并发32 |
| train microbatch | 1 | 2 | 1 | 1 |
| reference microbatch | 1 | 4 | 1 | 1 |
| actor/reference resident | false /false | false /true | false /false | false /false |
| vLLM memory fraction | .50 | .45 | .40 | .50 |
| engine max_num_seqs | 16 | 32 | 32 | 32 |
| sequence parallel | TP2默认开 | TP1默认关 | TP1默认关 | TP2默认开；SOCIAL_SEQUENCE_PARALLEL可显式覆盖 |
| CPU缓存 | 不适用当前terminal树 | 不适用 | v6：树512MiB、Oracle128MiB、prompt16MiB；仅内存 | 同v6，不改变精确Q或reference |

v7还保留 h100-96（2卡、train MB2/ref MB4、reference常驻、vLLM .55）、h100-96-single（单卡、MB1/1、均offload、.40）、h200-141（单卡、MB2/4、reference常驻、.45）。全部profile字典见v7 SNAPSHOT，实际覆盖进入每次run snapshot。Slurm默认2×H100-47、24 CPUs、3小时；单卡运行需同时覆盖Slurm资源及profile，不能只改其中一个。

原始环境分别保存在各历史目录的 `environment.json` / `environment_details.json`，包括Python、CUDA、driver、GPU等已记录项。上述866677、881010、960070的包记录均为 torch2.13.0 / transformers5.16.1 / vLLM0.28.0 / Ray2.46.0 / megatron-core0.12.3 / transformer-engine2.19.0 / flash-attn2.8.3.post1；不能仅凭这些相同就认为完整环境相同。v7没有远端实际环境记录，沿用现有环境的意图与实际记录分开。

## 8. 题库生成、C/S/D、筛选、split及题面覆盖

9月使用data_reasoning_v6，不是当前terminal pool。866677和881010原始data manifest hash均为 `730f0d819b3a9e48cbcdc781b17cd5db580317d569f196ae0b97f2fb66e0729d`。BP有bridge/coverage/difficulty curriculum与自适应有效组流程；D是固定micro bank和schedule，不能称为当前D/C筛选。881010额外bank hash与版本在其experiment原文件中：micro_bank、compact_bank、paired_bank分别记录完整sha256，training_pool=`micro24_v1_partner_choice_v1`，micro_variant=`24v1_partner`，coverage=`global-frontier-curriculum-btolerance-v4`，difficulty=`within-view-curriculum-v2`。

当前 v3/v6/v7 共用下列冻结资产（v7没有重选题）：

| 项目 | 当前冻结值/定义 |
|---|---|
| pool | `new/local_data/strategic_slices_oracle_consistent_candidates_v4` |
| selection | `new/local_data/strategic_slices_terminal_selected_v4` |
| pool manifest SHA256 | `a4330e5b5038d2e33e11ebd366651f2ed388cb850b1fa7ef6e4539d9d0bb06e9` |
| pool+selection联合训练身份 | `6080bc30f1a70b995bb9d7bfcdc3ed633bd0ff64bfd759691cf758f4533c4379` |
| parent/candidate规模 | 100父游戏、800候选、每父8候选；2/3人各50父 |
| 轮数 | 2人1轮20父、2人2轮30父、3人1轮50父 |
| world支持大小 | 40父大小3、22父大小9、38父大小27 |
| split | train63父/504候选；validation12父/96；test25父/200；按父冻结，不能把family完全隔离当作已实现 |
| 结构覆盖 | pool68 families；强query信息12候选/6父；entry-private-answer groups共10 |
| pool门槛 | min_C=.1；min_increment=.05；min_S=.05；min_information_set_mass=1e-10；min_distinct_histories=2；入口分层/保护规则见manifest |
| C/S口径 | 相同belief与物理树下完整contingent policy；query/future public/entry+future各通道分别测；null=未测，通道不相加 |
| D定义 | `V_star - mean(native terminal utility)`；失败不填虚假终局utility；有失败时主D=null，另报completed-only与bounds |
| D采样 | 每候选8次独立入口/world抽样及模型/reference RNG，6400条轨迹，6200完成；是历史JSON/act prompt测量 |
| 进入选题池 | 仅train；保护全部query S>.05与所有train entry-answer关系成员；其他需至少一条完成并观测到window gap/completion差异或same-prompt any-step价值差异 |
| 选题优化 | 恰100题；parent≤4；family≤max(8,强制保护数)；目标每覆盖family +10、parent +3、信号/D分数，配额绝对偏差−2 |
| 信号分数 | 4×any-step contrast +.25×mixed completion +min(1,gap_span/C) +.5×clip(D_completed/C,−1,1) |
| 限制/保护 | 241 eligible；39 protected；1个family因强制保护放宽到9；不是D>0或8次必须全完成的硬筛 |
| 最终100题 | 56父、37 families；k1/2/3=52/29/19；2/3人=54/46；proposal/response=54/46；12强信息题，9entry-answer groups |

完整原始门槛、所有候选、题目ID、reference文件hash、抽样分布分别在pool `manifest.json` / `candidates.jsonl` / `parents.jsonl` 和selection `SELECTION.json` / `COMPLETE.json`。它们的文件hash作为训练data合同核验。

**prompt修复后的边界：**本轮未重新跑D，也未改100题名单。旧D不是新prompt D，且“过去8次出现差异”不保证训练任意时刻仍有差异。v6后期几乎总采同一动作，连续reward也无法凭空制造组内advantage。未增加hard-example动态替换、强制探索或奖励改造。

## 9. Validation、test、保存、恢复和日志

| 项目 | 9月 | terminal v3 | v6与v7 |
|---|---|---|---|
| 验证对象 | 各自BP/SP/micro题库；具体范围以原配置/日志为准，不能代填96 | 当前96 slices/12 parents，完整游戏team/focal-vs-reference | 同v3；具名接口在v7统一 |
| 周期 | 每10更新验证/保存 | 每10更新；550更新对应55次周期验证，另base | 每500K训练response tokens验证、1M保存；base和正常结束另评测，新best即时保存；同一步去重 |
| 调度实现 | 旧同步批量 | 旧同步 | v6/v7训练、slice评测、full game评测都完成即补位；cohort结果固定顺序汇总 |
| best | 各历史pipeline规则见其source/日志 | validation full-window success，并列取较晚；base不参与 | 同v3；不使用test选best |
| checkpoint保留 | BP/SP keep2；D实际keep1 | best+latest/final去重，最多2 | 同v3；v7新增prompt/version身份，不允许v6直接续跑 |
| 最终test | 各实验定义，不是当前200题test | 正常完成训练预算后final-only，200 slices/25 parents，8 repeats | 同v3；暂停/取消/步数上限未完成预算不自动test |
| 评测指标 | 各任务正确/utility | strict动作率、window成功率、root、regret、completion、full-game utility | 同v3；信息题子集缺失须明确，不把总体正确率当信息推理提升 |
| 调试/证据 | calls/units/games、metrics、resolved、environment | 同类证据 | 加phase耗时、scheduler/cache、概率偏差；v7再加解释出现率/长度和run快照 |
| 恢复 | 各历史recipe/source合同 | 最近完整checkpoint，严格身份 | 严格data/model/source/profile/seed/预算/采样合同；新output；不混用v6 checkpoint和v7prompt |

已知评测限制：validation/test没有强query信息阳性题；test曾在base D分析中被查看，不能宣称完全未触碰盲测；family未完全held-out。当前只完成slice训练入口，匹配的新正式SP训练臂尚未实现/运行；旧SP模块存在独立label-review hash问题。恢复prompt没有解决这些研究条件，也不意味着两臂正式对照已经齐备。

v6实际训练不是“完全没提升”：base window成功49/96；119更新72/96；270更新80/96。与此同时6,279个节点组只有140个有task信号，232/307更新仅剩KL，后期98.7%组只采同一动作；12个需要调查的训练题在step50后3272回答中无正确调查。因此总体提升和信息题/探索失败必须分别记录。完整证据见[960070审计](../../new/terminal_node_v6_training_960070/review_20261017/README.md)。这些是v6结果，不能写到v7名下。

## 10. 来源、核验范围及无法补造的信息

- 9月BP/SP原始记录：`new/training_chain_evidence_20260921/new_bp/segments/866677`、`new_sp/segments/866677`；9月D：`new/d24_partner32_evidence_20260926/training/decomposed-seed42-881010`。完整历史源码证据：`new/pro_final_training_review_20260922/full_evidence.zip`；9月D原始commit不在本地git对象库，保留其原始记录，不声称由当前HEAD还原出全量源码。
- 旧terminal原始归档：`new/terminal_hf_test_calbench_20261008/raw/training-915731.tar.gz.part*`；v6：`new/terminal_node_v6_training_960070/raw/training-960070.tar.gz.part000`，sha256=`29b6afabd9d68ae91d3a9f5deba267d3b2ba17f47344a59a8c465f341b47f04a`。
- JSON/act接口已出现在2026-10-05 commit `8377f5bb2ef27643239df1cdb8b09ae456bf3994` 的strategic_slices/common.py中；不能把它归因于本次日志导出或模型自行改变prompt。
- v7接口迁移核验覆盖v6实际日志376个不同context、2,045个合法动作，含53个私有调查context：native菜单完全一致，具名调用全部round-trip回原索引，错配0；详见[迁移报告](versions/terminal_v7_named_20261017/native_interface_migration.json)。未重算Oracle，未调用模型。
- CPU单测、配置检查、完整prompt导出只证明已检查的代码性质；没有GPU采样、显存、吞吐、训练效果或收敛结论。用户无法独立GPU smoke，未将其设为前置条件，也未提交新训练。
- 本文不是全仓库所有历史试验的伪造重建；上面明确列出的5个实际run是此次逐项对照的证据范围。9月其它run若要加入，必须从它自己的原始记录注册，不能套用866677/881010。

## 11. 后续每个版本怎样留痕

[版本总索引](versions/index.json)是机器索引，[版本说明](versions/README.md)是操作说明；根目录[AGENTS.md](../../AGENTS.md)约束后续修改。

1. 改prompt/工具/算法/参数默认值/筛选/Oracle/采样/评测/执行实现前，读本对照和active快照；使用新版本号。
2. 新版本目录先写CHANGELOG：父版本、逐项差异、动机、授权、数据/D身份、尚未验证项；导出真实request生成的完整prompt。
3. 完成CPU检查后运行 `python -m examples.strategic_slices.freeze_pipeline_version`，冻结默认值、所有profiles、YAML、合同、source哈希和review文件哈希；拒绝覆盖旧版本。
4. 正式训练及source打包入口检查注册快照，源码或已冻结prompt变了但没登记时直接失败。每次实际运行再保存 `pipeline_snapshot.json`，包含所有CLI实际覆盖、resolved config、模型/数据/source合同。
5. 临时CLI覆盖不改代码版本，但它本身形成新的run快照；有意更改协议或默认值必须建新pipeline版本。运行结果、checkpoint及日志绑定其真实版本，不能回填到另一个版本。
