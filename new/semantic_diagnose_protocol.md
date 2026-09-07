# BENAC-P 语义诊断：可执行协议

状态：`semantic-interaction-loop-v1` 已实现。旧 stochastic pilot 单独保留，不合并结果。
入口：`bash examples/benac_p/run_full_diagnose.sh`。

## 研究范围

保持 B（伙伴理解）与 P（伙伴条件化交互规划）两个能力。模型输出语义判断与行动；不输出概率、utility 数字、Q、ranking 或 plan variable。后台精确计算只用于认证与评分。

这是 **3-player、三次 proposer turn、公开阶段行动集合的条件诊断子游戏**。不是完整 unrestricted BENAC 的随机总体，也不是长 horizon 或跨环境 transfer 证据。实例共享一个交互结构，改变目标名称、偏好到路线的映射、行动顺序、收益相关目标数及成本。Confirmation 是未见参数实例，不是未见结构。

每个 matched bundle 包含三个条件：偏好未知且影响路线、偏好已知、偏好未知但不影响路线。默认 12 bundles = 36 games，6 discovery bundles + 6 confirmation bundles。每个条件的 confirmation 只有 6 个独立 bundle，置信区间相应较宽；不能把三种条件当作三倍独立样本。

## 游戏与理性伙伴

三个玩家：P0 为 ego，P1 提供初步评估及路线许可，P2 审批最终路线。

1. P0 向 P1 提出准备、单项评估、双选项评估 menu、同时锁定路线的评估 menu、准备 menu，或 PASS。评估一旦接受，会形成不可撤销的行政成本；准备一旦接受，会完成额外 WANT goals。
2. P0 必须提交一个路线提议或路线 menu。若初步 menu 已锁定路线，就只剩该路线的许可提议。P1 只关心共同的许可目标，不区分路线。接受立即锁定唯一的路线与许可。P1 拒绝则项目终止。
3. 按公开协议，自动向 P2 提议批准已经锁定的路线；不能再换路线。P2 响应后终止。项目里程碑要求三方 commitment 同时成立。

所有提议都由原 `GameState.validate_offer/resolve_offer` 验证和执行，仍是普通合法 BENAC joint commitments。阶段行动集合是公开的实验限制，不能把在本协议下最优描述成全 BENAC action space 下最优。正常运行中第 2 步 P1 接受许可严格优于拒绝。

P1 对第一个评估的偏好为 WANT / NEUTRAL / AVOID；第二个评估分别相反 / 同为 NEUTRAL。公开的三种联合配置把这个偏好与 P2 对路线审批的偏好联系起来。因此观察 P1 可以帮助判断 P2，保留跨伙伴依赖。在“未知但无关”条件中 P2 支持每条路线，不需要推断 P1 来选择路线。

**Partner 行为没有随机性。** 各 partner 只使用公开 commitment 和自身偏好。并列最优优先 REJECT，若最佳接受选项并列则选 menu 中较早的选项。后台枚举所有允许的后续 ego 行动，验证每个候选响应的自身终局收益不依赖后续 ego 路线选择，并验证实际响应是这些终局收益的 argmax。若认证失败，拒绝该实例；不会回退到 heuristic 或 stochastic partner。实现中可用当前收益排序，是因为已证明剩余自身收益为相同常数，而不是把 myopic policy 冒充长期理性。

隐藏偏好仍然未知。三种配置事前等频，这是明确写在题面的信息；确定响应排除不一致配置后，剩余配置仍等频。后台跨配置完整枚举并加权，这不是 partner 随机行动，也不需要模型估计未提供的概率。

## 语义标签与输出

B 使用 `SUBMIT_JUDGMENT(possible_preferences=["want", "neutral", "avoid"])`，返回非空的剩余可能集合。这里每个取值唯一对应题面给出的完整联合配置，因而保留 P1/P2 的相关性；不是任意独立 marginal 的拼接。

