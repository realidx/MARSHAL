# BENAC-P 完整诊断实验协议 v1

本实验检验两项能力缺口及其功能依赖，不预设模型一定失败。
“分别测量”指实验上可分离的计算要求；“dependent / causal”指显式 belief 接口与
交互行动之间的干预效应。不能同时声称两项能力在统计上独立，又声称它们互不影响。
本协议不识别 LLM 内部的两个独立神经模块，也不把一个模型的结果推广到全部 MAS。

统一入口：`bash examples/benac_p/run_full_diagnose.sh`。
它完成实例生成、oracle 认证、全部静态对照、模型行动引出的动态分支、评分、按 game
聚类的置信区间以及报告。旧 `run_menu_diagnose.sh` 只保留为 11 题 smoke pilot。

## 1. 要回答的四个问题

| 问题 | 排除什么混淆 | 主要测量 |
|---|---|---|
| B：能否从伙伴行为形成正确 belief？ | 不要求规划或选择行动 | 独立 belief task 的 posterior excess Brier、TV；数值 likelihood 对照 |
| P：给定正确 belief，能否正确规划？ | 不需要自己从 history 重建 belief | oracle-belief planner 的 terminal-utility regret |
| B → P：修复 belief 会不会改变同一状态下的计划质量？ | 固定物理状态、action set/order、prompt 模板，仅替换显式 belief 数值 | 四格矩阵与成对 belief-repair effect |
| P → evidence → B：当前行动是否导致不同的未来学习结果？ | 强制执行指定当前行动；枚举全部响应，避免挑选成功轨迹 | 信息通道差异、expected proper Brier、chooser × updater 四格矩阵 |

预测、lookahead 和 branch comparison 仍属于 P，不增加第三个 primitive。
先做 B/P 独立读数，再看干预；不得把“belief 估计有误”自动解释成“任务上有损失”。

## 2. 实例、先验与数据隔离

默认准备 24 个 game，前 12 个 discovery，后 12 个 confirmation，各自交替包含
6 个未筛选随机实例与 6 个 decision-relevant 实例。seed 10000 是整个实验的种子；
实际 candidate seed、筛选次数和门槛写入 certificate。两部分必须分层解释。

未筛选层有 3 个 player、行动数 (2,2,1)、4 个 ALL_OF goals，包含一个三方目标；
其余结构、偏好、prior 权重和已知 soft-policy temperature 随 seed 改变。它估计
该声明生成分布上的表现，不根据 action gap 排除实例。

Decision-relevant 层以既有依赖 motif 为基础，加入一个随机额外 goal，随机改变
该 goal 的 ego / partner 偏好、prior 权重和 policy temperature，形成 6-goal game。
在任何模型调用之前要求：(i) frozen-prior continuation 下选择的首步，在真正自适应
continuation 下相对最优首步的 regret >0.005；(ii) 最优首步下更新 belief 的价值 >0.02。
最多检查 256 个 candidate，失败则明确终止，不回退成无正 gap 的实例。
筛选使用按固定 latent world 枚举的快速 reference；入选实例再由正式 BayesPlanner
核验最优值。这是**条件诊断分布**，不能用它估计未筛选任务中的失败率。

每个 game 的隐藏偏好组成两个公开 joint types，跨互动持续；P1/P2 均可能随 type
改变。这是明确声明的有限相关 prior，不等于原始 IID goal-preference generator。
正向 anchor 独立保留且不进入 confirmation；dependency 层与它共享设计 motif，
因此该层 confirmation 仅表示未见具体实例，不等于未见任务家族迁移。

主实验使用短的已排定子博弈 (P0,P0)，以便全动作与全响应 exact search。
这足以诊断当前规划、信息获取和随后重规划，但不单独证明长程 MAS 泛化。
另外纳入已知 partner 类型的三方长/短 horizon 对照 (P0,P2) 与 (P0)。

另有三个不进入 confirmation 统计的 pack：

1. 已筛选的 menu 正向 anchor：验证仪器可以测出任务相关的信息使用价值。
2. No-information：partner uniform_mix=1，所有响应与 hidden type 无关。
3. Known-type：先验是 singleton，更新不应提供额外类型信息。

