# L0 逐条失败复核

分析对象：`new/local_data/social_runs/social_probe_20260915/bridges-selfplay-g16-20260914-133728/bridges/samples.jsonl` 中 4 道 L0 × 8 次。逐条阅读全部 32 次回答；未重新调用模型、修改题目、prompt、奖励或训练配置。

## 结论

L0 的低分主要暴露了时序重建、ALL_OF 收益计算、身份归属和候选约束的组合困难。当前“L0”只是生成器按 `mode == binary` 分配的结构标签，并非 base model 已验证的基础难度。短 horizon 降低了搜索深度，却没有把这些基础能力隔离开。

所有 4 道题来自同一个 `shared_partner_commitment:binary` 家族，且都在 train；不能把 0/32 当作整个 L0 库或 validation 的独立估计。完整库的 12 道 L0 中，共享结构 6 道在 train，disjoint 结构 6 道在 test。本轮未采样 test。后续不能把已有 test 家族移入训练，或仅改名后用于调参。

## 分题结果

| 题目 ID | 内容 | 正确标签 | 截断 | 已提交的错误答案 |
|---|---|---|---:|---|
| `34da1223fa394d51c38f` | 接受目标报价，形成 belief | `[want] / want` | 6/8 | 2 次 `[neutral] / neutral` |
| `ee0c38cd5b14b726d4bf` | 拒绝同一报价，形成 belief | `[avoid] / avoid` | 8/8 | 无完整提交 |
| `e4e9396536f45f0de445` | 给定 `[want,avoid]`，接受后更新 | `[want] / want` | 3/8 | 4 次原样保留旧 belief；1 次全集 / undetermined |
| `fdcef144ef63d8c67397` | 接受另一目标报价，维持 belief | `[want,avoid] / undetermined` | 8/8 | 无完整提交 |

合计 0/32 正确，25 次截断，7 次合法但错误的提交。4 个八次奖励组均全零。7 次完整错误提交中只有 1 次是全集，因此 L0 的失败不能全部解释成“喜欢输出全集”；不过行为证据被误读成没有信息，会导致保留旧 belief 或扩大集合。

## 正确推理实际需要做什么

观察者是 Blair，判断 Alex 对 Harbor 的偏好：

- Harbor 要求 **Blair Maple AND Alex Maple**。
- Orchard 要求 **Blair Willow AND Alex Maple**。
- 已知 Blair neutral Harbor，两人都 want Orchard。
- 每个目标至少有一位非 neutral 玩家，因此 Alex 对 Harbor 的合法先验只有 want/avoid。
- 提案前两人都没有承诺。PASS 与 OFFER 是题目提供的起始事件，不提供行为证据；只有最后的 ACCEPT/REJECT 是自愿选择。
- 最后一次响应之后没有未来机会，必须比较接受和拒绝的终局效用。

目标报价是两人都加 Maple，接受只完成 Harbor，不能完成 Orchard：

| Alex 对 Harbor 的偏好 | 接受后 Alex 总效用 | 拒绝后 Alex 总效用 | 选择 |
|---|---:|---:|---|
| want | +1 | 0 | ACCEPT |
| avoid | -1 | 0 | REJECT |

维持题报价是 Blair Willow、Alex Maple，接受只完成 Orchard：无论 Alex 对 Harbor 是 want 还是 avoid，接受总效用都是 +1，拒绝都是 0。两种类型都接受，故保留旧 belief，favored 仍为 undetermined。此处没有需要求解的残余动作平局。

本次再次对 4 道题调用 `build_b_response_bridges.verify_task`：独立 backward、原生状态/收益、最终响应证书、旧 belief 和 posterior 均通过。记录在同轮 `local_analysis/l0_label_checks.json`。

## 具体错误链

### 1. 把接受后的状态投射回接受前：目标接受题至少 14/16 次

形成 ACCEPT 的 sample 0、1、2、3、6、7，以及更新 ACCEPT 全部 8 次，都明确说接受没有新增承诺。统计只包含明确表述，不将模糊的“already binding”一律计入。

更新题 sample 0：

> The offer was: Blair would add Maple (already binding), and Alex would add Maple (also already binding). This offer bound nothing new, but Alex accepted it.

