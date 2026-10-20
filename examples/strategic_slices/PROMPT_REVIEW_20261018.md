# v7题面审阅与v8修改记录

日期：2026-10-18。本轮来自用户对v7逐段审阅，另明确：“保留自己的调查答案，去掉额外来源提示”。v7文件和快照保留；当前修改作为独立v8记录，不覆盖v7。

完整输入：[v8 PROMPT_PREVIEW](versions/terminal_v8_readable_20261018/PROMPT_PREVIEW.md)。其中第五个例子 `terminal_private_new_answer` 包含一个此前未公开的真实调查答案；第四个例子则调查了原本已经公开的偏好，可比较两种情况。原始[v7预览](versions/terminal_v7_named_20261017/PROMPT_PREVIEW.md)可继续逐项对照。

## System、user、tools为什么分开

| 部分 | 含义 | 当前放什么 |
|---|---|---|
| system | 每道题共同遵循的作答要求 | 根据规则/可见信息决策，先简短解释，再恰好一次行动工具调用；沿用9月原文 |
| user | 当前游戏和这一时刻的题面 | 游戏规则、目标要求、公开/私有事实、概率、历史、已生效承诺、轮次/待答offer及当前决策范围 |
| tools | 允许提交的行动及参数格式 | OFFER、PASS、INVESTIGATE、ACCEPT、REJECT，以及此刻合法的参数组合 |

这不是3次采样，也不是3个模型分别推理。一次生成请求包含这些部分；Qwen chat template把它们序列化成同一个输入前缀，工具定义写进system里的工具说明。模型接着输出解释和一个工具调用，环境才执行该行动。tools里的INVESTIGATE也有游戏中的时间/次数成本，不是免费向Oracle求答案。

## 逐块解释与实际修改

| v7部分 | 原意/存在的问题 | v8处理 |
|---|---|---|
| GAME RULES中的goal说明与后面的DECISION OBJECTIVE | 计分定义分散；全LINEAR题的规则没有同时解释BINARY，后面又补充一次 | GAME RULES同时明确：BINARY须全满足才记1，否则0；LINEAR按已满足比例，含1/2=0.5例子；明确最终score公式。目标要求表紧随GAME RULES |
| GOAL REQUIREMENTS BY PLAYER | 每个目标要求谁承担哪些commitment；列名仅玩家名，易误读成玩家偏好 | 列名改为“Alex's required commitments”等；明确单元格是目标要求，不是偏好，none表示该玩家没有此项目标要求 |
| COMMITMENT OPTIONS | 各玩家可以承担的承诺名称；不是OFFER/PASS等动作菜单，也不是已经接受的承诺 | 删除独立大块，改为目标表后的一行名称列表；每offer新增上限移入GAME RULES。此刻合法新增组合仍由tools完整给出 |
| KNOWN PREFERENCES的Who knows/source列 | 把“公开”“恰好是你自己的”“调查所得”当作可叠加来源标记；同一行可能同时标public+own，容易被误读成不同互斥可见性类别 | 改为PUBLIC PREFERENCES和YOUR PRIVATE INFORMATION两张3列表。公开事实只列一次；你的私有事实包含未公开的自身偏好和你获得的调查答案。不额外标来源，不替模型总结谁通过调查知道了什么 |
| 调查历史中的额外提示 | 事件既写调查者/目标，又追加“答案仅送给某人”等提示 | 保留调查者与目标这一公开行动事实；删重复送达提示。规则仍交代调查答案私有，实际答案保留在当前玩家的可见事实里；其他玩家的答案不提供 |
| PUBLIC PREFERENCE SUPPORT | 当前小型题库用完整偏好行目录定义可能范围。v6的JSON已有public_preference_support，v7将其逐行写出；9月人类可读题面没有这段枚举 | 核验当前100父游戏后发现全部为“固定公开单元格 + 其他单元格独立取want/neutral/avoid”；因此可以完整删除枚举，用公开事实+独立抽样规则等价表达 |
| BACKGROUND PROBABILITIES | 产品权重、归一化、support等是求解器语言；不是直观游戏描述 | 恢复概率写法，例如want50%、neutral25%、avoid25%；等概率时写每项1/3，避免小数舍入。明确是观察行动之前的背景概率，观察后信念可变，不是效用权重 |
| CURRENT BINDING STATE | 当前已经接受、生效且不能撤销的承诺；不是模型的认知状态 | 改名COMMITMENTS ALREADY IN FORCE。保留是因为slice可从游戏中途开始，且待回应offer还没生效。历史与当前状态一致，未自动补充策略结论 |
| YOUR CONTROL WINDOW | 当前训练让模型最多负责之后几次自身决策，之后由参考策略接手；不是RR次数，也不是此时结算分数 | 改名DECISIONS IN THIS EXERCISE，用普通语言写剩余决策数、proposal/response各算一次、后续策略接管以及仍算整局终局分数；删certified/native等内部术语 |
| DECISION OBJECTIVE | 再次描述自身终局utility和goal公式，与GAME RULES重复 | 删除独立块。自己的整局最终score目标放YOUR TASK和GAME RULES；没有改成当前一步收益或只算窗口内收益 |

