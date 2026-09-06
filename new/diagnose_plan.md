# Diagnose 阶段：参考 TERMS-Bench，服务于能力后训练与迁移

更新：2026-09-06。状态：grounding、controlled partner、条件先验、小规模 exact
Bayesian filter 与短 horizon belief-conditioned planner 已实现并完成本地测试；
已验证人工构造的 belief-sensitive 和第三方依赖实例，尚未运行 LLM 诊断。

## 当前进展

- 已加入 `state-facts-v1`：当前 goal 状态、缺失 commitments、自身快照效用，以及
  pending offer 的 hypothetical accepted state。测试与真实 engine transition 对照。
- 已加入 `SoftProgressPolicy`（`soft-progress-v1`）与独立的 proposal / response
  distribution、probability 查询 API。采样使用同一分布，查询不消耗随机数。
- policy 只使用自身 preference 与公共 commitments / schedule / legal offers。
  已测试其他玩家私有 preference 改变不影响其概率；full debug view 也不被用于决策。
- CLI 新增 `--self-play controlled`，JSON 输出包含公开 policy specification 与复现 seeds。
- 首版行为启发式：`Phi(C)=sum_g V_g*(S_g+w*(1-S_g)*completed_fraction_g)`；
  OFFER/ACCEPT 按假设接受后的 `Phi` 增量评分，PASS/REJECT 为零分。
  默认 `w=0.5`、softmax temperature `0.5`、uniform mixture `0.02`；最后一个
  scheduled turn 将 `w` 置零。它不推断接受概率，不是最优或长期理性 partner。
- 部分进度只用于 policy score，环境仍是 ALL_OF、terminal-only reward。
  手工样例已验证 preference 可区分性与无信息对照；尚未证明批量实例的决策价值。
- 已加入 `ConditionalPreferencePrior`：枚举符合 v0 两条 preference constraints
  的 joint support，并条件化于 ego 自身偏好；公开 preference sampling 参数由调用方
  传入，不从真实 partner preference、seed 或 evaluator metadata 推断。
- 已加入 `BeliefState` 与 `ExactBayesFilter`：log-space 概率更新、joint serialization、
  marginals、entropy，以及逐 proposal/response 的证据日志。
  `synchronize(observation)` 消费完整 history 的新增前缀与 pending offer，重复同步
  幂等；streaming API 支持未来 planner 按 action/observation 展开分支。
- ego 的 PASS/OFFER/response 均作为 intervention，likelihood 只包含非 ego 行为。
  private/full debug view 的真实其他偏好不参与计算；filter 内部使用 dummy preference
  的公共 shadow engine 验证 history / transition。非法 fallback history 明确拒绝。
- 支持已知 `SoftProgressPolicy` kernel，可按 partner 设置固定公开参数。
  首版默认上限为 100,000 个未过滤 joint candidates；8 goals、两个未知 partner 的
  43,046,721 candidates 会明确报错，不自动切换近似。
- 独立全矩阵 prior 枚举、直接 joint likelihood 乘积、pending offer 去重、ego action
  排除与 streaming/replay 对照均已测试。`belief_demo` 提供可复现的 3-goal 示例。
- exact 仅指明确指定的有限生成分布与已知 policy 下的枚举推断（浮点精度）。
  额外基于隐藏状态/solver 的数据筛选、未知 policy 和未来的 policy shift 尚不覆盖。
- 已加入 `BayesPlanner.solve(observation, belief)`：ego 节点取最大值，partner 节点
  按固定 kernel 取期望，并用与 filter 共用的 `condition_belief` 更新未来 posterior。
  只优化自身实际 terminal ALL_OF utility；没有 partial-progress reward 或叶节点启发式。
- planner 不读取 raw history、真实 partner preference、seed 或 prior；pending offer
  假定已被传入 belief 吸收，不在 root 重复更新。返回当前 ego 的全部合法 action values、
  最优动作集合与 regret。partner phase 可以求 value，但不替 partner 取最大值。
- 每次 solve 新建缓存，缓存键包含 turn、commitments、pending offer 与完整 log belief。
  默认最多 4 个 remaining proposer turns、4096 hypotheses、50,000 个展开节点；
  超限明确报错，不把截断/部分搜索称为 exact。只有完整到达真实终局的值才返回。
