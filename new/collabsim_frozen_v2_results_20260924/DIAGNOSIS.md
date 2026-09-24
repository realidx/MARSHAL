# Frozen v2 原始轨迹复核

本次核对 trace、events、run_summary，并对照本地原生 CollabSim 执行器。没有修改环境、提示词或评分规则。

采用 README 指定的有效运行：Q0 877899；BP99 877961 的前三局与 878073 的 reverse-dashboard；SP41 877996；O99 877997。Hidden Profile 各取 hidden-profile-00。取消、部分运行和上下文溢出的额外运行不纳入。

## Hidden Profile：README 的行为解释需要纠正

四个模型的三位 agent 第一轮均输出 message，因非 discussion 阶段被拒绝，没有 initial_vote。最后一轮实际输出如下：

| 模型 | 最后一轮原始动作 | 原生结果 |
|---|---|---|
| Q0 | 三人 final_vote，均 Candidate C | 三次拒绝：缺少 initial_vote |
| BP99 | 三人 final_vote，均 Candidate B | 三次拒绝：缺少 initial_vote |
| SP41 | 两人 final_vote Candidate B；一人 message | 两次缺初始票拒绝；一次阶段不允许通信 |
| O99 | 三人 final_vote，均 Candidate B | 三次拒绝：缺少 initial_vote |

因此“没有已接受的 decide”属实，“模型没有尝试投票”不属实。Q0 已在讨论后选择目标 Candidate C，不能用零正式投票解释为没有整合信息。但原始选择不能冒充正式任务成功。单案例单运行不能确定模型排名。

证据：各运行 results/hidden_profile/hidden-profile-00/trace.jsonl 的 step 1、30，以及 events.jsonl 的 action_rejected；原生 controller.py 的 Final vote requires an existing initial vote first 检查。

## ShapeFactory：实际结果与统计陷阱

| 模型 | 完成订单 | 全队完成局 | 人均最终余额 | 实际接受成交事件 | 完全没有生产的局 |
|---|---:|---:|---:|---:|---:|
| Q0 | 1/12 | 0/4 | 195.00 | 2 | 1/4 |
| BP99 | 1/12 | 0/4 | 198.75 | 1 | 2/4 |
| SP41 | 2/12 | 0/4 | 200.00 | 3 | 1/4 |
| O99 | 2/12 | 0/4 | 200.00 | 3 | 0/4 |

成交依据 trade_offer_responded.response_type=accept；原生 completed_trades 列表同时收录 decline，summary 的列表长度不能解释为成功成交数。O99 reverse-private 的 completed_trades=3 实际全是拒绝。

action_validated 也不等于实际执行成功。原生任务函数在报价不存在、库存不足等情况下可以返回 False；不能只数 action_rejected 来统计语义失败。

一个明确实例：O99 reverse-private 的 B 在 step 30 接受 offer_13_1，随后 step 31 fulfill_order，并在 rationale 中认为已取得 circle、可以得到奖励。但事件记录没有这次成交和履约，最终 B 订单进度 0、余额 155。另一个实例：同局 C 多次拒绝 A 买 triangle 的提案，理由却是自己需要 square、要保留资金，混淆了出售收益与购买支出；当时没有库存也是执行约束，不能声称报价当时即可成交。

这批模型已会发消息、报价及尝试履约，不再是先前完全不调用 fulfill_order 的模式。但生产启动、报价身份与方向、真实库存、实际执行结果之间仍有明显断裂。四局中小幅得分差不足以证明训练改善了社会推理；BP99 在此环境也没有显示可靠优势。

## 建议

## 补充复核：论文与两人局

原论文 https://arxiv.org/html/2606.06399v1 的 Appendix B.3 明确指定 Candidate C；Table 4 的 baseline persona-based final vote accuracy：Llama-4 0、Qwen3.6 66.7%、GPT-5.5 100%、Claude 4.6 0。不是所有大模型均失败，也不是随模型规模单调改善。原生 analysis/task_metrics.py 从 summary 中已登记的 final_votes 计分，未登记投票计错。因此本批 Q0 正式准确率仍是 0，不能把 raw 三个 C 写为论文口径 100%。原生初始化没有把 correct_answer 放入可见 phase_rules；Q0 第一轮 trace 也没有这个答案字段。

重新读取 native-lite-q0-oldbp-runs.tar.gz 中 old-bp99-96k-876629 四局原始 summary/events：两人局确实完成 5/8 订单、实际成交 5 次、生产 23 件，四局都生产。三人 v2 为 1/12、实际成交 1 次、生产 5 件，两局零生产。两人每席位各一订单、三人也各一订单；相同经济参数、900 秒、10 秒触发、30 秒生产延迟、probe 和原生提示。实质变化包括人数 2→3、形状 2→3、订单/专长从双向互供变为三人供货环。三人不是纯粹增加一个同类席位。旧服务 H100、本批 H200，原生真实时间调度与异步执行也意味着这不是严格隔离人数的因果实验。

这些记录支持“原有双人交易能力没有稳健扩展至三人协调”的描述，不支持“BP99 从来不理解生产/履约”。供货环中购买对象与出售对象不同，是有代码依据的结构差异；它是否是下降主因仍不能由四局单次运行确定。

先修诊断统计：并列呈现原始尝试、schema 接受、实际环境效果。保留原生 HP 正式失败，同时报告 final_vote 尝试及选择，不能把未接受投票写成未形成选择。无需为此重跑、改提示词或放宽规则。

正式分析将本批视作包含显著流程/执行瓶颈的迁移测试；不能把全部失败直接归于 belief/planning，也不能据此单独定位训练失败机制。
