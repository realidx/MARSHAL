# Teacher 噪声与求解选择审查

本次为 CPU 开发审查，无模型 rollout、无训练、无生产 teacher 修改。固定选取训练集 balanced 背景的 14 题（8 个依赖几何）：8 道 B1/B2，6 道 binary P4。B 样本刻意平衡全集与缩集，并非总体随机样本。B3 和其他背景未覆盖。

## 1. 行为噪声

对固定合法历史的每一步，用 `(1-epsilon)*teacher_probability + epsilon/number_of_legal_actions` 重算行为似然，再按自己的偏好与私有事实条件化。强制 setup 不计作自愿行为证据；公共事实和先验约束保持不变。未重新求解噪声均衡，也未评估噪声对手下的 P 最优策略。

| epsilon | B 标签变化 | 被原标签排除的后验质量：最大值 |
|---|---:|---:|
| 0 | 0/8 | 0.000000% |
| 0.001 | 4/8 | 0.050013% |
| 0.01 | 4/8 | 0.501253% |
| 0.05 | 4/8 | 2.531646% |
| 0.1 | 4/8 | 5.128205% |

所有非零 epsilon 下，4 道原缩集题均恢复为三种偏好都有正概率；4 道原全集题支持集不变。全部 8 题的 favored 在所测噪声范围内不变。后验质量上升是该噪声模型下、给定这些历史的条件概率，不能当作 LLM 对手的实测错误率。

例：B2 `38837892447a0e89fd40` 的纯 teacher 后验为 want=0、neutral=0、avoid=1。epsilon=0.01 时变为约 0.002506、0.002506、0.994987；因此 possible 从 {avoid} 变成全集，但 favored 仍为 avoid。

结论：严格支持标签对正噪声存在不连续变化；这不等于所有行为证据都失效。不能直接沿用纯 teacher 的缩集标签评价噪声对手，也不能把输出全集当作学会了推断。后续模型诊断需要同时报告错误排除、favored 和决策表现。

## 2. 初始化与更新顺序

每题使用默认 uniform/synchronous，加 first、last 初始化，以及按全部玩家编号正序、逆序的诊断更新，共 70 次求解。同一行动规则、收益、回应平局选择与残余最优动作均匀分配保持不变。

默认 14/14 成功，且全部重现生产标签。56 次替代求解中 52 次成功，4 次失败。成功结果中，策略概率数组变化 0 次，标签变化 0 次；历史不可能 0 次。

策略比较直接哈希全部节点的概率数组，未使用包含初始化/更新顺序元数据的 policy_sha256。成功策略通过现有稳定性、信息集与偏离检查，以及 audit_native；不是仅比较初始化元数据产生的不同哈希。

| 变体 | 成功 | 失败 |
|---|---:|---:|
| first | 10 | 4 |
| last | 14 | 0 |
| forward | 14 | 0 |
| reverse | 14 | 0 |

失败清单：

- 73d16ca7db8eac086750 / acquisition / first: SearchLimit: Synchronous terminal policy iteration cycled; no label
- 3d8bfa9b9afbcd702653 / target_selection / first: SearchLimit: Synchronous terminal policy iteration cycled; no label
- df2e7febf6ffa7a3d6b8 / ordinary_alternative / first: SearchLimit: Synchronous terminal policy iteration cycled; no label
- 366c31bb8da920344159 / answer_use / first: SearchLimit: Synchronous terminal policy iteration cycled; no label

结论：在这个小样本上未发现多个已验证策略导致不同标签；发现了初始化引起的求解循环。失败不能当作另一种策略，也不能把局部稳定结果提升为全局唯一性证明。此次未改变回应利他平局规则，不能据此声称标签对该规则稳健。

## 对下一步的影响

- 保留现有精确 teacher 作为明确指定的监督参考。此次证据不支持现在重写 solver。
- 将纯 teacher 标签与带噪声标签分开；模型若被告知噪声仍严格排除真实可能偏好，才是直接的对手模型适应失败。
- 下一阶段分别测“明确给出噪声假设”和“未告知模型失配”，对比监督后/self-play 后模型；本次不能回答 self-play 是否修复脆弱性。
- 选择依赖仍是有限样本下未发现；需另审平局规则、近优行为，不能由本次阴性结果略过。

复现：`python new/teacher_robustness_20260917/audit.py`，再运行 `python new/teacher_robustness_20260917/test_audit.py` 和 `python new/teacher_robustness_20260917/report.py`。复现会重写本目录结果，不会修改训练数据。