- 评估 menu 的 CHOOSE_1 / CHOOSE_2 / REJECT 分别支持 WANT / AVOID / NEUTRAL。
- 单独提供第一个评估被拒绝时，NEUTRAL 与 AVOID 仍无法区分。
- 准备被接受或 PASS 不提供偏好证据，回答仍不确定可以完全正确。

标签只从初始公开信息与实际响应的一致性得到，不直接揭示 sampled hidden truth。B 指标包括集合 exact、错误排除仍可能偏好的比例、未排除已被证据否定偏好的比例、不确定性状态正确率；另提供保持初始判断的基线。

P 使用 `SUBMIT_ACTION(action_index=...)`，索引只对应题面列出的自然语言合法提议。多个最优动作全部接受。根节点 reference 完整考虑响应、更新、重规划后的终局 utility；不优化 MI。

统一提示保留 `Briefly reason about the task before submitting your answer.`。默认 `balanced` profile 对判断题提示约 120 words、规划题约 240 words；这是软目标，不是句数限制、最低长度或评分门槛。不要求固定推理步骤，并提示结论已确定或动作并列最优时及时提交。默认总输出仍为 1024 tokens，包含文本和工具调用。每次只允许一次 native auto tool call。保存 reasoning、tool calls、usage、finish_reason；截断与格式错误单列，不当作策略 PASS。

## 四块实验与完整轨迹

- **B**：在同一 interaction 前、后分别判断，后者只包含真实产生的响应。没有证据时不要求变得更确定。
- **P**：提供正确、完整的语义伙伴判断，根节点检验信息获取规划，后续节点检验依据判断选择路线。已知条件和无关条件作为对照。
- **B→P**：相同 planner、新上下文、同格式判断，分别注入 model/oracle 判断。P 不继承 B history 或 scratchpad。
- **P→B**：固定正确初始理解，比较 model/oracle 首步，枚举所有可发生响应；同一 updater 更新判断，再测 reference 与 model continuation。
- **End-to-end**：初始 model B → model P → deterministic response → model B → model P → P2 response → terminal outcome。枚举每个隐藏配置，导出完整 trajectory。这是上述受控、分开调用接口的闭环，不是任意部署架构的表现。

Planner 使用经验证足以比较剩余路线的状态投影：对没有预先锁路线的分支，先前评估的具体标记不会影响后续路线的可用性和相对价值，其既成收益只贡献相同的常数；若 menu 已锁路线，则必须保留真实的绑定路线和相应受限行动集合。因此不把标记或旧 action/history 重新送给 P，让 P 绕过被干预的语义判断。后台仍用真实 binding state 计算实际 utility，不删除成本。根节点 P 则知道所有可选行动的物理后果、成本与未来机会。

第一张四格表 R 是 regret，越低越好；第一个字母表示 judgment，第二个表示 planner：OO、OL、LO、LL。B repair = R_LL − R_OL。主表在 reference 首步后的分支上加权；根节点的 oracle-judgment planning regret 单独报告。

第二张四格表 J 是 utility，越高越好；第一个字母是当前 chooser，第二个是 updater；后续 planner 固定 reference。

- chooser repair = J_OL − J_LL；
- updater repair on model action = J_LO − J_LL；
- updater repair on oracle action = J_OO − J_OL。

同时保存每种 action 的剩余可能数、oracle entropy/MI、模型语义判断读数以及实际 continuation utility。只有 utility 差异，不能声称是纯信息中介效应。证书另外提供 **同一个 menu、相同真实分支状态、更新 vs 保持初始判断** 的参考收益差，认证信息确实具有后续决策价值。

相同 action/response 的调用在不同实验 arm 间复用，避免重复调用引入无关差异。无效判断阻断依赖的 P；分支不完整时整 game 对相应指标排除，绝不丢掉失败分支后重新归一化。两张表的完整配对覆盖与协议覆盖单独报告。CI 对每个条件的独立 bundle 做 bootstrap；三个条件的共同成功率也按 bundle 汇总。

## 运行与复现