每个主 pack 选择：

- 同 partner、option-wise ego immediate utility / 新增 commitment 数量匹配的两个 menu，
  以 exact mutual information 差最大的 pair 分别作为 high/low 通道。
- high menu 的第一个 offer，作为单 offer 对照。
- 终局回报最优的 reference 首步，作为 optimal 行动干预。
- 模型在正确初始 belief 下自行选择的首步，作为动态 model 行动干预。

high/low 是信息通道的实验设计，不意味着 high 是最优规划动作。只有 optimal arm
按照终局收益选动作。未筛选层的所有 game 都保留；条件层公开筛选命中率。certificate 列出 information gap 和
belief-sensitive decision 的数量。若生成集缺乏正 gap，判定仪器覆盖不足，不能从
“没有测到依赖”推出模型没有依赖。

每个 action 的 REJECT / ACCEPT 或 CHOOSE_1 / CHOOSE_2 全部枚举，用真实概率
加权；不是将三个 outcome 当成三个独立 game。PASS 的 posterior 保持 prior。
同一个 game 的多种 arm 和 response 也不算独立重复样本。

模型输入不含真实 type、private partner matrix、reference Q、最优动作或 oracle
标记。planning task 的 action 顺序按 seed 随机化，同一个 case 的各 intervention
保持同样的顺序。任务调用次序随机化，模型 belief → 注入该 belief 的 planning 保留
必要先后关系。每次调用是独立会话，不带入上一次的回答或 oracle 标签。

## 3. B：独立 belief 测量

同一个合法 history 分别运行：

- `belief`：public state/history、自己的偏好、完整 joint-type support 和 initial prior、
  known partner policy，输出各 joint type 的 posterior probability。不给 legal-action
  选择题，不要求行动或策略。
- `bayes_arithmetic`：直接给同一 observed event 在各 type 下的数值 likelihood 与 prior，
  只做归一化更新。用来区分伙伴行为 likelihood 理解与纯 Bayes 算术。

主要误差为 excess Brier：\(\|\hat b-b^*\|_2^2\)，同时报 TV 与 clipped KL
（log 分母下限 1e-12）。它们衡量显式 posterior 报告，不直接证明内部 belief 表征。
模型 posterior 再输入 reference planner，并在真实 posterior 下评估所选动作，得到
`oracle_planner_regret`，判断 belief error 是否有任务代价。

No-information 和 known-type 是更新的负对照。Root belief 是 prior 复制对照。
大量错误若只出现在算术题，不能独占归因于 partner modeling；若 raw-belief 比
likelihood-table 明显更差，说明困难还包括从互动行为推断 evidence likelihood。

## 4. P：独立 conditioned-planning 测量

提供真实物理状态和**完整正确 joint posterior**，去掉原 history 与 initial prior，
从而不需要重新推断 partner。给出所有合法行动，用 index 输出消除 native tool
序列化失败。已知伙伴策略使用同一公开公式。目标是实际 ALL_OF 终局 utility。

\[
R(a)=V^*(s,b^*)-Q^*(s,b^*,a).
\]

主指标为 `plan_oracle` regret；正 regret 表示即使 belief 被修复，决策仍有损失。
同时运行 history-only planning，作为自然接口的补充，不与显式两阶段模型混为一谈。

每个 game 独立测一个 grounding task，计算两个 offer 执行后的即时 utility。
既报告全部样本，也报告 grounding 正确子集。该小 grounding probe 只能降低
机械状态理解的混淆，不能保证排除了所有 arithmetic / grounding 错误。
另有已知类型的长/短 horizon 对照，检查误差是否涉及 future partner action。

## 5. B → P：真正的四格矩阵

同一 case，在一个全新的 planner 调用中注入 model belief 或正确 posterior。
二者使用**完全相同的 prompt 模板**，差异只有 belief 概率数值。
模型 belief 来自独立 belief-only 调用；不把历史留给 planner 重新覆盖该 belief。

以下单元均用真实 posterior 的 Q 评分：

| belief / planner | 模型 P | reference P |
|---|---|---|
| 模型 B | R_LL | R_LO |
| 正确 B | R_OL | R_OO=0 |

