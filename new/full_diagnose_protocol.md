# BENAC-P 冻结诊断协议：两个 primitive、四块实验、两张四格表

版本：interaction-loop-v2；输出协议 brief-reasoning-tools-v1。默认执行 core；辅助探针通过 `--extended` 开启。
主线保持 Diagnose → Post-train → Solve → Transfer。

## 1. 理论结构与主张边界

\[
B_t\overset{conditions}{\longrightarrow}P_t
\overset{controls\ interaction}{\longrightarrow}O_{t+1}
\overset{updates}{\longrightarrow}B_{t+1}\longrightarrow P_{t+1}.
\]

只有两个能力：

- **B — Partner Belief**：根据互动证据形成和更新对 partner 的 task-relevant model。
- **P — Partner-Conditioned Interaction Planning**：依据当前 belief 选择伙伴与行动，
  考虑伙伴响应、承诺后果、未来证据及其对后续决策的影响。

当前 BENAC 实例的 hidden variable 是偏好；此实验不声称已经覆盖所有 private
information、incentive 或任意 partner policy。Epistemic consequence 属于 P 的
computation；P→B 是两能力之间的 functional dependency，不是第三个 primitive。

Menu 让 action-dependent evidence 更直接可测。原版单 offer 的 ACCEPT/REJECT
也可以提供主动选择产生的证据，不能把该路径说成 menu 首次创造的能力。

## 2. 默认主实验：四块

| 块 | intervention / 输入 | 输出与判据 |
|---|---|---|
| B alone | 固定合法 history，只要求估 partner；给公开先验、type support 与已知伙伴策略 | posterior error，以及该误差在 reference planner 下的 task cost |
| P given B* | 正确完整 joint posterior，固定物理状态，不要求从 history 自行推断 | 基于实际 terminal utility 的 action regret |
| B→P | 相同 planner prompt，仅替换 model/oracle belief 数值 | 第一张四格表、paired belief-repair effect |
| P→B | 固定初始 state/belief，强制执行不同当前 action | 通道存在证书、当前选择的 utility regret、第二张四格表与下游 belief 读数 |

B-only 调用不提供行动选择题。给定 belief 的 planner 调用去掉 history 和 initial
prior，使用同一个模板与相同的 legal-action 顺序，只改变 current belief 数值。
模型 belief 从独立 B-only 调用获得；每次 planner 调用使用全新会话。
给定 oracle belief 后的剩余 regret 是本接口下的 P 缺口，不保证完全排除了算术或
状态理解问题。默认保留每个 game 一个很小的 grounding 检查，以及无信息/已知
类型对照；它们用于读数质量检查，不是另外的主研究问题。

## 3. 第一张四格表：B→P

统一符号：O=reference/oracle，L=LLM；**第一位 belief，第二位 planner**。
所有格子都在真实 posterior 下，用同一终局 Q 评价当前动作：

\[
R_{bp}=V^*(s,b^*)-Q^*(s,b^*,P_p(s,b_b)).
\]

| belief | reference planner P* | LLM planner P̂ |
|---|---|---|
| oracle B* | R_OO=0 | R_OL |
| model B̂ | R_LO | R_LL |

核心读取：

- R_LO：B error 的 task cost。
- R_OL：给定正确 belief 的 P deficit。
- R_LL−R_OL：修复 B 对同一个 LLM planner 的影响。

R 使用 regret，越小越好。不能把 R_LO 与 R_OL 自动相加解释全部 R_LL。
非加性交互可以作为 extended 读数，但不是依赖成立的必过门槛：belief 的因果
影响可以为正，而交互量恰好为零。修复收益允许为负，不据此改指标或丢弃样本。

## 4. 第二张四格表：P→B

这一块仅有三步。

### ① 证明当前 action 能改变 future evidence

在同一个 (s,b) 强制执行两个合法 menu，枚举所有 partner responses，计算
\(I(Z;Y\mid do(a_1))\) 与 \(I(Z;Y\mid do(a_2))\)。
两个 menu 在 partner、ego 即时 payoff 和新增 commitment 数量上匹配。这个
**CPU reference certificate** 只证明环境提供不同的证据通道，不产生额外的默认
LLM high/low-menu 测试，也不把 MI 变成 reward。

### ② 测 planner 是否做出好的 interaction choice

给 LLM 正确 current belief，选择完整合法 action set 中的行动。reference 使用：

\[
a^*=\arg\max_a\mathbb E[\text{terminal utility after observe-update-replan}].
\]

比较 model action 与 a* 的终局 utility，得到 root action regret。reference **不按
MI 最大化选行动**。低 MI action 可能最优，因为信息不值得其成本；低 MI 本身不能
作为 planning weakness 的证据。MI 更高也不意味着 terminal utility 更高。

### ③ 固定当前行动，比较后续更新与收益

分别执行 do(a_model) 与 do(a*)，枚举全部响应，用真实 response probability
加权。对每个 action 只保留三类核心读数：

1. Oracle posterior uncertainty（expected entropy；同时给 MI 描述通道）。
2. Model posterior error（expected excess Brier）。
3. 后续 reference planner 的 terminal utility。

