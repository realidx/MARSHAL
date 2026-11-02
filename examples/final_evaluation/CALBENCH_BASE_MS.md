# 通用 Base+MS：在本地 CalBench 24 局中如何运行

版本：`general-ms-conditioning-v2-shared-budget`，2026-11-02。已实现并做 CPU 离线验证；没有调用真实模型、测量模型收益或训练。

## 系统做什么

每当原环境请求玩家行动时，同一个 checkpoint 先生成一段简短的私有分析，再根据原上下文和分析输出行动：

```text
原生玩家可见上下文
    → MS：判断自身及他人的目标、知识、约束、意图，区分证据与推断
    → 原上下文 + 本次暂定 MS
    → 当前阶段的原生行动 JSON
    → 环境执行并提供下一次观察
```

两段核心指令见 [interaction_scaffold.py](interaction_scaffold.py)。它们不提日历、会议、时间槽或某种最佳策略；不强制填满 mental-state 类别，不要求固定句数或固定自身/他人比例。
行动阶段保留原目标，要求考虑可能的回应与后续影响；MS 被明确标记为可能出错的判断，不能当作新观察。
这是受 Base+MS 启发的通用适配，不是原论文逐字复现，也尚无跨环境效果证明。

MS 只用于紧随其后的行动请求，不另外保存到下一轮。原生客户端照常保留收到的消息和最终 assistant 行动回复，包括原有 `thinking`；若模型在行动解释中重述判断，该解释仍会按原生规则留在历史。因此这里的“没有 MS memory”指没有独立追加、保存上一轮 MS 的机制，不代表删除所有过去推理文字。

## 一个真实案例：`loose_uniform_s1`

案例来自 [冻结题库](calbench_stream_v1/cases/loose_uniform_s1.json)。四名玩家、8 个时间槽，会议依次到来；玩家不会提前看到后续会议。
第一场会议参与者为 0、1、2。Agent 0 初始日历如下：

| 时间槽 | Agent 0 自己可见的内容 |
|---|---|
| 0 | Errand #1，移动成本 1 |
| 1 | 空闲 |
| 2 | 空闲 |
| 3 | Errand #2，移动成本 1 |
| 4 | Errand #3，移动成本 1 |
| 5 | 空闲 |
| 6 | Errand #4，移动成本 1 |
| 7 | 空闲 |

此时尚未收到其他参与者的消息。第一阶段收到与基础调用相同的合法上下文，包括原生规则、Agent 0 的目标和这份日历；不会额外获得其他人的日历、真实成本、未来会议或评价器最优答案。

下面的 MS 和回复均为**人工编写的流程示意，不是模型输出，也没有执行成真实对局**：

> 我知道自己的 1、2、5、7 槽空闲。目前没有其他参与者对可用时间的陈述，因此尚不能认定任何一个槽对所有人可行。

第二阶段重新收到完整原上下文及上述暂定分析，可以输出原生通信动作，例如：

```json
{"thinking":"询问一个自己空闲的时间。","actions":[{"type":"dm","to":1,"content":"Slot 1 works for me. Does it work for you?"}]}
```

环境只执行这个 DM，不执行 MS。若之后 Agent 0 收到 Agent 1 和 2 各自确认 slot 1 的消息，下一次 MS 会从更新后的原生历史重新生成。它可以判断“消息支持 slot 1”，但不能声称自己直接看到了他人的日历。进入 DECISION 时，第二阶段仍须通过原生 `schedule` 写自己的日历，消息中的同意不等于已经完成调度。

同样的通用指令覆盖 CHEAP_TALK、DECISION、原生决策重试及 VOLUNTARY；合法动作和阶段限制仍由原生题面提供。MS 不增加环境回合，也不会让非参与者自动获得消息或被唤醒。

[完整实际请求导出](../strategic_slices/versions/general_ms_calbench_v2_20261102/preview/PROMPT_PREVIEW.md)包含这几个入口的完整 system/user/history，以及两阶段实际 HTTP 请求。请求由原生客户端和本次 adapter 生成，没有删节；回答和后续消息是明确标记的离线 fixture。HTTP 没有新增 `tools` 字段；具名动作仍由 CalBench 原生 prompt 中的 JSON 合同定义。

## 与之前基础 CalBench 的区别

| 项目 | 基础调用 | 本次 Base+MS |
|---|---|---|
| 每次原生行动请求 | 一次模型调用 | 同一 checkpoint 两次调用 |
| 推理支持 | 已有原生协商策略与 `thinking` 字段 | 额外显式 MS，再据此行动 |
| 输入信息权限 | 自己的日历、收到的消息和历史 | 相同；新增文本来自模型自己的判断 |
| 独立 MS 记忆 | 无 | 无；只用于本次行动 |
| 默认生成上限 | 4096 tokens | 两阶段共享 4096；行动上限 = 4096 − MS 实际生成 tokens |
| 原生行动、解析及重试 | 原生实现 | 相同；第二阶段结果交给原解析器 |
| MS 空、截断或未正常结束 | 无此阶段 | 单列 scaffold 失败，停止该局与后续批次；保留缺失，不补空动作或零分 |
| 记录 | 原生行动请求/响应 | 另存 MS 请求/响应、配对及预算扣除记录、完整 pipeline snapshot |