- B 独立任务代价：R_LO。
- P 在正确 belief 下的缺口：R_OL。
- 修复 B 对模型 P 的效果：R_LL − R_OL。
- 修复 P 在模型 B 下的效果：R_LL − R_LO。
- 非加性交互：R_LL − R_OL − R_LO + R_OO。

另有同格式 prior 注入 placebo/control。Root、no-information 情况下 oracle belief
和 prior 一致；其差异可暴露接口/调用噪声。脚本额外报告模型 P 在它实际收到的
model belief 下的 regret，避免将“依据错误 belief 合理行动”算作纯规划失败。

交互量可以正、负或零。**非零交互不是双向时序依赖成立的必要条件**：一个纯粹由
错误 belief 引起的损失，可有正向 belief-repair effect，却恰好是加性的。
不能因为某次注入收益为负就改样本或切换指标。

## 6. P → evidence → B：行动干预和第二个四格矩阵

先让模型在正确 initial belief 下选择首步，隔离“自己原先 belief 错了”这个来源。
reference 同样按长期终局收益选首步。随后分别 **do(model action)** 与
**do(reference action)**，枚举全部 partner 响应，并重新调用同一个 belief updater。
静态 high/low matched menus 与 single-offer arm 也这样处理。

用以下两个读数区分“通道提供了多少信息”和“模型有没有用上”：

\[
I_M=H(b)-\sum_y p(y\mid M)H(b_y^*),
\]

\[
\mathbb E[\text{Brier}(\hat b_y,Z)]
=\sum_y p(y\mid M)[1-\|b_y^*\|_2^2+\|\hat b_y-b_y^*\|_2^2].
\]

只比较 posterior error 不够：更丰富的 evidence 可能更难处理，因此还要比较真实
latent type 下的 expected proper score。模型不会收到 reference posterior。

第二个四格矩阵以第一位表示 chooser（模型/参考），第二位表示 updater（模型/参考），
四格 downstream planner 都固定为 reference：

\[
J_{m,u}=\sum_y p(y\mid do(a_m))Q^*(s_y,b_y^*,P^*(s_y,b^u_y)).
\]

脚本中的 `chooser_updater_utility` 给出 J_LL、J_OL、J_LO、J_OO：

- 修复 chooser：J_OL − J_LL。
- 修复 updater：J_LO − J_LL。
- 交互：J_OO − J_OL − J_LO + J_LL。

此外记录 model-updater + model-planner 的 continuation regret，作为完整两阶段
policy 的补充。缺失任一 response 不会将余下分支重新归一化冒充期望。

最后有一个 future-objective 干预：同样的当前 observation、prior、行动集与
partner response kernel，但声明 reward 在当前响应后结算，不再有后续 ego decision。
观察模型的行动、选择通道的信息量是否改变，并比较原长期 objective。这里特意
**不重建单轮 partner kernel**，否则原 soft-progress 的末轮权重变化会污染干预。

这些干预确立的是显式行动改变未来 evidence、而 evidence 进入更新/规划的功能路径。
Menu outcome 同时改变 commitment state；matched immediate utility 与 bit count
不能消除未来物理状态差异。因此 J 的差异是整个选择行动的总效果，不能命名为
纯信息的 reward-mediated causal effect，更不是模型内部神经机制因果证明。

## 7. 统计、结论标准与决策

主结果只看 confirmation games，discovery 用于探索与调试，anchor 单独列出。
前述 24 个 game 是首轮可执行规模，不是 power 保证。独立 belief error 使用 high-menu
通道；planning、belief 的任务代价以及 belief→planning 四格干预使用 optimal-action
响应分支。按各自真实 response 概率加权，再按 game 等权汇总，bootstrap 2,000 次抽整个 game。
输出 95% percentile interval。完整响应缺失的 game 从相关聚合指标排除并计数，
不只对其有效 outcome 重新归一化。无明显 decision gap 的样本保留并报告。

先查看 validity 与 grounding。建议首轮解释门槛：format valid ≥98%、grounding
≥95%、confirmation 有至少 10 个完整有效 game；各层默认只有 6 个 confirmation game，
分层区间仅作 pilot 读数，正式确认建议至少 `BENAC_DIAGNOSE_GAMES=48`。
覆盖不足时先解决测量质量或增加样本。
这些是 pilot 的判断门槛，不是通用统计定律，也不以过滤方式抹掉失败。