每条 response 上，LLM updater 与 Bayes updater 接收同一份 evidence。Bayes
updater 在本地计算；model-action 的动态分支只需要调用 B，不重复整套 P 探针。

统一符号：**第一位 current chooser，第二位 updater**。后续 planner 始终固定为
reference，以免把另一轮 model-planning error 混入这张表。

\[
J_{cu}=\sum_y p(y\mid do(a_c))Q^*(s_y,b_y^*,P^*(s_y,b^u_y)).
\]

| current chooser | reference updater B* | LLM updater B̂ |
|---|---|---|
| reference planner P* | J_OO | J_OL |
| LLM planner P̂ | J_LO | J_LL |

J 使用 utility，越大越好：

- J_OO−J_LO：给定正确后续更新，当前 action selection 的 task cost，即 root regret。
- J_OO−J_OL、J_LO−J_LL：分别固定 reference/model 当前 action，更新缺口的 task cost。
- J_OL−J_LL：同一个 model updater 下，修复当前 chooser 的总收益。

这张表和 posterior 读数共同描述 P_t→O_{t+1}→B_{t+1} 的 functional dependency。
**不能仅凭 J 的差异就宣称损失完全由信息介导**：两个 action 也会改变 commitment
state。若报告“belief quality 更差并伴随下游 utility loss”，必须同时有相应读数
支持。只观察到 utility loss 时，结论应停留在 interaction planning 的总损失。
不要求主实验识别 pure information seeking 或模型内部神经机制。

## 5. 实例与 reference

默认 24 个主 game，discovery / confirmation 各 12 个；每部分交替包含：

- 6 个未筛选随机实例：3 players、行动数 (2,2,1)、4 个 ALL_OF goals，包含三方目标。
- 6 个预认证 task-relevant 实例：依赖 motif 加一个随机额外 goal，随机改变新增
  goal 的偏好、prior 与伙伴 temperature。运行模型前要求 root-action regret >0.005、
  最优首步下 update gain >0.02。最多筛选 256 个 candidate，失败明确停止。

后者是条件诊断分布，筛选次数、candidate seed、门槛和 reference 值公开。
两类实例分别报告，条件层失败率不能当作未筛选总体失败率。两层均使用公开有限
joint-type prior，hidden preference rows 跨互动持续；不是原始 IID 生成 prior。
筛选层共享设计 motif，confirmation 是未见实例，不是未见任务家族的 transfer。

另外保留 1 个旧正向 anchor、1 个 uniform no-information、1 个 known-type 对照，
不进入 confirmation。主子博弈是两个已排定的 ego proposer turn，做精确终局搜索。
这足以检验 observe-update-replan，不单独证明长程、多环境或全部 MAS 的缺陷。

首轮 oracle 预检中，纯随机 high-MI menu 的 task-value headroom 不足，故保留
上述显式 task-relevant 分层。筛选完全不使用模型表现，不保证模型一定失败。

## 6. 默认统计与报告

独立 B/P 与第一张表使用 reference optimal action 后的固定 history；第二张表
再加入模型实际选择的 action。所有响应枚举并按真实概率加权，不挑选成功轨迹。

- B 主误差：\(\|\hat b-b^*\|_2^2\)（posterior excess Brier），另记录 TV。
- P 主误差：实际 terminal utility 的 regret。
- 因果/依赖读数：两张四格表、成对修复差异、action-specific posterior uncertainty/error。
- 按 game 等权汇总；bootstrap 2,000 次抽整个 game，给出 95% interval。
- 不把多个 response 当独立样本；缺失分支不重新归一化成伪完整期望。
- 完整 oracle 通道/utility 读数不因 model updater 格式错误而消失；模型读数单独
  标明缺失。四格均值的有效覆盖可能不同，推断使用共同完整样本的 paired effects。

先看 validity、grounding、oracle-certified headroom，再解释 weakness 或修复收益。
默认每层只有 6 个 confirmation game，是 pilot 规模，不是 power 保证。需要更稳定
分层统计时增加 `--n-games`，而不是改变筛选门槛以挑选结果。
显式 posterior error 测量的是报告的 belief；接口干预测量 functional causal effect。
两项缺口与两条依赖路径必须分别有证据，不能从任一单项结果自动推出全部主张。

`report.md` 默认围绕四块实验和两张四格表组织，具体分支值在 `scores.json`，
区间和分层读数在 `summary.json`。不以 secondary metrics 堆砌主 claim。

## 7. Extended：需要定位原因时再开启

以下保留为 `--extended`，不属于默认主实验：数值 likelihood/Bayes arithmetic、
prior 注入、history-only planning、LLM high/low-menu 与 single-offer arms、
future-stop objective 干预、额外长短 horizon、非加性交互及 proper-score 等辅助汇总。

future-stop 保留原来的 partner response kernel，以免修改末轮 progress 权重带来
混淆。即使开启 extended，所有 action selection reference 仍按 terminal utility
优化，不能改成 MI 最优策略。

## 8. 运行

