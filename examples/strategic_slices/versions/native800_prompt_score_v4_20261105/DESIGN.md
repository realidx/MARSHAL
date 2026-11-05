# Native800题面v4：采用用户布局，合并历史与目标状态

2026-11-05。父版本v3及其所有结果保留。本版采用用户提供的完整system/user草案方向，替代此前短system选择；具名tools不变。
用户另行明确：保持原回应平局规则，只改表达。共同规则移到system，具体状态留在user；开头只要求自身预期最终收益，并指向回应平局规则。仅ACCEPT/REJECT自身收益平局时比较其他玩家预期最终收益总和；proposal不增加合作目标。

目标要求和当前完成状态合表。每个玩家列始终列出全部required commitments，每项标committed/missing；最后列共享完成度。pending不计入。若未来存在未用于任何目标的行动，单独披露其状态，不能因为合表丢失物理状态。

一笔OFFER和response对应一个原生历史事件。pending保留not yet binding；完成回应后替换为ACCEPT或REJECT及结果：只有ACCEPT使新增承诺生效。原proposal机会编号保留，调查行为/目标公开，答案仅在本人私有事实累计提供。

删除冗余历史before/after表需验证主S信息口径：承诺只增不减，保留当前完整承诺、所有其余已接受NEW additions和原机会编号。遗漏一条事件时，当前承诺减去其余已接受新增的并集得到该遗漏事件新增；其发生位置由编号缺口确定，因此其余事件的历史状态可恢复。仅对主S逐条遗漏作此保证，不推广到联合遗漏多条历史的诊断。

不改游戏、800名单、Oracle reference、主Q/S、scorer-v1、GRPO或采样/训练默认值。真实模型D尚未测；旧生产active v8不变。CPU运行前冻结source，运行结果另存EVIDENCE；完整实际system/user/tools必须导出。
