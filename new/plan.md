# BENAC-P v0：可执行的游戏实现计划

**状态：** 当前阶段已实现并跑通 game engine、policy-agnostic self-play harness、native OpenAI-compatible tool-calling vLLM adapter（含一次 retry），以及用于 debug/controlled diagnostics 的 rational oracle 和 perfect-information reference solver；第一版直接用 self-play 验证交互。Bayesian inference、diagnostics 和 reproduction 仍是后续工作。

这份文件是当前的 canonical plan。它根据之前的讨论重新整理；如果和早期聊天记录有冲突，以本文件后面的定义为准。

## 1. 第一阶段的目标

第一阶段的交付物是一个可以运行完整 episode 的 BENAC-P v0：

```text
随机生成 game
→ 为每个 player 创建 private observation
→ proposer 选择 PASS 或 partner + offer
→ partner 选择 ACCEPT 或 REJECT
→ environment 执行 binding commitment transition
→ 重复直到 finite horizon 结束
→ 返回每个 player 的 terminal reward 和 public transcript
```

所有 player 都必须通过同一个可替换的 policy interface 控制。policy 可以是：

- LLM / vLLM policy；
- oracle-style policy；
- random 或 scripted policy；
- 以后接入的任意 learned policy。

第一版优先测试 **self-play**：三个 player 使用同一种 policy class，但每个 player 获得自己的 private preference 和同一份 public transcript。oracle 不再是第一优先级。

## 2. v0 的正式游戏定义

### 2.1 Players 和 horizon

默认参数：

```text
N_PLAYERS = 3
ACTIONS_PER_PLAYER = 3
N_GOALS = 8
N_ROUNDS = 4
MAX_CHANGES = 1
```

round-robin schedule 由一个 seed 决定。`N_ROUNDS=4` 表示每个 player proposer 四次，因此一个 episode 有：

```text
N_PLAYERS * N_ROUNDS = 12 proposer turns
```

以后可以把 `N_PLAYERS`、action 数量、round 数量和 `MAX_CHANGES` 参数化，但不改变 policy interface。

### 2.2 Commitments

每个 player (i) 有 (K_i) 个 binary commitments：

\[
C_i\in\{0,1\}^{K_i}.
\]

初始状态为：

\[
C_i^0=0.
\]

commitments 是 binding 的，只允许：

\[
0\rightarrow 1.
\]

已经 committed 的 action 永远不能回到 0。

### 2.3 Goals

每个 goal (g) 有一个 public requirement set：

\[
\mathcal C_g\subseteq\{(i,a):i\text{ 是 player},a\text{ 是该 player 的 action}\}.
\]

v0 中所有 goals 都是 binary/all-or-nothing：

\[
S_g(C)=
\mathbb 1[(i,a)\in\mathcal C_g\Rightarrow C_{ia}=1].
\]

也就是说，一个 goal 的所有 required commitments 都完成时，它的 satisfaction 才是 1，否则是 0。v0 暂时不使用 linear goals。

同一个 commitment 可以出现在多个 goals 中。这是制造 long-horizon consequences 的关键机制。

### 2.4 Private preferences

每个 player 对每个 goal 有一个 private qualitative preference：

```text
WANT     → +1
NEUTRAL  →  0
AVOID    → -1
```

内部保存为：

\[
V_{i,g}\in\{-1,0,+1\}.
\]

player (i) 的 terminal utility 为：

\[
U_i(C^T)=\sum_g V_{i,g}S_g(C^T).
\]

数字 `-1/0/+1` 只存在于 environment 和 evaluation 中；默认 agent observation 只显示 `WANT/NEUTRAL/AVOID`，不显示其他 player 的 preference。

v0 不使用：

- generator type；
- A/B/C type label；
- ego/helper/adversary family；
- preference magnitude；
- personality 或 reliability latent variable。

### 2.5 Reward

采用 terminal-only reward：

\[
r_i^t=0\quad(t<T),
\]

episode 结束时返回：

\[
r_i=U_i(C^T).
\]

不加入 information reward、belief reward、cooperation bonus 或 query reward。

## 3. Generator v0

### 3.1 Public goal hypergraph

每个 goal 随机选择不同的 players，再从每个被选 player 中随机选择一个 commitment。默认 goal arity 在 2 和 3 之间均匀采样：

```text
G0 = {P0.A1, P2.A0}
G1 = {P0.A0, P1.A2, P2.A1}
```

