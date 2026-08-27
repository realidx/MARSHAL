我基本赞成，而且我觉得这次变化不是“小修”，而是把项目真正找到一个更统一的核心机制了。

之前我们的结构更像：

\[
\text{ASK},\quad \text{SAY},\quad \text{ACT}
\]

三个 interaction skills 并列。

现在更自然的结构应该变成：

\[
\boxed{
\text{Partner Modeling}
\rightarrow
\{\text{ASK},\text{SAY},\text{ACT}\}
}
\]

而 interaction 本身又不断反过来更新 partner model：

\[
\boxed{
M_t
\rightarrow
a_t\in\{\text{ASK,SAY,ACT}\}
\rightarrow
o_{t+1}
\rightarrow
M_{t+1}
}
\]

这一下其实把整个项目串起来了。

---

## 1. 你抓到的关键点：ASK 本身确实不是最本质的问题

假设我已经知道：

```text
Alice knows database architecture.
Bob knows frontend.
Charlie knows deployment.
```

现在 deployment 出问题。

那么问谁？

当然问 Charlie。

这时候所谓“ASK ability”几乎退化成：

\[
\text{query routing}
\]

甚至就像你说的，把其他 agents 当成 tools：

```text
deployment_question → call Charlie
```

这并没有多少真正的 multi-agent intelligence。

真正困难的是：

> **我一开始并不知道 Charlie 到底知道什么。**

也许我只知道有 Alice / Bob / Charlie 三个 agents。然后：

```text
Alice: I didn't work on deployment.
Bob: I changed the API gateway yesterday.
Charlie: I don't know the gateway, but I configured the container.
```

经过 interaction，我逐渐形成：

\[
M(\text{Alice}),M(\text{Bob}),M(\text{Charlie})
\]

然后下一次出现 deployment error 时，我选择 Bob，而不是随机问一个人。

所以真正的能力不是：

\[
\text{ask the right person}
\]

而是：

\[
\boxed{
\text{learn who the right person is}
\rightarrow
\text{then ask the right person}
}
\]

这个差别非常重要。

---

# 2. SAY 其实更加证明了这一点

假设我知道一个信息：

> database schema changed.

我要不要说？

这不能只看：

> “这是不是重要信息？”

而应该看：

> **对谁重要？**

比如：

```text
Alice: backend
Bob: UI
Charlie: database migration
```

那么：

\[
P(\text{message useful}\mid Alice)
\neq
P(\text{message useful}\mid Bob)
\neq
P(\text{message useful}\mid Charlie)
\]

更进一步：

如果我认为 Alice 已经知道 schema changed，那么没必要再告诉她。

如果我认为 Bob 的下一步 action 依赖这个信息，就应该主动告诉 Bob。

所以 SAY 本质上依赖：

\[
\hat B_j
=
\text{my belief about what partner }j\text{ believes/knows}
\]

以及：

\[
\hat G_j
=
\text{my belief about what partner }j\text{ wants to achieve}
\]

于是：

\[
\text{SAY}(j,m)
=
\pi_{\text{say}}
(
\hat B_j,
\hat G_j,
s,
m
)
\]

这已经非常接近 Theory of Mind 了。

---

# 3. ACT 也是一样

ACT 更明显。

假设我们知道：

```text
Alice wants X.
Bob wants Y.
```

同一个 action 对不同 partner 意义完全不同。

甚至对于 cooperative task：

```text
I believe Bob is trying to implement module Y.
```

因此：

```text
I should implement module X.
```

这里我的 action 本质上依赖：

\[
\text{belief about partner goal}
+
\text{belief about partner future action}
\]

所以你的新理解可以压缩成一句非常漂亮的话：

> **Multi-agent interaction is not primarily about knowing how to ask, say, or act; it is about learning a model of one's partners and conditioning asking, saying, and acting on that model.**

我觉得这个比之前的 formulation 强很多。

---

# 4. 而且它有非常扎实的理论支撑

这个其实正好和 **Interactive POMDP (I-POMDP)** 的经典 formulation 对上。

普通 POMDP 维护的是：

\[
b_t(s)
\]

