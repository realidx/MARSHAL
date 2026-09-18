# Reasoning v5 candidate：预算内重分配与 linear 历史关联题

此版本取代此前“额外追加练习组”的候选方案。本轮提交入口默认选择此包（B/P-only 与 SP-only）；本地没有启动模型训练。底层历史工具的默认 v3 不变。

## 采样：替换，不再追加

B/P-only 的一个任务组仍为同题 8 个 replica。每一步的任务组上限，逐步取自冻结的 v4 原采样计划。新采样器在此上限内选择完整题组：优先轮换基础题、同历史 B/P、缩集题、调查结果利用，再按历史曝光补充其他完整对照组。无法容纳的组延后，不截断对照组。

同历史练习组包括独立 B 判断、原始历史 P、正确联合 posterior 下 P。各自独立调用，不把模型 B 答案传给 P。所有出现 P4 的批次都保留该调查／不该调查控制题。旧难题没有删除。

固定 seed=42 的实际采样函数审计：

| 更新步数 | 任务组数 | 原 v4 上限 | 覆盖题数 |
|---|---:|---:|---:|
| 50 | 441 | 441 | 336/594 |
| 194 | 1831 | 1831 | 594/594 |
| 512 | 4933 | 4933 | 594/594 |

194 步时，基础题每题出现 12–13 组、同历史练习成员 5–7 组、缩集配额题 4–7 组、结果利用题 6–7 组。这是调度曝光，不是有效梯度；实际训练可能因 token 预算更早停止。

**任务组数量不增加，不代表实际 token 消耗完全相同。** 题目的输入长度和模型输出长度仍不同；本次没有修改 token 上限、奖励、优化器或截断处理。

## Linear 历史关联题

在预先固定的 32 个小局候选上按原生规则搜索，并保持原有结构分区、排除正式 A 的保护几何。只接受 teacher 收敛且历史改变可接受动作集合的节点；求解循环记录为不可用，不生成标签。不参考任何模型答题结果。

- 训练：5 个决策点、2 种几何，各配 B、原始 P、oracle P，共 **15 题**。
- 开发：8 个决策点、3 种几何，共 **24 题**；与训练几何隔离。
- 训练总数由 579 增至 **594**，开发题库由 471 增至 **495**。
- 所有新增点从可见输入重新构建 teacher 并回放历史，检查动作价值、前后可接受动作、B 标签和工具评分。
- 5 个训练点的前后可接受动作集合均有交集；开发中 3 个点完全不相交。不能说训练题全部“忽略历史就必错”。

周期验证保持 **45 道 B/P＋8 局当前模型 SP**。在原 45 题中替换完整题组，加入一个 linear B/raw-P/oracle-P 三联组，保留原诊断类别覆盖。正式测试未修改；没有加载 Q0。

SP 延续上版候选设置：108 个 reset 全部保留，以初始总提案机会 ≤6／7–9／≥10 分档，完整调度周期的入场比例为 50%／25%／25%。此轮没有进一步修改 SP；该比例不是 token 或梯度比例。

## 验证与使用

```bash
python -m training.social_mixed.search_linear_history_v5
python -m training.social_mixed.prepare_reasoning_v5
python -m training.social_mixed.audit_reasoning_v5
SOCIAL_DATA_DIR=examples/social_mixed/data_reasoning_v5_candidate \
  python -m training.social_mixed.preflight \
  --output examples/social_mixed/data_reasoning_v5_candidate/preflight.json
python -m unittest training.social_mixed.test_curriculum_sampling
```

构建依赖 v4 候选包与已审核的 16 道基础题。训练时需显式设置 `SOCIAL_DATA_DIR`；改变数据与采样应记为新实验。`exposure_audit.json` 保存重求解证据和曝光统计，`linear_history_search_audit.json` 保存候选搜索结果。

当前工作只证明数据和采样一致性，未证明学习改善。截断、grounding 和真实模型的错误轨迹诊断尚未处理；不将它们归因为数据量不足。

## 本轮训练入口更新

训练及开发请求使用简短的目标表列名澄清。step 0 开始验证，保存 best 与 last；选择规则与提交命令见 [FULL_TRAINING.md](../FULL_TRAINING.md)。本轮不运行 Mixed。
