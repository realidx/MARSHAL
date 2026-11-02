# CalBench 独立 belief/MS → action：两次调用

当前版本：`general-belief-ms-v8-prompt-retry-once`，2026-11-02。CPU离线结构检查通过，尚未调用真实模型评测。
用户要求独立的belief/MS阶段；不采用v4把MS要求合并进一次行动回复的方案。

## 每次原生行动内的准确顺序

```text
system：原生CalBench规则等（不改）
过去的原生user / assistant历史（不改）
user：本次原生观察与请求（完整结束，不改）
user：BELIEF / MS STAGE要求
    → 第一次模型调用实际生成MS
assistant：第一次模型调用返回的MS文本
user：ACTION STAGE要求
    → 第二次模型调用生成原生行动JSON
assistant：最终行动回复
```

`assistant`是消息的角色，表示当前模型已经生成的回复；不是第三个模型、不是另一个玩家、也不是额外的指令。
运行代码从第一次响应读取真实文本，把该文本作为assistant消息加入本次临时对话，第二次调用因而能看到它。
其他玩家发来的DM仍由环境按原生方式写在user观察内容中，不冒充当前模型的assistant回复。
MS请求是在原始user之后**独立新增一条user**；不写进system，也不拼在原始user内容中。
第二次请求保留第一次请求的逐条完整前缀，再接assistant MS和user行动要求，不把MS搬成user引文。

两次调用使用同一被测checkpoint。无状态HTTP接口仍需提交累计messages；共享逻辑历史不等于保证缓存命中或省去前缀计算。

## 两个新增user提示的完整文字

MS：

```text
Before your next action, briefly articulate your own mental states and
your beliefs about the mental states of other participants.

Write from your own perspective: what you believe, want, know, or intend,
and what you think others believe, want, know, or intend. Include emotions
only when relevant to the interaction.

Ground these judgments in the available context and history, without
inventing hidden facts. Write one brief paragraph that can guide your
next decision.

```

Action：

```text
ACTION STAGE
Use your preceding mental-state assessment as a fallible judgment to briefly plan
and choose your next legal action. Follow the original environment rules and
return only the original required action-response format. Do not repeat the MS
assessment or narrate future execution.
```

不要求固定mental-state维度配额，不加入CalBench最佳调度策略、教师belief或额外事实。
第二次调用仍按原生 `thinking/actions` JSON输出，行动由原生解析器执行；MS文本不会直接作为环境动作。
原生system仍保留原有行动格式要求，本次没有暗中修改它；CPU结构检查不证明模型一定服从独立MS提示或不再重复。

## 与不同次行动之间的关系

上述MS/user/assistant消息只属于本次行动内部的临时对话。
最终行动返回原生客户端，原生客户端继续保存**原始user请求 + 最终assistant回复**；MS阶段的额外消息不会另行写入跨行动历史。
原有最终回复的thinking照常保留。没有改写旧行动与新行动的关系，也没有增加跨局MS记忆。

## 真实例子与预算

使用 [loose_uniform_s1](calbench_stream_v1/cases/loose_uniform_s1.json) 的Agent0：第一场会议参与者是0、1、2，自己的空闲时间是1、2、5、7，尚无他人确认。
第一次回复可以判断“我知道自己的空闲槽，但不知道哪些对别人可行”；这条真实回复以assistant身份出现在第二次请求中。
第二次才决定例如向Agent1发送询问，并输出原生行动JSON。这只是说明，不是已测模型表现。
[完整逐角色预览](../strategic_slices/versions/general_ms_calbench_v8_20261102/preview/PROMPT_PREVIEW.md)及requests.json包含六种入口，所有示意回复/后续消息明确为人工fixture。

默认两次生成共享4096：MS可使用总额度，行动上限为4096减去服务报告的MS `completion_tokens`，没有固定阶段份额。
服务必须报告有效生成用量；不按字符数猜tokens，也不对已包含的reasoning tokens重复计费。
MS截断/空回复、未知或非法用量、预算耗尽或超额均单列失败，不自动补额度或伪造零分。行动仍走原生parser和重试。
每次原生行动请求（包括原生重试）重新获得总预算，不是整局共4096。768是另外的诊断条件。

