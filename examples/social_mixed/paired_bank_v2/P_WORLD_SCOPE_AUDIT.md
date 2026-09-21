# P 世界集合来源审计（2026-09-22）

结论：497题全部通过本次世界支持覆盖检查。没有发现teacher世界集合排除了P可见定性支持所允许的世界。本检查不修改标签、P训练资格或正式训练就绪标记。

## 逐题检查方法

从实际P任务的自身偏好及所有伙伴/目标的 `possible_preferences` 构建笛卡尔积；不使用旧历史、私人调查、公开偏好源记录或背景prior筛选。这个集合允许任意相关性，并且尚未用favored缩小分布范围，因此是实际定性belief允许世界的保守上界。

与 `labels.worlds` 相交，再检查有无遗漏；同时检查原posterior是否在可见支持内、被删除的公开偏好事实是否已经由可见支持蕴含。actual_request_sha256绑定每题实际P渲染请求。摘要记录数据manifest与审计脚本hash。

结果：

- 497/497题：可见支持笛卡尔积全部包含于teacher世界集合。
- 0题：源posterior在可见支持之外有超过1e-9的概率质量。
- 0题：被删除的源公开偏好事实未被可见支持蕴含。
- 49题：LP允许集合仍含源posterior概率为零的世界。未简单按历史后非零posterior筛掉所有零概率世界。
- 314道实际P训练资格题中，0题因本项世界遗漏而需要重新隔离。

## 约束来源

1. `training/b_sft/debug/audit_readable_pretraining.py::reconstruct`：根据源公开偏好、每人至少want一个目标、每个目标不能所有人neutral生成世界及类型目录。这些生成条件没有直接显示在P提示里，但本次逐题检查表明它们没有在可见支持笛卡尔积之外额外排除世界。
2. `training/b_sft/social_private_teacher.py::PrivateEpisode`：setup应用于初始状态，随后建立tree；`observe`更新历史权重及节点索引，不直接改写tree.worlds；`_weights`结合自身偏好和私人结果形成源posterior。
3. `training/social_mixed/reasoning_bank.py::labels`：保存tree.worlds，而不是只保存非零posterior世界。
4. `training/social_mixed/audit_qualitative_cases.py::cells`：LP在存储世界上使用自身偏好、可见边缘支持筛选，并按可见favored构造分布约束；不另用历史似然或私人结果过滤。
5. `training/social_mixed/history_free_requests.py::request`：P仅渲染当前状态、自身偏好、定性belief和行动规则；世界覆盖检查以其使用的semantic_beliefs为依据。

## 未认证的部分

这不是“所有P标签完全无歧义”的新证明。既有LP对固定per-world continuation payoff表做重加权；多步题的后续伙伴策略、信息分区或价值表可能依赖源历史，即使world support完整也不能排除这类依赖。要认证整个P输入充分性，还需单独审计或重算这些后续策略。也没有在本次重新认证浮点严格边界和所有奖励容差。

## 复现

```bash
python -m training.social_mixed.audit_p_world_scope
python -m unittest training.social_mixed.test_p_world_scope -q
```

结果为 `p_world_scope_audit.jsonl` 和 `p_world_scope_summary.json`。两项测试通过，包括人工删除一个可见世界后必须报告遗漏的反例测试。