因此一个 goal 不重复选择同一个 player，但不同 goals 可以重复使用同一个 commitment。

### 3.2 Connected 的定义

将 public goal hypergraph 投影成 player graph：

- 每个 player 是一个 vertex；
- 如果两个 players 出现在同一个 goal 中，就在它们之间连 edge。

`connected` 定义为这个 player graph 连通。也就是说，从任意 player 都可以通过共同参与的 goals 到达其他 player。

### 3.3 Preference sampling

对每一个 `(player, goal)` 独立采样：

```text
P(WANT)    = 0.4
P(NEUTRAL) = 0.2
P(AVOID)   = 0.4
```

然后 resample 整局，直到满足以下基础 constraints：

- 每个 player 至少有一个 `WANT` goal；
- 每个 goal 至少被一个 player 视为非 `NEUTRAL`；
- player graph connected；
- 每个 player 至少参与一个 multi-player goal；
- 不允许两个 goals 的 requirement set 完全相同；
- 不强行要求每个 goal 同时包含 cooperation 和 conflict；
- 暂时允许存在没有出现在任何 goal 中的 commitment，但 generator 要记录 action coverage，之后根据样本分布再决定是否过滤。

generator 必须接受 seed 并保证 deterministic。超过最大 resampling 次数时明确抛出错误，不静默生成不满足约束的 game。

### 3.4 Generator 的输出

generator 返回一个 `GameSpec`，至少包含：

```text
public goals and requirements
goal type = binary
number of players/actions
round-robin schedule
private preference matrix  # environment/evaluation only
seed and generator metadata
```

`generator metadata` 可以保存到 log 中，但不能出现在默认 player observation 中。v0 没有需要隐藏的 generator type。

## 4. State、public transcript 和 observation

### 4.1 Complete internal state

environment 内部保存完整世界状态：

```text
commitment matrix C
private preference matrix V
public goal requirements
public goal types
round-robin schedule
current turn index
public transcript
```

“perfect information”不是一个特殊 player class，而是 observation/view 的选择。环境可以拥有完整 state，同时给不同 policy 不同 visibility。

### 4.2 Default public transcript

BENAC-P v0 使用 public transcript。所有 players 都观察：

- 当前 proposer；
- proposer 是否选择 `PASS`；
- selected partner；
- 完整 offer；
- `ACCEPT` 或 `REJECT`；
- 每次 transition 后的 commitment state；
- 历史 turn index 和 round-robin schedule。

player 只额外观察自己的 private preference，不观察其他 players 的 preference。

以后可以加入 local/bilateral transcript 作为 harder information structure，但不属于 v0。

### 4.3 Player observation

默认的 `PlayerObservation(player_id)` 包含：

```text
player identity
own WANT / NEUTRAL / AVOID preferences
public goals and named requirement sets
current commitments as named actions, e.g. P0: [A0]
round-robin position
public event transcript without repeated commitment snapshots
legal partner names
pending offer as named deltas, if this player is responder
```

agent-facing observation 使用 named representation，例如：

```json
{
  "current_commitments": {"P0": ["A0"], "P1": [], "P2": ["A1"]},
  "pending_offer": {
    "proposer": "P1",
    "partner": "P2",
    "proposer_adds": ["A2"],
    "you_add": ["A0"]
  }
}
```

内部 `PlayerObservation` 仍可以保留 matrix、完整 target vector 和
`legal_offers`，供 environment validator、tool mask、oracle 和 solver 使用；这些
字段不进入 LLM 的 agent-facing payload。

它不包含：

```text
other players' preference values
generator labels
hidden evaluation metadata
```

可以提供显式的 `full` debug view 来测试 perfect-information policy，但不创建 `PerfectInfoOracle`。任何 policy 都可以选择接收 public/private view 或 full view；这是环境配置，不是 policy 身份。

## 5. Action 和 turn semantics

### 5.1 Proposer 的 action 不是人为拆成两层

proposer 每个 turn 做一个 atomic decision。canonical vLLM wire protocol
通过 OpenAI-compatible native tools 发送：

```text
tools = [PASS(), OFFER(...)]
tool_choice = "auto"
parallel_tool_calls = false
```

可用 tool 只包含当前 proposer phase 的 action types；如果当前没有任何
合法 offer，则只发送 `PASS()`。`PASS()` 是明确的战略 no-op，不是缺少
tool call 的 fallback。

`OFFER` 的参数使用可读的 commitment names：

