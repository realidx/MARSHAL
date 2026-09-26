# 分层 O/B/P 诊断

目的：把可理解的证据更新与行动后果分开检查，再比较 belief 干预；不按 Q0/D 的输赢选题。

当前冻结27题：直接反馈3题、一步排除8题、一步有歧义8题、多步更新8题；共108次调用。repair-sensitive 13题、action-control 14题。多步来自4个来源，每个最多2题。直接反馈仍使用原生6目标场景，简单的是证据链，不声称整个行动题更简单。

## 层次

- direct_feedback：实际私人调查明确返回目标偏好。基础信息读取检查。
- single_elimination：只有一次伙伴选择提供信息，正确可能集合缩小。
- single_ambiguous：只有一次伙伴选择提供信息，仍保留所有偏好，但支持程度发生变化。
- multi_update：至少两次伙伴选择分别改变 teacher 的信念；自己的接受不算新的伙伴证据。生成器在较小原生行动空间中搜索，以避免靠扩大战略树堆难度。

每题保留 B/O/P_gold/P_model 四种条件，P 使用标准训练渲染器。B/O保留明确的初始状态与自然事件。初始绑定不是伙伴行为。P不接收历史或数值posterior。

`evidence_trace` 保存每个事件的行为者及前后信念，供审查；这些数值不进入模型请求。每题通过原生转移/终局收益核验、定性belief充分性检查以及移除历史后的 continuation 一致性检查。它们是规则和标签验收，不等于已验证模型可学或已掌握。

## 报告

repair-sensitive 与 action-control 为两个独立主面板，各自给出 O/P 正确率、regret及配对repair gain。整体只作描述，不用于单独宣称机制。B分别给出possible set、favored、联合正确率，无效输出算错。另按证据层次及层次×作用类型列出结果。

注意 action-control 沿用原资格定义：没有与gold接受集合不相交的单点偏好反事实；不意味着所有偏好下动作价值完全相同。两面板的分母及无效输出均保留。

## 生成与运行

```bash
python -m new.diagnostic_v8.build
python -m new.diagnostic_v8.freeze
python -m unittest new.diagnostic_v8.test_suite
python -m new.diagnostic_v8.experiment --base-url http://localhost:8000/v1 --model MODEL --checkpoint-hash HASH --output runs/diagnostic_v8/MODEL --max-tokens 4096 --concurrency 4
```

使用相同batch-invariant服务配置。旧v7/v7p不覆盖。题数、各层和两主面板数量以manifest为准；不将相同来源的变体宣称为独立结构。未运行LLM测试，不能承诺D提升。