随后推论“任何偏好都可接受，所以没有信息”，最终返回全集。更新题 sample 1、2、4、5 则据此保留旧 belief。sample 6 甚至正确推出了 neutral 不合法，仍因时序错误无法排除 avoid。

实际题面先列当前承诺，随后列历史；历史明确写了 `New binding commitments: Blair: Maple; Alex: Maple.`。这是模型没有正确重建决策前状态，不是上传状态或标签错位。当前证据不能证明只换展示顺序就能解决，也不足以据此认定 prompt 有机制缺陷。

### 2. 将共享的必要条件误当作足够的收益理由

拒绝题的回答反复认为：Alex want Orchard，而 Orchard 需要 Alex Maple，所以 Alex 应接受任何包含 Alex Maple 的报价。

拒绝题 sample 1：

> So if Alex were to add Maple, they would achieve Orchard.

拒绝题 sample 3：

> if Alex wants Orchard, they would be expected to accept an offer that includes their commitment to Maple.

这忽略了 Blair 必须加 Willow；实际报价加的是 Blair Maple，而且没有未来回合。模型于是人为制造“Alex 明明 want Orchard 却拒绝”的矛盾，反复怀疑已知偏好、引入动机，直到截断。

维持题中也出现相反方向的过度排除：sample 3、4、7 因 Harbor 未完成，就把“没有表现出追求 Harbor”当成不 want Harbor 的证据；sample 5 在正确保留两个候选后，又把 avoid Harbor 等同于不肯承诺 Maple，反复推翻结论。这说明还必须学习“动作相同而收益影响不同”和无关证据下不更新。

### 3. 身份归属与合法先验没有稳定掌握

形成 ACCEPT 唯一的两次完整提交（sample 5、6）均把 `You are neutral about Harbor` 归给 Alex，最终提交 neutral。题面已明确 `You are Blair`。sample 7 一度出现同样错误，后来自行纠正。

其他回答常保留 neutral，未应用“每个目标至少一位非 neutral”的约束。即使更新题直接提供正确先验，也不能保证保留约束：sample 0 又加入 neutral。形成题实际上需要先做全局生成约束推理，再做行为排除；这不是单纯的二选一题。

### 4. 截断大多伴随未解决的逻辑错误

25 次截断中，按“在新证据后明确写出完整 gold 集合与 favored，而非仅复述旧 belief”的标准，只有拒绝题 sample 5 出现完整正确答案的文字表述，但没有工具提交。

它先写出 `[avoid] / avoid`，又重新讨论 neutral，最后回到正确答案。不过其理由仍错：声称 neutral 类型会因 Orchard 而接受，没有正确排除非法 neutral 世界。不能将这条算作可靠的正确 reasoning。

其余有局部正确推理，但没有稳定完成正确判断。例如维持题 sample 5 得到正确候选集合后又错误排除 avoid；拒绝题 sample 4 开始写工具 JSON 时仍然选择全集。增加长度并不保证修复这些错误。

## 对数据优化的含义

1. 当前 L0 不宜直接承担课程入口。需要分别验证身份/先验、前后状态、单目标收益和行为排除，然后再加入共享动作；层号应由这些能力和重复采样表现共同决定。
2. 独立构造新的合法 train/validation 教学家族，优先让一个目标的收益变化清楚、其他目标贡献固定，并覆盖接受→want、拒绝→avoid、无关行为→保持集合的对照。保留共享结构作为后续难度，不把已有 disjoint test 改名搬入训练。
3. 给定正确旧 belief 的题可以隔离先验推导负担，但本轮更新题 0/8 已说明：只给两个候选不足以解决时序错误。新题需要验证收益变化是否确实被模型理解，而非仅看输出集合大小。
4. 保留合理的维持题，但提高真正行为排除题获得混合奖励组的机会。不能只增加全集负例数量：本轮 L0 连正确的双元素维持题都未提交成功，首先缺的是可产生正例的基础行为推理。
5. 下一轮继续原生工具、二元奖励、1024 输出预算、不 retry；固定其他条件，用少量题独立重复采样检验新入口是否出现正确排除及组内奖励差异。当前结果提示风险，不证明训练后必然输出全集。

逐条人工笔记及完整原文：同轮 `local_analysis/l0_manual_review.json` 和 `local_analysis/l0_responses.md`。人工错误标签为诊断记录，不改变训练奖励；未将每个标签解释为互斥或因果贡献比例。