- 独立 contingent-policy / alpha-vector 枚举验证多步结果，解析 acceptance 概率验证
  最后一轮 Q；测试覆盖 hidden-state 信息泄漏、重复求解、pending response 与预算失败。
- [planner_step3.json](artifacts/planner_step3.json) 保存两类可复核实例。两段合法 history
  到达相同 C/turn/phase 后分别选择 P1 与 P2，交叉使用另一动作的 regret 约为
  0.20419 与 0.19188。另一个三方 goal 实例中，所有单次 accepted-state snapshot
  utility 都为零，但为后续 P2 行动做前置承诺的 value 为 0.57349，PASS value 为零。
  前一组是当前 belief 的决策价值，后一组是已知偏好下的长期依赖；尚未证明主动探测
  信息的最优性，也不代表随机实例总体或 LLM 表现。
- 小规模资源检查：3 players、每人 1 commitment、2 goals、24 hypotheses 的一个
  固定实例，2/3/4 remaining turns 分别展开 164/1238/9225 节点。本机一次运行约为
  0.03/0.17/0.89 秒，不作为大配置可扩展性承诺。
- 下一步：扩充带负对照的 decision fixtures，接入同信息条件的 LLM belief/planner
  诊断矩阵并运行训练前 pilot；混合实验需明确注入公开 policy specification。

## 1. 主线与范围

研究主线保持 `Diagnose → Post-train → Solve → Transfer`。
研究假设是 LLM 尚不能稳定地将持续交互的其他 agent 的激励、信息和未来行动纳入自身计划。
诊断围绕两个计算瓶颈组织：

1. Partner belief / belief updating。
2. Partner-conditioned planning；prediction、lookahead、counterfactual branch comparison 属于这一项。

TERMS-Bench 作为通用谈判诊断的方法参照，并在实现可获取时作为外部评估。
BENAC-P 保留为主要训练候选环境，重点验证 multi-party、cross-agent dependency 与不可逆承诺的长期后果。
诊断不以建立另一套 generic negotiation benchmark 为交付目标。

## 2. 已核查的来源与边界

