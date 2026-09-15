# Prompt 原始来源核对与建议（2026-09-14）

最初版本只做来源核对与设计建议。用户确认后，已按下述组织方式实施新版 prompt，见文末实施记录。SocialRL 指此前讨论的 Hua 等人的 arXiv:2608.13787，不是另一篇同名论文。以下将实际源码、论文描述与我们的建议明确分开。

## 已核验的来源

### Benac

找到了官方仓库的 LLM baseline，而不只是论文里的算法代理。实际 prompt 在 [baselines.py](https://github.com/dtak/negotiation_benchmark_public/blob/main/src/methods/baselines.py)。核对了官方下载内容；本地 vendored baselines.py 已经有过修改，不能把它逐字当作官方版本。

原版先定义目标和伙伴接受条件，再解释 G/P/sat_masks/action_counts，列出绑定性、预算和向量长度约束，最后定义 JSON 输出。静态游戏配置和当前轮状态分两条消息提供；完整 G 是其输入。可借鉴分块与字段释义；完整信息、数字向量、纯 JSON 输出以及自动替换非法输出均不直接移植到我们的 B/P 监督。原版公开代码的存在不证明其 prompt 对我们的模型或不完全信息任务最优。

### MARSHAL

完整原文可直接阅读 [Kuhn Poker 源码](https://github.com/thu-nics/MARSHAL/blob/main/roll/agentic/env/kuhn_poker/env.py) 和 [Hanabi 源码](https://github.com/thu-nics/MARSHAL/blob/main/roll/agentic/env/hanabi/env.py)。共同结构是短 system 目标，user 中依次为 GAME RULES、PLAYER INFORMATION、RESPONSE INSTRUCTIONS。输出只选一个合法动作，并提供极短格式示例。Hanabi 的观察文本分别说明自己可见的伙伴真牌、伙伴对该牌所知范围，以及自己手牌的已知范围。它给的是游戏中可观测信息，不是要求模型自行从未解释的内部字段辨认视角。

[原版 env_manager.py](https://github.com/thu-nics/MARSHAL/blob/main/roll/agentic/rollout/env_manager.py) 还按回合标注是谁行动，分别放置状态、合法动作和历史选择。配置会影响展示哪些对手回合信息，不应泛称所有配置均只显示对手动作。其 answer 标签协议不改回我们已放弃的纯文本方案。

本地阅读入口：roll/agentic/env/hanabi/env.py 的 _get_prefix_prompt / _render_text；roll/agentic/env/kuhn_poker/env.py 同名函数。本地 env_manager.py 另有大量项目修改，以上对原项目的判断以远端原版为准。

### SocialRL

核验 [原论文 §3.1、§5.4](https://arxiv.org/html/2608.13787v1)。没有找到可核验的完整逐字 prompt 或公开 prompt 源码，因此不能给出所谓“SocialRL 原始完整模板”。论文说明事件按接收者过滤，区分已经发生的观察与要求当前决策的通知；接口接受动作定义。ToM 实验组织为 Infer → Act → Anticipate。单加该结构使 base 4B 的平均收益从 0.454 降至 0.353；训练该结构的轨迹才带来改善。可借鉴事件视角和动作/后果的区别，但对 P 仍应直接给 belief，不能照搬 Infer 步骤重新混入 B。

## 对当前 prompt 的具体建议（我们自己的设计）

1. 把长段 RULES 切成编号规则：目标如何达成、偏好如何计分、承诺何时生效、动作消耗哪次机会、终止条件。不要用“偏好决定目标是否达成”之类模糊合并表述。
2. 明确身份与当前任务：名字、B/P、提案或响应。使用全名承诺 Alex.Cedar / Blair.Cedar 解释归属，但工具参数仍由 self_commitments / partner_commitments 分开承载。
3. 统一信息入口，在同一玩家/目标位置标明内容、来源和可见范围。不要让 public_preferences、private_results 和 current belief 看起来像三个相互竞争的世界状态。P 的给定 belief 是当前状态；公开信息只是其中的公共部分。
4. 已生效承诺和可选择承诺分别展示且解释其不同。可以把状态字段写成短自然语言清单或小表格；保留数据结构用于内部存储，不要求题面必须整段 json.dumps。
5. 历史逐事件写“谁做了什么、结果是什么、谁看到了”，保留 imposed setup / voluntary 以及 B 的旧/新证据边界。不能把报价视为成交，也不能把环境设置视为动机证据。
6. 明确剩余提案顺序包含当前机会及其响应，并可展示本人此后还有几次提案机会。这是由公开轮转机械计算的事实；不直接提示该题是否应该调查，不删除合法但无价值的查询。
7. B/P 共用规则与状态渲染，任务要求分开：B 形成/维持/更新集合与 favored；P 直接使用已给 belief 选动作。不要求 P 再形成 B，也不强迫每条回答输出长的分步模板。
8. 每次只注册当前阶段的真实工具；给独立、短小的参数格式示例。格式示例不夹带被测题答案或某动作恒优的暗示。teacher 的伙伴规则是任务假设，要明确自己的收益优先与平局处理，不能用一句“理性”替代。

## 输入框架（最初结构草案）

```text
SYSTEM
你正在参与一个关于绑定承诺的谈判游戏。
根据当前任务完成 belief 判断或选择行动，简短解释并调用一个指定工具。

GAME RULES
1. 达成条件：目标要求的所有承诺都已生效时，目标达成。
2. 收益：每个已达成目标分别按每位玩家的偏好计分；未达成为零。
3. 报价与成交：OFFER 提出双方各自的新承诺；ACCEPT 才使其生效。
4. 时序与动作成本：逐项说明 OFFER/响应、PASS、INVESTIGATE。
5. 信息规则：每人知道自己的偏好；调查结果真实且仅调查者可见。
6. 游戏结束与伙伴策略：准确写出实际约定。

YOUR ROLE AND CURRENT TASK
你是 {player}。当前任务为 {B formation/maintain/update 或 P proposal/response}。

GOALS AND COMMITMENTS
逐个目标列出所需的“玩家.承诺”。
分别列出已经生效的承诺和仍可新增的承诺。

YOUR CURRENT INFORMATION
按玩家和目标列出已知事实，并标明 public/private 来源。
P：另列给定的未决候选或定性判断；明确这些都是你当前已经掌握的信息。
B：不给待推断答案；维护/更新题仅给正确旧 belief。

OBSERVED HISTORY
按事件列出 actor、行动、发生的结果和可见范围。
区分环境设置与玩家自主行动；维护/更新题区分旧历史与新证据。

CURRENT DECISION
当前提案/待响应报价；剩余提案顺序；本人剩余调查额度。
B：明确只判断指定玩家的指定偏好。
P：明确使用当前 belief，选择当前阶段的一个合法动作。

TOOLS
本阶段实际注册的工具、参数含义和最短格式示例。
```

这份草案只改变表达的组织方式。没有额外给最优动作、反事实收益表或 teacher 的隐藏权重。是否改善需要保持同题、同标签的小规模对照，不能把来源于其他项目的写法当作已经验证有效。

## 实施记录：bp-readable-prompt-v1

- 规则与题面渲染：`training/b_sft/social_prompt.py`。它只接收既有可见信息投影，不读取 teacher。
- 接入位置：`training/b_sft/social_named_probe.py` 的 `request(..., arm='action_tools')`。B 使用 SUBMIT_BELIEFS；P 使用实际动作工具。
- 完整 API 输入预览：`new/local_data/social_runs/bp_readable_prompt_review_v1/prompt_examples.md`。包含 B 行为排除、favored 维持、私有调查结果、调查与最后机会的对照、certain/unlikely，以及一份完整重命名短教学输入。
- 已知事实合并展示并保留来源；P 的给定 belief 明确属于本人当前掌握的信息。历史分别说明提议与成交，并保留 setup/voluntary、旧/新证据边界。提案顺序明确包含当前机会，同时机械计算本人后续机会数。
- P 内部题型名称不进入题面；不提示该题应该调查还是成交。合法但无价值的调查仍保留。短教学的题目也使用同一渲染器。
- 与前一版 `bp_action_tools_review_v1` 的 75 个条件逐一比较：原始 input、teacher、教学例子选择、工具名称与参数 schema 均相同；B 工具说明文字有简化。73 个可评分条件的 gold 提交全部通过，另 2 个定性信息不足条件仍不强判对错。
- 本次没有运行真实模型或更新参数。prompt 是否改善理解和提交一致性，仍需后续同题小规模采样检验；这次不据此宣称能力已改善，也未解决题目覆盖问题。

## 用户审阅后的精简版：bp-readable-prompt-v2

当前完整题面入口：`new/local_data/social_runs/bp_readable_prompt_review_v2/prompt_examples.md`。上一版保留用于对照。

- system 只说明游戏身份、简短解释与一次工具调用。删除禁止数字置信度、checkpoint、不续写工具结果等提醒。
- 模型题面不出现 B/P、formation/maintain/update 类别；内部分类仍用于分析。名字继续使用既有固定映射和重命名对照，本次没有增加随机命名机制。
- 目标要求改成“玩家 to commit to 承诺”的句子，短教学解释也去掉点号写法。
- 事实逐条说明内容和可见范围，删除 Source 多重标签与抽象信息解释。P 的当前 belief 单独呈现，保留其取代初始分布或条件化初始分布的区别。
- investigate 只给一般合法范围、真实私有结果与机会成本，不在规则中提示“已知／无关”这类策略分类。
- 历史用 starting event provided by the task 和 chose to 区分预设事件与玩家选择；保留旧／新证据边界。没有改变事件本身。
- 保留初始分布、生成约束、伙伴自身收益优先／利他平局／剩余并列等概率选择，以及伙伴可用的信息。删除 solver 初始化与迭代术语。遇到未审阅的伙伴规则、生成规则或 belief 描述时，渲染器拒绝静默套用当前文案。

验证：25 项测试通过；75 个条件的 input、teacher、工具定义与教学例子选择均与 v1 相同；73 个可评分标准答案通过，2 个定性歧义条件仍不强评分。检查覆盖了全部请求，包括短教学内容中的旧措辞残留。

限制：这证明了接口与既有标签的一致性，不证明所有符合简化行为规则的策略都会产生相同标签。teacher 的固定策略选择记录仍保留在本地；跨策略标签稳健性仍需单独审查，不能靠 prompt 中写出求解算法宣称已解决。本次未运行模型或训练。
