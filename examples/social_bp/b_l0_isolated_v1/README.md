# L0 简化候选包

首测文件是 `requests.jsonl`：6 题，train / validation 各 3 题，每题独立 8 次，共 **48 次调用**。尚未采样或合并进完整训练集。

| 证据 | 正确旧 belief | 新答案 |
|---|---|---|
| 接受只完成被询问目标的报价 | want / avoid，undetermined | want，favored want |
| 拒绝同一报价 | want / avoid，undetermined | avoid，favored avoid |
| 接受只完成另一目标的报价 | want / avoid，undetermined | 保持两个候选，undetermined |

相对旧 L0，两个目标不再共享任何承诺，首测统一提供正确旧 belief。模型先学习用行为更新或维持，不必同时推导生成约束。`formation_requests.jsonl` 另存同场景去掉旧 belief 的 6 题，用于后续核对；首测不混入。

每个目标仍至少涉及两名玩家。保留原生最后响应、ALL_OF、teacher 规则、原生工具、二元奖励、1024 输出预算；不增加答案 retry 或长度惩罚。起始 PASS / OFFER 仍是合法的教学设置，不计作行为证据。前后状态展示不变，时序推理仍需要模型完成。

为保留原 test 的 disjoint 家族，使用新的有效前置条件组合：train 被询问目标有两个前置承诺，背景目标三个；validation 两个目标各三个。所有额外承诺都参与目标，每人最多增加两项承诺是原生配置参数。不是改名复制 test，也不是添加无关动作。

这减少了共享动作和先验推导负担，但增加了部分目标的前置条件数，因此只称为简化候选，不能预先认定成功率提高。两个 split 各只有一个结构家族，validation 测结构迁移；不能据此声称已有充分独立性或平滑课程。

- `review.md`：全部 12 道实际题面及分开的本地收益证书，供人工审核。
- `tasks.jsonl`：本地标签，不能发送给模型。
- `audit.json`：12 题独立状态、收益、先验与 posterior 核验；与历史数据家族无交集及来源哈希。
- `probe_manifest.json`：首测 6×8 及请求哈希；形成题另计。
- `curriculum_candidate.json`：新入口及验证 IDs，旧非 test L0 延后名单；尚未修改正式课程。

生成器：`training/b_sft/build_b_l0_isolated.py`。本地检查：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src /private/tmp/social_native_tools_venv/bin/python -m unittest training.b_sft.test_b_l0_isolated training.b_sft.test_b_response_bridges
```

后续用冻结二元奖励分别检查：三类题正确率、组内混合奖励、截断、复制旧 belief、错误全集，以及解释是否真的比较了接受/拒绝效用。只有更新题开始产生正确排除，才支持将该包作为 GRPO 的课程入口。