- 支持 B 缺口：可重复的 posterior error，且在 oracle P 下产生任务 regret；
  raw 与 arithmetic 对照帮助限定缺陷来源。
- 支持 P 缺口：oracle-belief regret 稳定为正，在 grounding 合格子集仍出现。
- 支持 B → P：配对 belief-repair effect 为正，并有 decision-sensitive oracle 证书。
- 支持 P → B：forced-action 改变证据通道；修复 chooser 改善期望学习/后续行为，
  与 no-information / future-stop 对照一起解释。
- 支持“二者各自有缺口且相互依赖”：前两项和对应两条干预路径均得到证据。
  只观察到其中一项就收窄 claim。交互项单独作为非加性证据，不作为必过门槛。

不能把普通 95% 区间用于任意多指标挑选显著性；这轮报告为预先指定的少量主读数
和探索性对照。正式投稿前应根据 pilot 效应规模做样本量设计、多模型复现以及
结构不同的测试环境。当前只有一个 LLM ego 与受控伙伴，不等于全体 LLM 的 self-play。

## 8. 远端运行与产物

复用 repo 的 vLLM server（Qwen3-4B-Instruct-2507），不需要在本地连接用户服务器。
默认 base URL 为 `http://localhost:8000/v1`，可通过环境变量覆盖。

```bash
# 先运行已有服务脚本；服务已启动则跳过。
VLLM_MODEL=/path/to/Qwen3-4B-Instruct-2507 \
VLLM_SERVED_MODEL_NAME=Qwen/Qwen3-4B-Instruct-2507 \
VLLM_MAX_MODEL_LEN=16384 \
bash examples/item_game/run_item_game_vllm_028_server.sh

# 跑完整诊断。
bash examples/benac_p/run_full_diagnose.sh

# 增加 confirmation/discovery game 数，不改变各层生成/筛选规则。
BENAC_DIAGNOSE_GAMES=100 BENAC_DIAGNOSE_WORKERS=8 \
bash examples/benac_p/run_full_diagnose.sh

# CPU-only 准备题目、标签与证书，无模型调用。
bash examples/benac_p/run_full_diagnose.sh --export-only

# 指向同一输出目录恢复；模型、seed、数量、token 与并发配置保持一致。
BENAC_DIAGNOSE_OUTPUT_DIR=runs/benac_full_diagnose/具体目录 \
bash examples/benac_p/run_full_diagnose.sh --resume
```

默认 4 路并发，模型 temperature=0，每次最多 2048 output tokens。任务数及输入 hash
记录在 manifest；静态任务约 2,000，模型首步产生的动态任务另有最多约 500。
精确数量取决于最优首步是 PASS、OFFER 还是 MENU。所有参考计算在 CPU 上完成。

输出：`manifest.json`、`tasks.json`、`dynamic_tasks.json`、`oracle_labels.json`、
`certificates.json`、`answers.json`、`scores.json`、`summary.json`、`report.md`、`run.log`。
回答逐批原子保存；传输错误停止并可恢复；格式错误单独记录，依赖它的 model-belief
planning 标为 blocked_parent，绝不偷偷替换成 oracle。所有 labels 与 model-visible
输入分离。首次 export-only 不生成模型结论。

## 9. 与过往方法的关系

TERMS-Bench 的受控 counterpart、posterior intervention 和参考策略差距为诊断
提供了方法参考；本协议进一步使用同一显式 belief 接口的完整四格对照与当前
negotiation action 对未来 evidence 的干预。不能把 posterior injection 本身作为创新。
原文：[TERMS-Bench](https://arxiv.org/html/2605.13909v1)。

Riemer et al. 的 agent adaptation 工作强调从对他人的显式判断到实际行为使用之间
的区别；因此本协议同时测 belief 报告、给定 belief 的 planning、以及行为干预，
不只根据问答准确率声称具备战略交互能力。
原文：[Can Large Language Models Adapt to Other Agents In-Context?](https://arxiv.org/html/2412.19726v1)。