```bash
# 远端模型：复用已有 vLLM 0.28 + hermes 配置和服务环境变量。
bash examples/benac_p/run_full_diagnose.sh

# 只认证并导出题目，不调用服务。
bash examples/benac_p/run_full_diagnose.sh --export-only

# 后台 oracle 自检；不是 LLM 结果。
bash examples/benac_p/run_full_diagnose.sh --oracle-check

# 指定一个已有目录继续运行（必须是新版、同 seed / model / prompt / budget）。
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_full_diagnose.sh --resume

# 不调用模型，从保存的回答重建动态分支并评分。
BENAC_DIAGNOSE_OUTPUT_DIR=/path/to/run bash examples/benac_p/run_full_diagnose.sh --score-only
```

默认 `Qwen/Qwen3-4B-Instruct-2507`，`http://localhost:8000/v1`，4 workers，seed 20000。
继续使用 `BENAC_P_VLLM_BASE_URL` / `VLLM_BASE_URL`、`VLLM_MODEL` / `VLLM_SERVED_MODEL_NAME`、`BENAC_P_VLLM_API_KEY`、`BENAC_DIAGNOSE_MAX_TOKENS`、`BENAC_DIAGNOSE_WORKERS`、`BENAC_DIAGNOSE_SEED`、`BENAC_DIAGNOSE_GAMES`（这里表示 matched bundles，须为不小于 2 的偶数）。

默认 288 静态调用，至多 504 个额外调用（通常因分支复用明显更少）。新运行自动使用新的时间戳目录。不可在旧 stochastic pilot 的输出目录上 resume。`--response-protocol json_action` 是单独目录中的无推理结构化输出对照。

关键输出：

- `manifest.json`：任务、prompt、tool schema、模型、参数指纹。
- `tasks.json` / `dynamic_tasks.json`：实际模型输入与依赖；工具 schema 单独导出。
- `oracle_labels.json` / `certificates.json`：后台标签、终局收益及理性/信息价值证书。
- `answers.json`：原始 reasoning、工具输出、状态与实际请求 fingerprint。
- `interventions.json`：reference / model / end-to-end 首步和全部响应分支。
- `scores.json` / `summary.json` / `report.md`：四块指标、两张表、完整性和 CI。
- `rollouts.json`：真实 commitment transition 与各 hidden configuration 下的完整模型轨迹。
- `protocol_summary.json`：调用合法性、总 completion tokens mean/P95、reasoning 词数和截断。

旧版仅通过 `run_stochastic_diagnose.sh` 或 `python -m benac_p.diagnose_suite` 使用。旧概率诊断与新版语义诊断不直接合并比较。


## Reasoning budget calibration

`run_reasoning_calibration.sh --source-run runs/benac_semantic_diagnose/retry-826767`
使用同一批 discovery 输入比较 open（原运行缓存）、compact（80 words）、balanced（B 120 / P 240 words）。默认选择 72 题，新增 144 次请求，hard cap 三组保持一致。按条件、root/downstream、B/P-oracle/P-model 分层抽样；不按旧回答是否失败来挑题，不使用 confirmation。

P-model 的输入 judgment 固定为原记录，不把新 profile 的 B 输出注入 P；评分标签按该实际输入 judgment 重算。三组因此比较同一问题。失败或截断在“valid-and-correct”成功率中不算成功，不通过只看完成样本来隐藏失败；真实 regret 仍只对合法完成回答报告。输出各 profile 的 mean/P95 completion tokens、B/P 成功率、截断率，以及按 bundle bootstrap 的配对差异。

建议规则仅为开发阶段 heuristic：格式完成率至少 98%，B/P 的 valid-and-correct 成功率分别距观察到的最好值不超过 5 个百分点，再选择平均 tokens 最低者。样本小，不是正式 noninferiority 证明。如果没有 profile 达标，不给出推荐。模型权重和 serving 设置需与缓存 baseline 一致；保存原始历史运行，不覆盖它。

## Bounded final submission after calibration 826995