复用 repo 的 Qwen3-4B-Instruct-2507 HTTP 服务，不要求本地连接远端：

```bash
# 服务已启动则直接运行主实验。
bash examples/benac_p/run_full_diagnose.sh

# CPU-only 生成、认证和导出，不请求模型。
bash examples/benac_p/run_full_diagnose.sh --export-only

# 只在需要定位原因时增加辅助探针。
bash examples/benac_p/run_full_diagnose.sh --extended

# 更大样本，仍是同一冻结结构。
BENAC_DIAGNOSE_GAMES=48 BENAC_DIAGNOSE_WORKERS=8 \
bash examples/benac_p/run_full_diagnose.sh

# 同一输出目录、同一配置恢复。
BENAC_DIAGNOSE_OUTPUT_DIR=runs/benac_full_diagnose/具体目录 \
bash examples/benac_p/run_full_diagnose.sh --resume
```

环境变量保留：`BENAC_P_VLLM_BASE_URL`、`VLLM_SERVED_MODEL_NAME`、
`BENAC_DIAGNOSE_OUTPUT_DIR`、`BENAC_DIAGNOSE_GAMES`、`BENAC_DIAGNOSE_SEED`、
`BENAC_DIAGNOSE_WORKERS`、`BENAC_DIAGNOSE_MAX_TOKENS`、`BENAC_P_VLLM_API_KEY`。
默认 4 路并发、temperature 0；任务数与上限写入 manifest。

输出 manifest、静态/动态 tasks、oracle labels、certificates、answers、scores、
summary、report 和运行日志。原子保存与断点续跑保留；格式错误不替换为 oracle，
依赖无效 model belief 的任务标为 blocked_parent。v2 profile/hash 与旧 v1 不同，
不能把新任务混进旧运行目录；core/extended 也需要分别建目录。

## 9. 冻结输出协议：brief reasoning + auto tool call

四块实验统一使用 `reasoning_tools`：普通 content 中先给简短自由推理，随后恰好
一个 native tool call。默认提示为：

> Give brief free-form reasoning in at most three short sentences, aiming for under 100 words.
> Do not restate the problem. Then submit your answer with exactly one of the supplied tool calls.

不规定必须经过哪些战略推理步骤，不把诊断答案写进 reasoning scaffold。
B 使用 `SUBMIT_BELIEF(probabilities=...)`；P 使用 `SUBMIT_ACTION(action_index=...)`；
grounding 使用 `SUBMIT_UTILITIES(utilities=...)`。现有行动集合与评分不变。
推理不放进工具参数，也不会连同 model belief 注入下一个 planner 调用。

HTTP 使用 `tool_choice="auto"`、`parallel_tool_calls=false`，不设置整段输出的
JSON response_format。使用现有 repo vLLM native-tool server 的 parser 配置。
默认 **max_tokens=1024，包含 reasoning 和 tool call 的总输出**；三句/100 词是软
约束，不是独立 reasoning token 配额。不会用换行 stop sequence 切断工具调用。

每条回答保存 content/reasoning、tool calls、raw message、usage、finish_reason、
推理出现标记、按空白切分的词数和耗时。`protocol_summary.json` 汇总总 completion
长度 mean/P95、推理覆盖、超出软词数提示的次数、合法性与截断情况。词数不是 token
数；不声称精确区分 content 和工具参数各自消耗的 tokens。

`finish_reason="length"` 标为 `truncated`，即使已解析出工具调用，也不算正常完成
的能力读数。缺失/错误/多个 tool calls 标为 `invalid`，绝不当作 PASS 或 planning
regret。依赖无效 belief 的 planner 标为 blocked_parent。若调用合法但没有 reasoning，
仍正常评分，单独计入 reasoning coverage；超过软词数但正常完成也不强行判无效。

先在 discovery 检查长度与截断，必要时统一调整预算，再冻结 confirmation 配置。
保留纯 JSON action 作为可选对照：

```bash
# 默认短 reasoning + auto tools，总输出上限 1024。
bash examples/benac_p/run_full_diagnose.sh

# 不同输出目录运行纯 action 对照，默认同样 1024 总 tokens。
bash examples/benac_p/run_full_diagnose.sh --response-protocol json_action

# 需要时统一提高所有实验条件预算。
BENAC_DIAGNOSE_MAX_TOKENS=1536 bash examples/benac_p/run_full_diagnose.sh
```

manifest 记录协议版本、system prompt hash、工具 schema hash 和 token 上限；不能
把旧纯 action 输出或其他预算续跑进本次实验。输出额外包含 `protocol_summary.json`
与动态工具 schema；真实模型推理质量仍需远端运行验证。

## 10. 方法来源

[TERMS-Bench](https://arxiv.org/html/2605.13909v1) 提供 controlled counterpart、
posterior intervention 和 reference gap 的方法参考。
[Riemer et al.](https://arxiv.org/html/2412.19726v1) 提醒显式判断与行为使用的区别。
本项目据此同时测 B、给定 B 的 P，以及两条功能依赖；诊断服务于后续 post-training
与 transfer，诊断本身不替代主研究 claim。