例如目标需要Alex的Cedar和Blair的Cedar：如果只有Alex已经承担Cedar，LINEAR completion=1/2，BINARY completion=0。COMMITMENT OPTIONS原本只是说明Cedar等可选名称；CURRENT BINDING STATE原本说明哪些已经承担。这两者一个是可选种类，一个是已发生的物理状态。

这里的BINARY/LINEAR是**环境目标如何计分**，与“训练reward是否二分”不同。本轮训练仍使用已确认的连续Q/负regret。

## 偏好信息的边界

- 公开偏好是开局就固定且人人知道的事实；自己的实际偏好是个人直接拥有的信息。自己的一条偏好也可能本来就公开，v7的public+own并不代表两条不同事实；v8去掉这种重复来源表示。
- 调查后，调查者可以额外知道别人的某一条真实偏好；这条值仍不公开。v8只给当前玩家实际能看到的值，谁调查过谁从公开事件中体现。
- 如果调查目标原本就公开，该值在PUBLIC PREFERENCES里保留一次，不重复制造“私有事实”。如果调查得到原来未公开的值，该值出现在YOUR PRIVATE INFORMATION里。没有删除新的调查信息。
- 不由环境提供从行为推导出的偏好、不提供Oracle posterior/Q/最佳动作、不提供对手的私有调查答案，也不额外给“谁推断出了什么”的说明。

## 概率和信息未改变的核验

[概率等价检查](versions/terminal_v8_readable_20261018/prior_equivalence.json)：100个父游戏、1,344种隐藏世界、198个可变单元格、521个公开固定单元格。所有catalogue都是这些单元格取值的完整笛卡尔积。去掉常数公开偏好的概率因子后，独立抽样的每个world概率与原world_weights逐一相同，最大差异0。没有重建题库或重求Oracle。

[实际日志迁移检查](versions/terminal_v8_readable_20261018/native_interface_migration.json)：376个不同context，2,045个原生合法动作；system与tools和v7逐项一致；三列表中可见偏好事实集合全部与v7一致。53个context带调查回答，其中34个含原本未公开的调查信息。没有动作错配或可见事实增删。去掉的是额外来源/知识提示和冗长枚举。

新renderer会检查catalogue能否独立表达；未来若加入相关偏好或额外联合限制会直接报错，不静默改写概率假设。

## 关于窗口仍需分清的事情

窗口是实验控制/评分合同，不是原生游戏规则：例如k=2表示模型最多再负责两个自身决策，不是环境总共再走两步，也不代表刚好一个RR。Oracle Q包含窗口后的参考策略终局延续值，因此v8保留其实际含义，使用普通语言说明接管方式与最终计分时点。

是否让模型知道窗口，是可以继续审阅的protocol选择。本轮没有把“删掉看不懂的文字”扩展成偷偷隐藏窗口或改变窗口后策略，也没有声称“precomputed strategy”已向模型完整公布了对手每个节点的策略概率。当前描述交代运行方式，不是完整策略函数。

## 版本与运行状态

- pipeline：`terminal-node-regret-grpo-readable-v8`；prompt：`terminal-readable-named-v2`；父版本v7。
- 完整修改清单和不变项：[CHANGELOG](versions/terminal_v8_readable_20261018/CHANGELOG.md)；完整配置：[SNAPSHOT](versions/terminal_v8_readable_20261018/SNAPSHOT.json)。
- 原100题、reference、Oracle Q、reward/advantage、20×8、并发、预算、优化器、验证和保存频率沿用v7；没有加解释奖励或新算法。
- 旧D仍按旧JSON/act测量；本轮没有重跑D、重选题、GPU采样或提交训练。CPU检查不是模型效果/训练收敛证据。