也就是：

> 我认为环境现在是什么状态。

I-POMDP 最核心的修改就是把 **other-agent models 也放进 interactive state**。agent 不只是维护 world belief，还维护关于其他 agents 的 beliefs/models，并且随着 interaction 持续 Bayesian update。原论文甚至明确提到其他 agent model 可以涉及其 **preferences、capabilities 和 beliefs**。

也就是说，我们可以非常自然地写：

\[
IS_t^i
=
(
s_t,
M_t^1,
M_t^2,\dots,M_t^n
)
\]

然后：

\[
\pi_i(a_t\mid b_t(IS))
\]

这正是：

> action conditioned on partner attribution。

Bayesian Theory of Mind / inverse planning 则给你提出的 **goal + belief** 一个更直接的理论依据。Baker、Saxe、Tenenbaum 的经典 computational ToM 模型把 intentional behavior 理解成：agent 根据自己的 **beliefs** 采取近似理性的行动去实现自己的 **goals**；观察者再反过来从行为推断它的 beliefs 和 goals。

所以你提出：

\[
\boxed{
\text{Partner Model}
=
(\text{Goal},\text{Belief})
}
\]

其实不是一个随便拍脑袋的 decomposition。

它有很强的 cognitive / decision-theoretic foundation。

---

# 5. 但这里有一个我觉得非常重要的修正

我不建议说：

> partner attributes 在一个 episode 内不变，其中包括 goal 和 belief。

因为 **goal 可以固定，但 belief 通常不能固定。**

比如：

```text
t=0:
Bob doesn't know the password.

t=1:
Alice tells Bob the password.

t=2:
Bob knows the password.
```

Bob 这个 agent 没变。

他的：

\[
G_B
\]

可能完全没变。

但是：

\[
B_{B,0}\neq B_{B,2}
\]

所以这里最好区分两个东西：

\[
\boxed{
\text{Partner Type}
\quad vs \quad
\text{Partner State}
}
\]

我会这样建模：

\[
\theta_j
=
\text{episode-persistent partner properties}
\]

和：

\[
z_{j,t}
=
\text{time-varying partner mental state}
\]

然后 focal agent 维护：

\[
M_{j,t}
=
P(\theta_j,z_{j,t}\mid h_t)
\]

这会比全部叫 attribution 清晰很多。

---

# 6. 那么到底 attribution 里面放什么？

我觉得这里**千万不要再次走向一个巨大的**

\[
A+B+C+D+E
\]

latent social vector。

你之前对这个问题的担心是对的。

我们应该从一个 normative assumption 出发：

> **为了选择 ASK / SAY / ACT，最少需要知道 partner 的什么？**

我目前会优先考虑：

\[
\boxed{
M_{j,t}
=
(\hat G_j,\hat B_{j,t})
}
\]

也就是：

**Goal**

\[
G_j:
\quad
\text{What is this agent trying to achieve?}
\]

**Belief**

\[
B_{j,t}:
\quad
\text{What does this agent currently believe/know?}
\]

这是一个非常干净的第一版。

而且最近 MuMA-ToM 的 formulation 也非常接近：它专门测试 agent 的 **belief、social goal、belief about another agent's goal**，说明 goal/belief 确实是当前 ToM literature 中非常自然的一组 mental variables。

---

# 7. Capability 要不要加？

这个我觉得暂时**不要作为一级变量加进去**。

例如：

> “Bob knows Python.”

到底是：

```text
capability = Python
```

还是：

```text
belief/knowledge = relevant Python knowledge
```

很多简单环境里其实没有必要区分。

只有当我们真正出现这种情况：

```text
Bob knows what the problem is,
but Bob cannot solve it.
```

才必须区分：

\[
\text{knowledge}
\neq
\text{capability}
\]

所以第一版完全可以假设：

> if an agent knows the relevant solution/information, it is capable of supplying or using it.

把 competence/capability 留给之后。

这样模型会干净很多。

---

# 8. Reliability 反而可以直接去掉

这也是你现在这个设置很聪明的地方。

如果规定：

> agents 不撒谎。

那么我们暂时不需要：

