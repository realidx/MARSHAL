# 仅回应 offer 时使用利他平局规则

用户决定：仅在回应其他玩家的 offer、ACCEPT 与 REJECT 的自身预期终局收益相同时，比较其他玩家的预期终局收益总和。主动 OFFER、PASS、INVESTIGATE 不再使用利他平局；自身收益最优的残余并列动作均匀随机。最后一次响应之外，仍比较完整后续游戏的预期收益，而非即时新增收益。

## 实现

统一规则为 `training/b_sft/decision_policy.py` 的 `response-only-altruism-v1`。更新当前 private/full-terminal teacher、随机平局窗口 teacher、B oracle、P 可接受动作和 qualitative LP 的阶段条件，以及独立 backward 核验。增加 teacher/prompt 版本。响应节点保留原收益比较，提案节点只比较自身收益；全局 own-utility 偏离检查不再把其他玩家收益改善作为偏离成立的条件，稳定策略检查仍执行。

B/P 英文题面声明这一差异。Self-play 使用 `training/social_mixed/policy_prompt.py` 在保留的全局游戏呈现上加入新目标说明。真实随机初始局、原生动作和自身终局 reward 均保持原语义；self-play 不执行 teacher，也没有利他额外 reward，所以这条平局偏好是模型指令，不能声称被 reward 强制实现。

历史数据、下载的模型结果和 frozen runtime 不重写。新的混训启动检查拒绝旧 objective 或尚未 training_ready 的 B/P 数据，发生在模型初始化前。旧实验的得分不能直接解释成新规则下的表现。

## 数据迁移结果

源：`examples/social_bp/data_two_a100_v1/tasks.jsonl`，411 题（含 train/validation/test；本次仅 CPU 重算标签，没有对 test 调用模型）。保留原 split 和 family。

新目录：`examples/social_bp/response_only_v1/`。

- 403 题完成重新求解、原生收益核验和标签生成；332 题另外通过适用的独立逐世界 backward 对照，其余不把逐世界最优冒充信息集最优。
- 25 道 B 标签变化：train 18、validation 3、test 4。
- 45 道 P 标签变化：train 31、validation 8、test 6。
- 8 道 P 现在所有合法动作均可获奖：train 4、validation 3、test 1；不能继续贡献有效训练配额。
- 8 道调查 P 出现同步最佳响应循环：train 5、validation 2、test 1。逐题 ID 和异常保存在 migration.json。没有悄悄重用旧标签，也没有改用其他求解顺序作为隐式 fallback。
- 循环仅说明当前流程未产生标签，不说明这些游戏无解。此处是监督教学标签迁移，不对 outcome self-play 做求解器筛选。

新任务包含 previous_task_id、objective_version、新 policy hash，重新生成 previous belief、B posterior 或 P acceptable actions。迁移目录不是最终课程：全部 training_ready=False。8 道无标签题与 8 道退化题仍需在后续数据组装中明确处理，不应把 403 题直接宣布为完整可训练数据包。

## 最新 11 道对照

`examples/social_bp/b_response_only_controls_v1/`：11/11 完成新规则核验，答案全部不变。因为前置 PASS/OFFER 都是 imposed，唯一自主证据是最终响应，此处仍采用利他平局。旧 88 次采样保留为旧措辞的实测，不能声称新 prompt 已经调用模型。

## 验证

40 项 CPU 测试通过：新规则的提案/响应差异、损己不能被利他覆盖、残余并列、private solver 的实际混合概率、LP 的阶段区别、B bridge 标签、terminal teacher，以及 mixed rollout 接口/原生终局与私有调查检查。未跑 GPU、未启动训练、未操作服务器。

复现迁移（CPU）：

```bash
python -m training.b_sft.migrate_response_only \
  --source examples/social_bp/data_two_a100_v1/tasks.jsonl \
  --output examples/social_bp/response_only_v1
```

存在未解决的求解循环时命令非零退出，同时保留完整迁移清单。不得以退出失败为由删除 self-play 的复杂初始局。
