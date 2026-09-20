# B/P 缺陷、耦合与决策价值：第一版

本版只围绕三个问题，不另加泛化/内部机制证明任务：

| 要回答的问题 | 数据与输出 |
|---|---|
| B、P 单独是否有缺陷 | v2 开发集分项；本版 B posterior 误差和 correct_B_model_P regret |
| B/P 是否耦合 | v2 P→B 机会成本/似然辅助对照；本版改变输入 belief 的配对规划 |
| 两者是否影响决策质量 | 下列四格修复比较，全部按正确 posterior 的期望自身 utility 评分 |

## 四格实验

| | 模型 P | 参考 P |
|---|---|---|
| 模型 B | model_B_model_P | model_B_reference_P |
| 正确 B | correct_B_model_P | correct_B_reference_P |

每个 case、每个 replica：
1. 模型看到原生历史，对唯一未知伙伴偏好输出 want/neutral/avoid 的完整概率分布。
2. 两个独立 P 请求分别获得模型 belief、正确 belief，使用同一当前状态、原生工具、推理预算及匹配采样 seed。P 不继承 B 的 reasoning，不看到可绕过 belief 接口的历史证据。
3. 参考 P 在同样的合法行动中按各自输入 belief 最大化自身期望 utility，精确平局均匀选择；无需模型调用。
4. 无论输入 belief 对错，四格全部按正确 posterior 和已认证逐世界 payoff 计算 utility/regret。

这是受控模块接口，不是训练部署必须采用的流水线。原生无辅助 P_infer 保留在 v2，不能把这里的模块化表现冒充完整 agent 表现。

只因为当前恰有一个未知偏好，其三元分布才是完整 joint belief。**不把 possible/favored 擅自转成概率。** 数值输出只用于本诊断，不改训练目标。B 以 total variation 报误差，不自设任意“数值完全正确”门槛；已有 v2 语义 B 分数另报。

保存四个修复差值：
- B_repair_gain：保持模型 P，把模型 B 换成正确 B 的收益变化。
- P_repair_gain：保持模型 B，把模型 P 换成参考 P 的收益变化。
- P_repair_given_correct_B：正确 B 下，模型 P 的剩余决策损失。
- B_repair_with_reference_P：参考 P 下，模型 B 的决策损失。

错误 belief 下的参考 P 可能更坚定地选择错误动作，因此 P_repair_gain **可能为负**，不能强行称为改善。报告所有值。参考 P 是指定 teacher 延续策略下当前决策的枚举参考，不是对任意 LLM 对手的全局最优策略。

## 当前题目和检查

复用重新求解并认证的一个 binary 结构，voluntary/preset 两个 case。物理状态、合法动作、逐世界 payoff 相同，证据意义不同，正确动作集合不相交。三个重复最多 18 次模型调用/模型。数值 B 与 v2 语义 B 不是同一个输出任务，分开报告。

P→B 仍使用 v2 的四个解析控制请求：理解伙伴备选方案的效用 → 得到行动似然 → 更新偏好。它不是自己调查的 P→未来 B，也不是长原生历史的逆向规划证明。

本版题目少，目的在于先把三个命题对应到实际可执行的测量。尚未跑模型，不能预写 base 有缺陷或 trained 已修复。单项题是开发题，组合题源自训练结构改编，均不称泛化测试。

五项 CPU 测试通过：正确 belief/action 通路、错误 prior 造成参考决策损失、B 截断阻断依赖格而不影响独立格、P 无历史证据绕过且工具一致、非法概率拒绝。正确 prior 反例只是设计有效性检查，不是模型结果。

## 运行

用户在已有模型端点上运行；代码不启动服务器。先运行 v2 单项与 P→B，再运行本版四格，输出目录分别保存：

```bash
python new/diagnostic_v2/run.py --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL --output runs/diagnostic/q0/components --repeats 3
python new/diagnostic_v3/experiment.py --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL --output runs/diagnostic/q0/repair --repeats 3
```

Q0/BP/SP 分别运行并匹配解码设置（temperature=1，top_p=1，4096 tokens，无重试）。总计最多 117 次调用/模型。四格结果在 repair/results.json，完整请求响应在 calls.jsonl，协议与冻结 manifest 在 protocol.json。

格式失败、截断不映射为虚构合法动作，utility/regret 为 null；被阻断的格单列。不得丢弃失败后只报完整四格均值；同时报告各格覆盖率与 B/P 协议失败。基础设施失败单列。独立采样的四格差异不证明模型内部存在对应的因果模块。

```bash
python -m unittest discover -s new/diagnostic_v3 -p 'test_*.py' -v
```

## 测量修订：PRO 审查后的约定

- 每个模型 P 格增加 `input_belief_planning_regret`：按它收到的 belief 衡量是否规划合理。真实收益仍统一按正确 posterior 计算。这能识别“错误推断与错误规划抵消”。
- `B_total_variation` 是指定行为模型下的外显 posterior 近似误差，不是广泛概率校准指标，也不代表内部真实 belief。
- 两种来源的 belief 通过同一函数、键序和 12 位有效数字序列化，不给正确/模型来源提示。
- 冻结动作集合和逐世界 payoff；输入错误 belief 不重新求解伙伴策略。本例是最后一次提案，无后续 focal 决策，不能逐世界偷选后续行动。
- 同一 belief 下两种历史来源的完整 P 请求、动作集合、payoff、reference 输出分布有 CPU 一致性检查。
- 每 case 报 `decision_gap`（精确最优与最好非最优的差），与原 P 的 0.1 近优容差分开。全动作并列则间隔为 null。
- 四格是两条修复路径，不能将四个 gain 相加或解释为责任百分比。B_repair_gain 和 P_repair_gain 都可能为负。正确 B+参考 P 与其余两个单修复格的差应非负。
- `interaction_gamma` 为 U11−U01−U10+U00，可正可负；不强求正值，不将其解释为训练协同或内部模块因果证据。
- summary.json 为每个 gain 报自己的有效配对数；分解恒等式只在四格齐全时检查。缺失、截断仍不填正常零收益。