The 72-task discovery calibration favors balanced as the candidate: 94.4% valid,
33.3% B valid+exact, 50.0% P valid+optimal, mean 231 completion tokens. It does not
meet the 98% coverage criterion yet. All four balanced truncations are downstream
planning questions in unknown_relevant. The traces repeat route/menu comparisons;
one explicitly selects action 4 and keeps writing, while other traces also ignore
supplied judgment constraints or conflate P1 and P2 preferences. Truncation is not
sufficient evidence that the underlying reasoning was correct.

The optional `--finalization-tokens 128` keeps the same balanced prompt and 1024-token
initial cap. Only a length-stopped native-tool response receives one extra request:
original question + original ordinary-text reasoning + a short submit-now instruction,
with the submission function explicitly selected through `tool_choice`. Incomplete
tool-call fragments are not replayed. No labels, corrective hints, or new evidence
enter that request. All nontruncated answers remain unchanged; no strategic-error
retry is allowed. A failed finalization is retained and not automatically retried,
including on resume. The option defaults to disabled until serving compatibility
and completion recovery are checked on the discovery sample.

Run the small check on the server using the uploaded calibration directory:

```bash
bash examples/benac_p/run_finalization_calibration.sh \
  --source-run runs/benac_reasoning_calibration/826995
```

This reuses all 72 balanced first passes and sends only four new requests. Each adds
at most 128 completion tokens (at most 512 additional across this sample, or 7.1 per
original task). The original question and reasoning incur extra prompt-token cost;
that cost is also recorded. Maximum completion budget per recovered task is 1152,
not 1024. The named-function request has local mocked-HTTP coverage but still needs
verification on the actual vLLM/Hermes server.

`comparison.json` and `report.md` compare original balanced and balanced+finalization
using all 72 questions; `answers.json` preserves both raw attempts. Metrics distinguish
first-pass truncation, finalization attempts, protocol-valid finalizations, semantic
validity/correctness, and total tokens per task. Request means and per-task total means
are separate. Missing usage after transport errors is counted; observed token totals
cannot include unreported server cost. Completion recovery alone is not a demonstrated
improvement in B/P computation.

After validating that protocol, run the complete B / P / B→P / P→B suite in a fresh
directory, freezing the same setting for every condition:

```bash
bash examples/benac_p/run_full_diagnose.sh \
  --reasoning-profile balanced --finalization-tokens 128
```

The finalization policy and budget enter the manifest, preventing resuming/mixing a
run with a different policy. Finalization supports both semantic judgment and action
submissions. Main-suite strategic scoring still validates the submitted schema and
scores the actual selected action; no missing answer becomes PASS.

## Frozen episode-prior clarification (semantic-interaction-loop-v2)

B now uses clear-auto wording: the full configuration table describes the population;
`initially_possible_preferences` restricts the current episode, configurations outside
it are already ruled out, and an empty history adds no evidence. The output remains
the supported preference subset. There is no answer clipping or posterior supplied
by this clarification. P inputs, game generation, oracle and scoring are unchanged.

The standard `run_full_diagnose.sh` now selects balanced reasoning, a 1024-token initial
cap, and one 128-token finalization if truncated. It first runs four empty-history B
checks using the same game description/schema/question: WANT only, NEUTRAL only,
AVOID only, and all three possibilities. All four must be semantically exact for the
script to continue automatically into the complete diagnosis. Failed checks are saved
and not retried on resume; they do not trigger prompt selection or answer repair.
Preflight tasks are separate from diagnostic statistics and have separate token usage
in `belief_preflight_summary.json`. Their total extra cost is four initial requests,
plus at most four bounded finalizations. The protocol budget settings and prompt version
are frozen in the manifest; use a fresh output directory. Direct Python CLI defaults
remain configurable; the shell wrapper supplies the new standard settings.

```bash
bash examples/benac_p/run_full_diagnose.sh
```

Inspect `belief_preflight_answers.json` if the script exits with a failed check. A
synthetic oracle check validates plumbing, not actual model performance. Historical
calibration/audit helpers reconstruct their archived question wording for matched
replays rather than silently replacing it with the new prompt.