- [TERMS 论文](https://arxiv.org/html/2605.13909v1)：附录 C 描述受控 counterpart；D 描述离散化 Bayesian planning reference；E 描述 posterior / revealed-type interventions；F 描述分项指标；I.2 区分 kernel、family 与 latent-type 信息披露。
- 其 posterior intervention 给 LLM 的是低维摘要，并非完整 joint belief。其标准 agent 不获知完整 simulator policy。不能直接等同于我们计划中的同信息模块替换实验。
- [官方网站](https://terms-bench.github.io/)还包含跨多次交易的 bankroll 模式。因此不能把“TERMS 没有长期状态”作为 BENAC-P 的区别。
- [官方公开仓库](https://github.com/Terms-bench/terms-bench.github.io)当前核查到的是网站、榜单与展示材料；尚未找到完整可运行 harness。方法参考已可开展；正式复用、版本一致性和运行成本尚未验证。

以下均为本项目的实施设计，不声称是 TERMS 原有实验。

## 3. 第一批诊断要回答的问题

- 在规则与 state grounding 正确时，模型的 belief 是否随有信息量的行为更新？
- 纠正当前 belief 后，当前 action 的长期价值损失是否下降？
- 真实 preference 已知时，模型是否仍忽略第三方或不可逆承诺的后果？
- 后两种失误是否会随跨玩家依赖增强、剩余 horizon 增长而增加？

诊断不预设所有模型都失败，也不要求每个样本都需要更新或改变行动。

## 4. 两条工作线

### A. 外部通用诊断

先核查 TERMS harness 的可获取性、版本、协议、指标与 oracle 实现。
若获得可运行版本，保留原协议，运行目标训练模型的训练前基线。
若暂时无法获得，继续 B，不把自写 simulator 标注为官方 TERMS reproduction。
不自动提交榜单、发送 API key 或请求作者运行收费评估。

TERMS evaluation scenarios 不进入 BENAC-P 训练。
若使用 TERMS development 数据调方法，应另留未用于调参的最终测试集；反复查看的评估集不能再称 untouched transfer set。

### B. BENAC-P 最小针对性诊断

先完成 grounding facts、受控 partner、exact posterior、短 horizon reference 与固定决策点评估。
不以默认 8-goal 完整 Bayes-adaptive search 为起步依赖。
先使用明确公开的小 latent support，或缩小 goals / 隐藏维度；记录与默认 generator 的区别。

## 5. 核心数据与信息 contract

每个 decision record 至少包含：

```text
spec_id / scenario_id / seed / ego_id
decision_id / turn / phase / schedule / remaining_horizon
current_commitments / pending_offer / legal_actions
own_preferences / public_history_prefix
partner_policy_version / prior_version / information_condition
oracle_posterior / llm_belief / belief_representation
selected_action / reference_action_values / regret
protocol_validity / retry / truncation / model_and_prompt_version
```

隐藏 preference、完整 posterior 和 action values 的记录权限与 agent 输入严格分离。
reference action values 仅用于评分，除非明确标记为额外 action-value disclosure 条件。

Controlled partner：

- 固定、可计算 likelihood；只读取自身合法信息。
- 明确定义 proposer 与 responder 的规则、随机性与 tie handling。
- 首版可以是依赖公共 state 与自身 preference 的简单 policy。
- 若引入历史反应，显式记录影响未来行为的 history features；不能只以 commitments 作为充分状态。
- 对每个规则检查 preference 可区分性和决策相关性。softmax 本身不是完整 policy 定义。

Belief：

- prior 条件化于 ego 信息与公开生成/筛选协议。
- update 消费每个新观察一次；ego 自身动作作为干预条件，不额外作为关于 partner latent 的似然因子。
- partner 发出的 pending offer 在 ego response 前更新 belief。
- canonical 表示允许 joint distribution。摘要/边缘分布条件单独标记。
- 比较 incremental update 与 full-history re-inference。

Planner：

- 主模块诊断中，LLM 和 oracle 都获知同一 controlled-policy specification。
- 输入为当前充分公共状态、ego preference、belief 和 policy specification。
- 新建无旧对话状态的调用，避免通过 history 或隐藏会话旁路读取 belief evidence。
- 若研究 policy-unknown 情况，作为独立泛化条件；不将缺少机制知识造成的 gap 全归因于 planning。

## 6. 最小实验矩阵

先构建以下条件，共用固定决策点集合：

| 条件 | Belief / 信息 | Planner | 用途 |
|---|---|---|---|
| 原单体 agent | 标准合法 history | 原 LLM policy | 保留当前 agent 基线 |
| 模块化基线 | LLM belief | LLM | 测结构化接口下表现 |
| Posterior intervention | Exact posterior | LLM | 纠正当前 belief 后的剩余损失 |
| Belief decision value | LLM belief | Bayes reference | 当前推断信息的决策价值 |
| Bayesian reference | Exact posterior | Bayes reference | 同信息条件的规范参照 |
| Revealed state | 真实 preference | LLM | 消除 latent uncertainty 后的表现 |
| Revealed-state reference | 真实 preference | 固定 partner 下的最优应对 | 为 revealed-state LLM 提供同信息参照 |

另加 prior-only 对照判断 evidence 是否提供决策价值。
小规模先验证输入与 reference，随后运行模型。

固定决策点评估中，对 partial-information 条件选出的动作统一用 `Q*(x, b*, a)` 评分：

```text
regret = max_a Q*(x, b*, a) - Q*(x, b*, selected_action)
```

该 Q 假定当前动作以后 ego 使用正确 Bayesian continuation。
LLM-belief reference 在当前输入 belief 下选动作，但其搜索不模拟未来 LLM updater 的错误。
因此这是当前决策诊断，不宣称是该 updater 下的最优闭环控制器。

Revealed-state 条件使用相同真实状态信息下的 reference；不与仍有隐藏状态不确定性的 oracle 混称纯 planning gap。
现有 PerfectInfoSolver 假设所有玩家按完整信息 backward induction，不能直接充当固定 stochastic partners 下的 reference。

## 7. BENAC-P 必须补充的针对性实例

1. Belief control：无信息、信息有用但不改变最优动作、信息改变最优动作。
2. Third-party dependency：与 P1 达成承诺的价值依赖 P2 后续可采取的行动。
3. Irreversible consequence：某次当前可接受的承诺降低后续最优可达价值。
4. Long-horizon comparison：短视与长期 reference 的最优动作不同。

每例必须由 reference 验证 action gap，包含无需改变行动的负对照。
以合法 history 匹配当前 commitments、turn、phase、pending offer 与剩余 horizon。
若这些构造无法产生稳定的价值差，先改实例或 controlled policy，不进入训练。

“多方”不能仅靠玩家数量证明：应检查去掉第三方依赖后，原 action-value 差异是否消失或明显减弱。
关于不可逆性和 horizon 的消融需分别记录规则/任务难度变化，不把未匹配的游戏差异当纯因果效应。

## 8. 指标与归因

- Grounding / execution：state facts、合法性、retry 和截断。
- Belief：与 exact posterior 的差异、proper scores、posterior predictive quality，以及 belief 的决策价值。
- Planning：相同信息下的逐步 regret、最优动作集合命中、按依赖与 horizon 分层结果。
- Episode：terminal utility、PASS / ACCEPT / REJECT 分布；作为闭环效果补充。

不得要求每条 episode 的 belief error 单调下降；随机 evidence 可以暂时误导。
干预收益可正可负；小 posterior-injection gain 不等于原 belief 已正确。
完整 rollout 改变所访问的 history，因此其收益差不能直接解释成固定状态的纯模块误差。
使用按 game / scenario 配对、聚类的置信区间；不要把一局中的多个 turn 当独立样本。

## 9. 实施顺序与退出条件

1. 验证 grounding facts 与 controlled policy 的观察权限和 likelihood。
2. 在小 latent support 上验证 prior、posterior 和短 horizon reference；记录 runtime、内存和数值容差。
3. 保存可手工复核的合法 decision fixtures，验证四类实例是否成立。
4. 跑目标训练模型的训练前矩阵；预算允许时增加一个更强模型作参照。
5. 输出 failure profile，并明确第一轮 post-training 针对 belief、planning 还是两者。

退出本阶段的条件是：至少一类可重复、排除了主要 grounding confound 的任务相关失败，具有可靠的 reference、未见测试实例与可用训练信号。
若目标模型在小任务已无明显缺口，提高依赖难度或缩小能力缺陷 claim。
不要求先完成大规模 TERMS 复现、完整 BENAC-P exact solver 或新通用 benchmark，才开始训练 pilot。

## 10. Step 4：binding menu 与双向依赖诊断（已实现）

主线仍为 Diagnose → Post-train → Solve → Transfer，计算瓶颈仍只有 belief/updating
和 partner-conditioned planning。双向依赖需表述为：belief 改变当前计划；planning
通过选择 interaction action 改变未来 evidence 的分布，随后影响 belief。不能把环境
中存在这个闭环，直接写成已经证明 LLM 两种 weakness 存在因果依赖。

`GameSpec.menu_enabled=True` 开启扩展。保留 PASS / 单 OFFER 作为同一实验中的
基线，增加 MENU：同一 partner、两个不同且各自合法的 offer；CHOOSE_1 /
CHOOSE_2 / REJECT；仅选中 option 立即 binding，整个响应只推进一个 proposer turn。
完整 menu 与 choice 进入公开 transcript。CLI 为 `--menu`。

受控响应使用三个结果的共同 softmax（REJECT=0，各 CHOOSE 为对应 Phi gain），
proposer 的 menu score 明确为 max option Phi gain 的 Level-0 heuristic，非理性
oracle。ExactBayesFilter、BayesPlanner、native tools、runner 都支持扩展。模型自己
给出的 menu 是 intervention，不作为 partner preference 的 likelihood evidence。

`benac_p.menu_diagnose` 提供一个由搜索选出的三人、两次 ego proposer turn、五目标、
公开两类型 prior 的最小实例。该 prior 明确不同于默认 IID 条件生成 prior，并通过
`FinitePreferencePrior` 给 filter。P2 类型已知，P1 类型未知并跨轮持续。

正式 expectimax 数值与逐 response 分支计算相符：

- 两个最优 menu option 的 ego 即时 utility 均为 1。
- 自适应最优首步为 MENU，期望终局 utility 1.673071295。
- 冻结初始 belief 的 continuation rule 下，最优首步为单 OFFER。
- 该单 OFFER 按正确 Bayesian continuation 估值，相对最优 menu 的 regret 为 0.161470365。
- 同一个最优 menu，adaptive vs frozen continuation 的 utility 差为 0.166811714。
- CHOOSE_1 后 P1 type-A posterior 为 0.822577633；同一实际 commitment state 下，
  posterior-driven continuation 选择 P2，frozen-prior continuation 选择 P1。
- 已知类型负对照：所有首步 action 的 adaptive/frozen value 差为 0。

冻结策略定义：在实际后续 state 上，使用初始 prior 选择最后一轮动作；然后在
真实 posterior 下评估该动作。没有重采样 latent type，也没有把冻结预测分布
当成真实环境。物理状态仍会因 menu outcome 改变，因此这是指定策略对照，不是
纯信息因果效应。P2 在这里提供替代 consent；尚未证明不可替代的长程第三方依赖。

远端入口：`bash examples/benac_p/run_menu_diagnose.sh`，默认
`Qwen/Qwen3-4B-Instruct-2507`，沿用 ItemGame vLLM HTTP server script。用户在
remote server 运行，本地只准备与验证代码。`--export-only` 无需推理服务。

输出 11 个 fixed-decision probes：root 的 history / oracle-belief planning；三种
response 各自的 belief estimation、history planning、oracle-belief planning。
模型 belief + oracle planner 在本地评分。主指标为 posterior TV、平方误差、
action regret、oracle-planner-with-model-belief regret、配对 posterior injection gain，
单独报告 invalid/missing。oracle Q labels 与模型输入分文件保存。

当前产物为 `new/artifacts/menu_step4/`，不是 LLM empirical results。
首轮 remote run 后立即按 grounding/format、belief、oracle-belief planning failure
区分下一轮工作；不要继续以扩展 benchmark 为前置条件拖延 pilot。
一个筛选出的实例不能支持 generalizable MAS weakness claim；正向结果后必须扩展
到结构不同的 held-out instances、无信息/信息无决策价值对照与更强的第三方依赖。

本步验证：BENAC-P 相关回归共 66 tests passed；完整 controlled menu episode 3 turns、0 invalid；远端脚本 export-only 与 saved-answer 评分通路均通过，oracle answers 为 11/11 valid、误差与 regret 为零。后者仅为评分器自检，未写作模型实验结果。

## 11. 完整诊断入口（2026-09-07）

`examples/benac_p/run_full_diagnose.sh` 现在组织完整实验，取代将 menu smoke pilot
当作主诊断的做法。完整协议见 `new/full_diagnose_protocol.md`：

- B-only 与 likelihood-table 算术对照；正确完整 belief 下的 P-only。
- 相同 state、action order、prompt 模板下的 B×P 四格；prior 注入与 grounding 对照。
- do(high/low menu)、单 offer、reference action 与模型实际选择 action，枚举所有
  response；chooser×updater 四格及 expected proper belief score。
- 终止 future objective 干预保留原 partner response kernel；known-type、uniform
  no-information、已知类型 long/short horizon 对照。
- 默认 24 个主实例分 discovery/confirmation，各含未筛选与预认证 dependency 层。
  预检发现纯随机 high-information menus 缺乏 decision-value headroom，故明确加入
  模型运行前的 oracle 筛选层；不把条件层失败率报告为未筛选总体失败率。
- 默认 1,945 静态任务 + 至多 486 动态任务，4 路 HTTP 并发，自动保存、续跑和报告。
- 置信区间以 game 为 cluster，缺失 response 不重新归一化；各种干预收益允许为负。

主结论仍待用户 remote server 的 Qwen3-4B-Instruct-2507 实测。本地 preflight 摘要
在 `new/artifacts/full_diagnose_preflight.json`。完整实验不保证发现 weakness，也不
将显式接口因果效应等同于内部神经模块分解。

完整诊断验证：75 个相关测试通过；包含显式接口无标签泄露、oracle 四格归零、可加性 belief 因果效应、独立 screening 与正式 planner 一致、mock HTTP 全流程与零追加请求续跑。默认 24-game export 已完整通过；12 个筛选实例来自 44 次 candidate 检查，最小 root-action regret 0.06692、最小 update gain 0.13136。无真实 LLM 结果被预填。