## 只重试失败的prompt，继续全部24局

v8按用户澄清，取消v7整局重跑。每局只执行一次；遇到失败的模型请求，在当前位置重试该prompt一次：

1. MS请求失败、空/截断/未结束、用量非法或耗尽预算：只重新请求MS；当前游戏状态和原生历史保持。
2. action请求失败、空/截断/未结束或用量非法：保留已成功的MS，只重新请求action。
3. 重试使用完全相同的messages、model、seed、temperature、max_tokens；失败输出不追加历史，不重新生成已经成功的阶段。
4. 两次均失败则中止这一局、结果保留缺失，继续其余局；没有整局重跑或第三次请求。

原生DECISION语义/parser重试照旧，它与这里的同一请求重测不同。正常结束但调度失败不触发额外重测。
相同seed、温度0可能再次产生相同循环，不能保证恢复。

**预算边界：**被接受的MS和action仍共享4096，action上限为4096减去被接受MS的completion_tokens；失败输出的重试属于额外计算，全部计入实际总成本。
例如MS第一次用4096后截断，第二次219、action成功500：实际消耗4815，而被接受的MS/action为719；不把实际消耗写成719或声称所有尝试共不超过4096。
action重试沿用同一个剩余额度，不重做MS，也不降低已使用的实际成本。缺失usage仍为未知，不按字符或默认值补猜。

所有物理尝试追加到原阶段日志：MS在`ms/transport-agent-*.jsonl`，action在`transport-agent-*.jsonl`。
同一prompt的`call_index`相同、`prompt_attempt`为1/2，完整request、response、accepted、错误和耗时分别保留。
重试不占用下一个逻辑prompt的采样序号。scaffold收据记录阶段尝试及成功MS，原生trace用量包含被丢弃的失败输出；HTTP未报告usage则保留未知。
`case_results.json`为schema2，每局一条，汇总物理调用、prompt重试/恢复/耗尽数及全部token/时间；`results.json`保存每局执行结果。
没有`retries/case_id/`或整局attempts.json。审计脚本仍按旧v7合同读取旧结果，不能把旧整局重试改称prompt重试。

同一stream24政策用于native基础对照；其他旧suite的政策保持。两次prompt都失败仍继续后续题，RUN_FINISHED区分“全部尝试过”和“全部正常结束”，不填0效用。
进程被杀、进程池损坏或磁盘错误仍可能中断运行，不能把这些未启动的局称作已完成。
未自动续接旧job1060153/1060154，也未启动新模型运行；新运行使用新目录并保留原身份。

## 运行和记录

```bash
python -m examples.final_evaluation.calbench_local \
  --routes /absolute/path/routes.json \
  --output /absolute/path/new-belief-ms-run \
  --suite stream --scaffold belief-ms
```

routes使用总生成预算4096、温度0；已有兼容服务或现有launcher均可。基础对照选择 `--scaffold native`，默认仍为native。
历史 `base-ms`、单次调用 `ms-guided` 均不自动换成新语义，会报错；旧ms_max_tokens配置也拒绝。
每局的MS调用保存于 `ms/transport-agent-*.jsonl`，最终行动保存于原 `transport-agent-*.jsonl`，另有配对/预算收据及完整pipeline_snapshot。
所有24局、原生规则/目标/隐私约束、原生history/parser/retry、最终一致性评分保持；新增独立阶段及同prompt重试/继续运行合同另列。

[执行证据](../strategic_slices/versions/general_ms_calbench_v8_20261102/EVIDENCE.json)记录69项CPU检查，包括精确user-user-assistant-user顺序、真实第一响应传入第二请求、原生历史不变、共享预算及24局假响应机械对照。
假响应不能证明协调能力、模型D或重复问题改善；未训练，生产active仍v8。24局的配对/共享种子、s1开发用途及hindsight成本下界等原解释边界不变。