\[
R_j=\text{reliability}
\]

这直接和 ECL 拉开了。

ECL 的核心是从 historical interactions 建 explicit peer profiles 来估计 reliability，并据此决定是否信任对方。

我们可以说：

> **ECL asks: given previous interactions, which partner should I trust?**

而我们的问题更接近：

> **Given interaction with a previously unknown partner, what does this partner know and want, and how should my subsequent communication and action adapt to that inferred mental state?**

它们会有 overlap，但中心完全不同。

---

# 9. 这也解释了为什么“不允许撒谎”是好事

因为如果允许撒谎：

```text
Bob: I don't know.
```

可能是：

\[
\begin{cases}
B_B(X)=\text{unknown}\\
B_B(X)=\text{known but withholding}\\
B_B(X)=\text{known but deceptive}
\end{cases}
\]

这样我们马上又必须 infer：

\[
\text{reliability}
+
\text{incentive}
+
\text{deception policy}
\]

整个问题立刻爆炸。

所以第一版非常合理：

```text
Truthful answer
I don't know
I can't tell you
```

其中：

- `I don't know` → epistemic state；
- `I can't tell you` → communication constraint；
- 没有 deception。

这样非常干净。

---

# 10. 我甚至会重新定义 ASK

以前：

\[
ASK
=
\text{acquire task information}
\]

现在更准确的是：

\[
\boxed{
ASK
=
\text{an action that can acquire both task information and partner information}
}
\]

这是一个非常关键的改变。

比如：

```text
ASK Bob:
"Do you know who modified the database schema?"
```

如果 Bob 回：

```text
"No, I only worked on the frontend."
```

这个回答可能**没有解决当前 task uncertainty**。

但它解决了：

\[
\text{partner uncertainty}
\]

我现在知道：

\[
P(
\text{Bob knows frontend}
\mid h
)
\uparrow
\]

以及：

\[
P(
\text{Bob knows DB}
\mid h
)
\downarrow
\]

这条信息可能在 episode 后面非常有价值。

所以 ASK 有两种 value：

\[
\boxed{
VOI_{\text{ask}}
=
VOI_{\text{task}}
+
VOI_{\text{partner model}}
}
\]

这一下我觉得研究味道就明显起来了。

---

# 11. 这里甚至出现一个非常好的核心 difficulty

agent 什么时候应该问：

> “答案是什么？”

什么时候应该问：

> “你知道什么？”

这是两种完全不同的 information acquisition。

例如：

```text
ASK Bob:
"What is the password?"
```

是 **task-directed query**。

而：

```text
ASK Bob:
"What part of the system did you work on?"
```

是 **partner-directed query**。

后者当前可能没有直接 reward。

但是它改善：

\[
M_B
\]

从而帮助 future decisions。

这就是一种真正的：

\[
\boxed{
\text{exploration about another agent}
}
\]

而不是单纯 tool invocation。

我甚至觉得这可能变成你这个 project 最有意思的地方。

---

# 12. 于是整个 interaction loop 可以变得非常漂亮

我们不需要：

```text
ASK → SAY → ACT
```

这种流水线。

而是：

\[
M_t
\rightarrow
\pi
\rightarrow
u_t
\rightarrow
o_{t+1}
\rightarrow
M_{t+1}
\]

其中：

\[
u_t
\in
\{
ASK(j,q),
SAY(j,m),
ACT(a)
\}
\]

注意：

**没有 WAIT。**

**没有主动 OBSERVE。**

history 只是自然产生：

\[
h_t=(u_1,o_1,\dots,u_t,o_t)
\]

agent 每一次 interaction 后更新：

\[
M_{j,t+1}
=
Update(M_{j,t},o_{t+1})
\]

然后下一步 ASK / SAY / ACT 都依赖：

\[
M_{1:n,t}
\]

我觉得这是目前为止最干净的模型。

---

# 13. 但这里我会建议换一个词：Partner Attribution → Partner Model

这是比较 academic-writing 层面的考虑。

我觉得：

> **partner attribution**

可以描述一个能力：

\[
\text{infer latent properties of partner}
\]