```json
{
  "partner": "P1",
  "self_commitments": ["A0"],
  "partner_commitments": ["A1"]
}
```

因此 proposer 仍然一次性选择 `partner + offer`，不使用额外的
partner-selection stage → offer-selection stage hierarchy。

### 5.2 Offer 的表示

为了沿用原 BENAC 的 environment 设计，内部 offer 仍然执行两个 **最终
binary action vectors** 的 transition，而不是改变 game mechanism：

\[
o_t=(a_p,a_q).
\]

每个 vector 的长度等于对应 player 的 action 数量。environment 内部可以计算：

\[
\Delta C=a\land \lnot C
\]

来验证新 commitment 数量。native tool policy 的 wire-level
`self_commitments` 和 `partner_commitments` 表示希望新增的 action names；
adapter 会结合当前 commitment state 将它们转换成 environment 所需的完整
final vectors，然后交给同一个 legality validator。

一个 offer 合法，当且仅当：

- `partner_id != proposer_id`；
- vector 长度正确；
- 所有当前为 1 的 bits 在 offer 中仍为 1；
- 每个 player 新增的 0→1 bits 不超过 `MAX_CHANGES`；
- 不触发 forbidden action；
- proposer 和 partner 两侧合计至少新增一个 commitment。

空 offer / no-op offer 禁止。proposer 如果不想推进任何 commitment，必须选择 `PASS`。

### 5.3 Turn transition

每个 proposer turn 的执行顺序是：

```text
1. proposer policy.propose(observation)
2. 如果 action == PASS：
       C 不变
       记录 PASS event
       turn index + 1
3. 如果 action == OFFER：
       environment 验证 offer
       将 offer 和 pending state 交给 selected partner
4. partner policy.respond(observation, offer)
5. 如果 response == ACCEPT：
       C ← C OR offer
   如果 response == REJECT：
       C 不变
6. 记录完整 public event
7. turn index + 1
```

`ACCEPT/REJECT` 是 responder player 的 policy action，不是 environment 自动推导的规则。这样同一个 game 可以由 LLM、oracle、random 或任意 policy 玩。

### 5.4 Invalid action handling

机制层面，非法 action 不是合法 game action。默认 runner 使用 strict mode，遇到非法 output 直接抛出带上下文的 `InvalidActionError`。

canonical native vLLM policy 对 missing tool、malformed tool、multiple tool
或 illegal tool 做一次 retry。retry 只追加格式反馈：

```text
Your previous response did not contain one valid game action.
Choose exactly one of the available actions.
```

它不告诉 agent 应该采取哪一种战略。两次都失败后才抛出
`InvalidActionError`。strict mode 直接终止；non-strict mode 可以把 proposer
转换成带 `invalid_action=true` 的 fallback event、把 responder 转换成带
标记的 `REJECT`，但不会把缺少 tool call 当成有意的 `PASS()`。

## 6. Policy interface

实现一个与 agent 类型无关的 policy protocol：

```python
class PlayerPolicy(Protocol):
    def propose(self, observation: PlayerObservation) -> Proposal:
        ...

    def respond(
        self,
        observation: PlayerObservation,
        proposal: Offer,
    ) -> Response:
        ...
```

其中：

```text
Proposal = Pass | Offer
Response = ACCEPT | REJECT
```

`GameRunner` 接收：

```python
policies: Mapping[int, PlayerPolicy]
```

因此每个 player 都可以使用不同 policy，也可以三个 player 使用同一个 policy class / 同一个 vLLM model。self-play 默认使用同一 policy class 的三个独立 player contexts，避免任何 policy 获得不属于自己的 private state。

第一阶段至少实现：

- `RandomPolicy`：只用于 engine smoke test；
- `ScriptedPolicy`：用于精确覆盖 PASS、ACCEPT、REJECT 和 binding transitions；
- `VLLMPlayerPolicy`：用于第一版真正的 self-play。

不把 oracle 设计成第一阶段的核心依赖。

第一阶段仍提供一个非必需的 `RationalOraclePolicy` 作为 debug baseline。它
通过 `PerfectInfoSolver` 使用完整 `GameSpec`，按 continuation value 做
`ACCEPT/REJECT` 和 proposer action 选择；这不是 Bayesian oracle，也不改变
正常 policy 的 private observation 机制。

## 7. vLLM 接口

canonical training/evaluation interface 使用 OpenAI-compatible native tools，
不要求模型在普通 content 中打印裸 JSON。HTTP client 发送 `messages`、
当前 phase 的 `tools`、`tool_choice="auto"` 和
`parallel_tool_calls=false`，然后消费服务端返回的标准
`message.tool_calls`。