MS 调用的格式指令在复制后的 system 中覆盖“本次输出行动 JSON”的要求，游戏规则、目标和信息限制保留。第二阶段恢复完整原生格式要求。
适配层不自动向任何玩家发送 MS；最终行动消息仍由被测模型生成，不据此宣称已测量或保证隐私。

本版没有改变 24 个场景、全员同 checkpoint、原生目标/隐私规则、4 次通信上限、1 次原生决策重试、关闭 fallback/环境 reflection，或最终日历一致性的评分方法。
原生 prompt 中原有的场景策略仍保留；我们比较的是在这一基线上增加通用 MS 的收益，不是“无策略提示”与“有策略提示”。
两阶段不预留固定份额：MS 请求的上限就是总预算 4096；正常结束后，按服务返回的 `usage.completion_tokens` 扣除实际生成量，将全部剩余额度给行动阶段。例如 MS 用 300 tokens，行动最多 3796；MS 用 1200，行动最多 2896。每次原生行动请求重新获得这份总预算，包含重试，不是每局共用 4096。

不按字符串长度或自行重分词猜 tokens。服务必须报告两阶段的有效 `completion_tokens`；该字段中已包含的 reasoning tokens 不再另加。用量缺失/非法、服务报告超出请求上限，或 MS 用尽总预算时，记录 scaffold 失败，不执行行动、不补额度。MS 截断的处理仍是失败；没有固定预留，所以 MS 确实可能耗尽预算。

两次调用会增加输入处理和延迟，因此只保持生成 token 上限相同，不称严格计算量匹配。768-token 仍是单独诊断总预算，同样动态共享；不能与 4096-token 结果混合。初版固定 512/3584 的合同保存在 [v1 快照](../strategic_slices/versions/general_ms_calbench_v1_20261102/SNAPSHOT.json)，未改写。

## 如何使用

已有兼容模型服务时，在原 `routes.json`（总预算 4096、temperature 0）上显式选择：

```bash
python -m examples.final_evaluation.calbench_local \
  --routes /absolute/path/routes.json \
  --output /absolute/path/new-ms-run \
  --suite stream --scaffold base-ms
```

基础对照使用相同 routes/model，另建输出目录，并指定 `--scaffold native`。只改模型 endpoint/checkpoint 即可比较 base 与已有后训练模型，不提供额外教师模型。
自启 vLLM 的现有 launcher 也支持 `--suite stream --scaffold base-ms`；其他环境尚未接入该 adapter。原来的默认入口仍走基础调用。

每局 `transport-agent-*.jsonl` 只保存行动调用，`ms/transport-agent-*.jsonl` 保存分析调用，`scaffold-agent-*.jsonl` 记录一一配对与用量。自然语言 MS 不参与行动格式错误统计。`result.json` 的 `scaffold` 字段及原生 trace 用量包含两阶段成本；用量缺失则保留 null。
旧 `--ms-max-tokens` 参数已移除，含旧 `ms_max_tokens` 的 scaffold routes 会报错，避免静默沿用固定分配。
HTTP/服务错误、MS 生成失败及共享预算记账失败分别记录；失败前的请求和事件均保留，不自动重跑。相同输出目录不可覆盖，新的预算/模板/运行使用新目录。

每次执行写根目录及每局的 `pipeline_snapshot.json`，记录 CLI、配置、source/题库 hash、分阶段采样合同和环境。外部 API 的 model alias 不能证明权重身份；没有 launcher 权重证据的字段标“未记录”。正常推理服务须使用原有兼容环境和足够上下文容量；不会静默截断上下文。

## 验证与解释范围

离线验证包括原生客户端各入口的请求导出、MS 不独立进入历史、信息隔离、失败不伪装成动作、预算与用量统计，以及全 24 局固定假动作的原生引擎前后对照。假动作只检验接入机制，不检验策略质量。
完整执行记录和环境变更见 [EVIDENCE.json](../strategic_slices/versions/general_ms_calbench_v2_20261102/EVIDENCE.json)。没有启动模型评测、训练或测新 D；生产 active 仍为 v8。

后续比较应同时报告最终有效会议数、全流完成率、成本、格式/非法行动/截断及 replan 分支进入和解决情况。
24 局有配对与共享种子，不是 24 个独立结构；s1 八例已有开发验证用途，具体 checkpoint 的接触历史需核对。评价器最优成本是 hindsight 下界，不是在线可预知未来的策略要求。
