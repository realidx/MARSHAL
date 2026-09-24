# 两人短交互与 B 修正候选版

这是独立候选实现，未替换当前训练入口、数据 manifest、奖励或 checkpoint 设置。尚未完成 GPU trainer 接线和真实模型验收，不能当作已可启动的 D 配置。

## 短交互实际做了什么

- 从 compact_bank_200 的 O 题恢复原生 BENAC 状态、私有信息和原 teacher 策略。两人局，只训练一个 ego，伙伴使用固定 teacher，不加载其他语言模型。
- 模型真实选择动作；原生执行器推进状态，伙伴在其信息集内回应，再生成下一次模型请求。调查结果只给调查者，所有分支均遵守原生规则。
- 当前题起点之后，最长允许 2–3 次 ego 决策。可以提前自然结束；不强迫凑足三步，也不截断后用 teacher 估值冒充终局奖励。
- 使用原生行动工具和历史提示接口。模型请求不包含 teacher 值表、实际隐藏世界或正确 belief；删除静态单题的 0.1 argmax 容差说明，明确按终局个人收益评价。
- 同一起点生成 8 条轨迹，各自抽取与 ego 可见证据一致的隐藏世界。组内标准化的是整条轨迹的终局收益，不能把各决策分别算成独立单题 advantage。
- 固定伙伴复用原 teacher 的 off-policy 分支策略。这是受控策略伙伴，不代表真实人类或任意 LLM；运行时检查同一伙伴信息集内的动作分布一致。

资格审计：200 个 parent 中，66 个通过（55 个最长两次 ego 决策、11 个最长三次），103 个剩余机会不足，28 个不是两人局，3 个历史无法按所记录 teacher 重建，排除并保留原因。不能将这三题直接判为坏标签。

每个通过场景回放 8 条随机合法工具动作，检查 prompt、工具解码、状态转移、私有信息规则和自然终局；这不是模型学习信号验收。详情见 `qualification.json`。

接口：

```python
from training.social_mixed.short_interaction import ShortInteraction, collect_group
# task: qualification.json 中通过的现有 O task
window = ShortInteraction(task, seconds=10, max_nodes=30000, max_sweeps=128)
group = collect_group(window, complete, seed=42)
# complete(request) 返回 {raw_message: ..., finish_reason: ...}
```

collector 保存逐步请求和回答、整条轨迹收益。非法/截断输出明确返回失败，不补采、不假造终局收益；有失败时不输出可直接使用的组 advantage。接 GPU trainer 前仍需实现协议损失分支、跨决策 response mask/sequence 聚合、行为 log-prob 保存与恢复。这些是尚未完成的工程工作。

## B：重新核查了什么、改了什么

按同一 task ID 合并 0–124 步两段 calls。全部 4,000 个 B 回答：1,954 正确、645 合法错误、1,357 截断、44 其他无效。出现三次且从未正确的 20 题共 480 个回答：319 截断、157 合法错误、4 其他无效。157 个合法错误中，146 个 support 集合不对，125 个 favored 不被接受（两者重叠）。

20 题涉及：9 个单行为不确定性、4 个单行为排除、4 个多事件、3 个先验/公共条件题。因此“全是复杂历史题太难”不成立。逐题统计在 `b_failure_audit.json`，原始 prompt 与回答摘存于可重建的 `b_failure_examples.json`。

代表性语义错误：

- `48c9a64f717e2f934c0a-B`：正确保留三种可能，却把 50% neutral、25% want/avoid 的背景误当成同等支持，输出 undetermined。
- `0c1b45de0c673e8ed02b-B`：因“没有明确避免的证据”排除 avoid，尽管其背景支持最高。缺少陈述不是排除证据。
- `b30b2f20f54a421d7d02-B`：把已知喜欢 Orchard 当作不喜欢 Harbor 的依据，凭空引入目标互斥。
- `82506d3761b51b5ea4fc-B`：从提议包含 Cedar 直接推出喜欢 Orchard，忽略回应及整个决策后果；teacher 保留三种可能。
- `51576f22eeebf9637bad-B`：一个回答文字结论是 only avoid，实际工具提交却是 avoid+neutral。长解释也没有保证最终答案一致。

候选 `training/social_mixed/b_direct_candidate.py` 保留旧模块名，但已恢复原来的“先简短解释，再提交一次 SUBMIT_BELIEFS”要求，系统和用户提示均保留。1,024 上限、工具 schema、标签、exact support、favored 0.1 容差不变。不再提供取消解释的候选。

唯一保留的候选改动是通用语义澄清：喜欢多个目标不互斥；没陈述不等于 avoid；背景支持与不可能不同；行动涉及目标不直接等于喜欢该目标，须看完整后果及既有选择规则。`clarify_semantics=False` 返回完全相同的原始请求。

这些修改不加入答案、额外任务或数值输出要求，也不放宽 support。**没有证据证明已经解决 B 的语义学习或截断问题**。截断需在保留解释的前提下继续处理；尤其按隐式策略推导精确 support 仍可能超出当前模型的可靠能力，不能靠更多解释文字宣称已解决。也不据三次失败直接删除这些题。

## 复现

```bash
python -m examples.social_mixed.short_interaction_v1.audit
python -m examples.social_mixed.short_interaction_v1.audit_b
python -m unittest examples.social_mixed.short_interaction_v1.test_candidate -v
```

audit_b 读取本地已有两份 calls 压缩包，不调用模型。B 的下一项必要实测是对相同失败题比较原提示与保留解释的语义澄清提示；分别看提交率、support 与 favored，而非只比较总 reward。尚未提交此实测或训练任务。