对于 `Qwen3-4B-Instruct-2507`，使用 non-thinking model behavior；普通文本
reasoning 可以出现在 tool call 前，但不依赖 `<think>...</think>`。Qwen 的
tool-call template 使用 Hermes-style 格式；vLLM server 使用：

```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

旧的 ROLL in-process `LLM`/`AsyncLLM` adapter 保留为 legacy backend，不能
代表 canonical vLLM 0.28 deployment path。

### 7.1 Proposer prompt/output

proposer prompt 只能包含：

- 自己的 `WANT/NEUTRAL/AVOID`；
- public goals、requirements、binary semantics；
- named current commitments；
- public event transcript；
- 合法 partner 和 offer constraints；
- “其他 players 有自己的 private preferences，并最大化自己的 terminal utility”这一
  environment fact。

prompt 不直接告诉 model 需要如何诊断 partner acceptance、如何比较 future
continuation，或如何展开 lookahead。`legal_offers` 不发送给 model；模型根据当前
commitments、goals、constraints 和 OFFER schema 构造 action。

HTTP request 只发送 proposer 当前可用的 `PASS` 和 `OFFER` tools。model 必须
先写一段简短 reasoning，说明计划做什么以及原因，然后立即调用且只调用一个
tool。tool call 之后不能继续输出文本：

```text
PASS()
```

或：

```text
OFFER(partner="P1", self_commitments=["A0"], partner_commitments=["A1"])
```

### 7.2 Responder prompt/output

responder prompt 在 public/private observation 之外，加入当前 offer。HTTP
request 只发送两个 response tools：

```text
ACCEPT()
REJECT()
```

prompt 只说明 terminal utility 和 action semantics：`ACCEPT` 使 proposed
commitments binding，`REJECT` 保持当前 commitments 不变并推进 game。它不直接
给出“比较 accept/reject continuation”的 long-horizon 答案。model 必须先写一段
简短 reasoning，然后立即调用其中一个；tool call 之后不能继续输出文本。

vLLM 只负责生成 policy output；partner acceptance、commitment update 和
reward 仍由 game engine 执行。tool parser 的格式合法性、game engine 的
offer legality 和最终 reward 是分开的检查层。

### 7.3 Self-play 默认形态

第一版 self-play 直接让三个 players 都使用 `VLLMPlayerPolicy`：

```text
同一个 vLLM backend
→ player 0 prompt 带 player 0 private preference
→ player 1 prompt 带 player 1 private preference
→ player 2 prompt 带 player 2 private preference
```

policy 不需要显式输出 belief。历史 interaction 是否改变它的隐式判断，由后续 diagnostics 测量。

## 8. 代码结构

原来的 `third_party/negotiation_benchmark` 保留作为原 BENAC/public artifact 的 reference。BENAC-P 不直接覆盖旧 simulator 中的 perfect-information solver 或自动 offer 逻辑，而是在同一目录增加独立 package：

```text
third_party/negotiation_benchmark/
├── src/
│   ├── core/                 # 原 BENAC reference implementation
│   ├── methods/              # 原方法和 vLLM text adapter
│   └── benac_p/
│       ├── schema.py         # GameSpec, Goal, Proposal, Offer, Response
│       ├── generator.py      # connected random game generator
│       ├── state.py          # complete internal state and transitions
│       ├── observations.py   # public/private/full views
│       ├── policies.py       # PlayerPolicy, Random, Scripted
│       ├── vllm_policy.py    # VLLMPlayerPolicy
│       ├── oracle.py          # rational oracle policy for diagnostics
│       ├── solver.py          # perfect-information reference solver
│       ├── runner.py         # policy-agnostic episode loop
│       ├── sampling.py        # initial sample bundle and statistics
│       └── cli.py            # generate and run one self-play game
├── games/
└── tests/
```

`benac_p` 可以复用经过测试的低层工具，但不能继承旧 BENAC 的以下语义：

- environment 自动替 responder 接受/拒绝；
- proposer solver 自动替 agent 选择 best offer；
- 将完整 preference matrix 默认暴露给所有 player；
- 允许用空 offer 代替 PASS。

## 9. 第一阶段实现顺序

### Step 1：schema 和 generator

实现：

- `GameSpec`、`Goal`、`Offer`、`Proposal`、`Response`；
- 默认参数和 seed；
- connected player graph 检查；
- preference resampling constraints；
- public/private 字段分离。

### Step 2：state 和 transition engine

实现：

- 初始 commitment state；
- binding OR transition；
- PASS；
- offer validation；
- ACCEPT/REJECT；
- public transcript；
- terminal reward vector。

### Step 3：observation 和 policy runner

实现：

- `player_observation(player_id)`；
- private preference isolation；
- `PlayerPolicy` protocol；
- `GameRunner`；
- `RandomPolicy` 和 `ScriptedPolicy`。

### Step 4：vLLM self-play

使用 OpenAI-compatible HTTP vLLM client 实现 `VLLMPlayerPolicy`，让三个
player 都能使用同一 vLLM backend，但每次调用只看到自己的 private view。
训练和 evaluation 使用同一种 native tool wire format；每次缺少、malformed
或 illegal action 最多 retry 一次，并分别记录第一次 valid、retry 后 valid
和最终 invalid。

### Step 5：生成初始样本

生成并保存至少 100 个 3-player games，统计：

- 每个 player 的 WANT 数量；
- 每个 goal 的参与 player 数量；
- action coverage；
- connected constraint；
- self-play 中 ACCEPT/REJECT/PASS 比例；
- 最终 payoff 分布；
- 完全没有有效 offer 的 episode 比例。

这一步只看 game 是否退化，不开始做 benchmark filtering。

## 10. 必须通过的测试

### Generator tests

- 相同 seed 得到相同 `GameSpec`；
- 不同 seed 通常得到不同 game；
- player graph 始终 connected；
- 每个 player 至少一个 WANT；
- 每个 goal 至少一个非-neutral preference；
- 没有 duplicate goal requirements。

### Mechanics tests

- commitments 只能 `0→1`；
- 非法 `1→0` offer 被拒绝为 invalid action；
- 超过 `MAX_CHANGES` 的 offer 被拒绝；
- 空 offer 不能执行；
- PASS 不改变 `C`，但消耗一个 proposer turn；
- ACCEPT 执行 OR transition；
- REJECT 不改变 `C`；
- episode 恰好在 schedule 结束时 terminal；
- terminal reward 等于 `sum(preference * binary_satisfaction)`。

### Visibility tests

- player 0 能看到自己的 preference；
- player 0 看不到 player 1/2 的 preference；
- 三个 players 看到相同 public transcript；
- proposer 和 responder 的 view 在同一 offer 上信息不同但合法。

### Policy/interoperability tests

- Random、Scripted、fake LLM 都能驱动同一个 `GameRunner`；
- 三个 player 可以使用不同 policy；
- 三个 player 可以使用同一 policy class；
- fake vLLM 能通过 native tools 输出 proposer `PASS/OFFER` 和 responder `ACCEPT/REJECT`；
- missing/malformed/illegal native tool 最多只 retry 一次；
- native tool request 使用 `tool_choice="auto"`，不会发送裸 JSON `response_format`；
- 不需要真实 GPU 或网络即可完成 engine 和 adapter tests。

## 11. 明确不做的事情

第一阶段不实现：

- Bayesian exact solver；
- 显式 belief state；
- generator types 或 type classification；
- local/bilateral transcript；
- 复杂 oracle partner priority；
- PPO/RFE training；
- 原论文 reproduction sweep；
- benchmark-quality game filtering；
- information-seeking reward。

原 BENAC 的 perfect-information solver以后可以作为 reference tool，但不是 BENAC-P environment 的一部分，也不决定正式 self-play 的 ACCEPT/REJECT。

## 12. 第一阶段完成定义

当下面命令可以运行并通过时，第一阶段完成：

```bash
PYTHONPATH=src python -m benac_p.cli --seed 0 --self-play random
```

并且可以替换成：

```bash
PYTHONPATH=src python -m benac_p.cli \
  --seed 0 --self-play vllm \
  --vllm-backend http \
  --vllm-base-url http://localhost:8000/v1
```

第一条命令不需要模型或网络；第二条命令使用 OpenAI-compatible native
tool backend。server 需要开启 `--enable-auto-tool-choice` 和
`--tool-call-parser hermes`。两者都必须使用同一套 game state、transition、
observation 和 policy interface。

完成后，下一阶段进入 diagnostics：在 physical game state 相同的情况下改变 public interaction history，测试 player 的隐式 partner inference 是否导致 partner selection、offer、ACCEPT/REJECT 和 PASS 行为变化。