但真正被维护的 representation 最好叫：

\[
\boxed{\text{Partner Model}}
\]

或者：

\[
\boxed{\text{Interactive Belief / Partner Belief}}
\]

所以：

\[
\textbf{Partner Attribution}
=
\text{the inference process}
\]

而：

\[
\textbf{Partner Model}
=
\text{the resulting maintained representation}
\]

然后你的核心能力是：

\[
\boxed{
\text{Partner model acquisition and maintenance}
}
\]

这个术语与 I-POMDP 和 teammate-modeling literature 会更直接连接。

ad-hoc teamwork 本身其实就是研究“面对 previously unknown teammates，如何快速建模并适应”；经典工作和近期工作都大量使用 teammate modeling / latent teammate context 这种 framing。

---

# 14. 和现有工作的关系也一下变清晰了

我现在会把 literature space 看成这样：

| Work | Partner model 从哪里来 | Model 什么 | 用来干什么 |
|---|---|---|---|
| ECL | history | reliability | trust/reference |
| A-ToM | prior interactions | partner ToM order | predict/coordinate |
| ROTE | observed trajectories | behavioral program | predict behavior |
| MuMA-ToM | observation + dialogue | belief / social goal | evaluate mental-state reasoning |
| **我们** | **active communication during task** | **goal + belief** | **condition ASK/SAY/ACT** |

A-ToM 2026 的确从 prior interactions 估计 partner 的 ToM level，再据此预测其 action。

ROTE 则提出了一个很有意思的反例：不一定非要用 explicit belief/desire，而可以从 sparse observations 推断 behavioral programs 来预测 partner。

这对我们反而是好事，因为它提醒我们：

> **不要声称 goal+belief 是唯一正确的 partner representation。**

我们可以更谨慎地说：

> 我们选择 goal + belief，是因为它们提供一个 principled、minimal、interpretable partner model，并直接对应 ASK/SAY/ACT 所需要的信息。

---

# 15. 我觉得真正应该设计的新 training environment 已经不是 Hidden Choice 了

原来的 Hidden Choice：

```text
find missing information
→ ask someone
→ choose
```

现在太浅了。

新的环境至少必须让：

\[
\boxed{
\text{learning partner model early}
}
\]

对：

\[
\boxed{
\text{later interaction success}
}
\]

产生价值。

否则根本测不出来我们要的东西。

举一个最简单的 episode：

```text
Agents: Alice, Bob, Charlie

Unknown to focal agent:

Alice:
    Goal: finish backend
    Belief: knows DB + API

Bob:
    Goal: finish frontend
    Belief: knows UI + API

Charlie:
    Goal: deploy system
    Belief: knows infra
```

一开始 focal agent 不知道这些。

然后 task 有多个阶段。

第一阶段可能出现：

```text
Need to diagnose an API error.
```

focal agent 可以 ask。

interaction 后，它逐渐知道：

```text
Alice likely knows backend.
Bob likely knows frontend.
Charlie likely knows infra.
```

第二阶段：

```text
Need deployment information.
```

如果它真正维护了 partner model：

\[
M_{\text{Charlie}}
\]

它应该直接找 Charlie。

第三阶段它自己获得：

```text
API schema changed.
```

它应该推断：

> Bob 的 frontend goal/action 依赖 API schema。

于是主动：

```text
SAY(Bob, schema_changed)
```

第四阶段需要 joint action。

它根据：

\[
G_{\text{Alice}},G_{\text{Bob}},G_{\text{Charlie}}
\]

选择自己的 ACT。

这样一个 episode 里面就已经自然出现：

\[
ASK
\rightarrow
update\ partner
\rightarrow
ASK
\rightarrow
SAY
\rightarrow
ACT
\]

但这不是 hard-coded sequence。

这是 partner model 自然驱动出来的。

---

# 16. 最关键的实验不是“能不能预测 attribute”

这个我特别想强调。

我们千万不要最后做成：

```text
Agent profile:
Goal = ?
Belief = ?

Accuracy = 85%
```

然后说：

> model learned partner attribution.

那很容易退化成一个 ToM benchmark。

真正重要的 evaluation 应该是：

\[
\boxed{
\text{Does better partner modeling cause better interaction decisions?}
}
\]

因此至少要比较四种情况：

1. **No partner modeling**
   
   所有历史不提供 / partner identity randomized。

2. **Oracle partner model**
   
   直接告诉 agent partner goal + belief。

3. **Learned through interaction**
   
   agent 自己 ASK / 从 SAY 更新。

4. **Corrupted partner model**
   
   给错误 attribution。

如果：

\[
Performance_{\text{oracle}}
>
Performance_{\text{learned}}
>
Performance_{\text{none}}
\]

并且：

\[
Performance_{\text{corrupted}}
<
Performance_{\text{learned}}
\]

那就真正支持：

> partner attribution is functionally causal to interaction performance.

这个证据比直接让模型 report “Bob goal 是什么”强得多。

---

# 17. 更漂亮的是我们可以测一个新的 quantity

我会特别关注：

\[
\boxed{
\text{Attribution-conditioned behavioral adaptation}
}
\]

也就是同一个 physical/task state：

\[
s
\]

只有 partner model 不同：

\[
M_j^{(A)}
\neq
M_j^{(B)}
\]

那么 agent 的 action 应该发生变化：

\[
\pi(a\mid s,M_j^{(A)})
\neq
\pi(a\mid s,M_j^{(B)})
\]

例如完全相同的问题：

> “我应该把这个 bug report 发给谁？”

但 inferred partner state 不同。

如果 model 无论 history 怎么变都永远找 Alice：

> 没有 partner-conditioned behavior。

如果它随着获得的信息真正改变 ASK/SAY/ACT：

> 才有 adaptation。

这可以成为非常干净的 behavioral metric。

---

# 18. 所以我现在会把整个 project 改写成这个中心

不是：

\[
\text{Train ASK + SAY + ACT}
\]

而是：

\[
\boxed{
\text{Learn partner models through interaction}
\rightarrow
\text{use them to guide ASK, SAY, and ACT}
}
\]

而 training games 的作用变成：

> **创造一种环境，使得成功必须依赖于准确建立和维护 partner model。**

这句话非常重要。

我们不应该直接 reward：

```text
+1 correct partner attribution
```

而应该让：

\[
\text{good attribution}
\Rightarrow
\text{better task reward}
\]

于是 RL 被迫学习：

\[
\text{interaction}
\rightarrow
\text{partner inference}
\rightarrow
\text{adaptive policy}
\]

---

# 19. 我目前最喜欢的 formalization

如果让我现在就给这个项目定一个数学骨架，我会用这个：

对于每个 partner \(j\)：

\[
\theta_j = G_j
\]

作为相对 persistent 的 latent goal/type，

以及：

\[
B_{j,t}
\]

作为动态 epistemic state。

focal agent 不知道它们，只维护：

\[
q_{j,t}(G_j,B_{j,t})
=
P(G_j,B_{j,t}\mid h_t)
\]

每一步：

\[
u_t
\sim
\pi_\phi
(
u
\mid
o_t,
q_{1,t},\dots,q_{n,t}
)
\]

其中：

\[
u_t
\in
\{
ASK(j,q),
SAY(j,m),
ACT(a)
\}
\]

interaction 返回 observation：

\[
o_{t+1}
\]

然后：

\[
q_{j,t+1}
=
Update_\phi
(
q_{j,t},
u_t,
o_{t+1}
)
\]

episode 中：

\[
G_j=\text{fixed}
\]

但：

\[
B_{j,t}
\]

可以随着 information exchange 改变。

**我认为这就是现在最值得继续往下推的版本。**

而且它比我们之前那个“ASK game + SAY game + commitment game”有更强的统一性：以前是在列技能，现在是在提出一个 **mechanism hypothesis**：

\[
\boxed{
\textbf{Effective multi-agent interaction requires maintaining a task-relevant model of other agents; communication and action should be conditioned on, and simultaneously refine, that model.}
}
\]

这已经开始像一个可以支撑整篇 paper 的 hypothesis，而不只是 curriculum design 了。