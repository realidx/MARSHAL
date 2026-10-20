# 2026-10-21：输入形式、状态披露、记忆与响应平局规则核对

本轮先核对事实并形成状态化草案，**没有改动生产训练、评分、Oracle、题库或超参**。active仍为v8。新[V9完整草案](versions/terminal_v9_state_draft_20261021/PROMPT_PREVIEW.md)标为 `NOT_TRAINING_READY_SCORE_MISMATCH`，没有接入训练；发现的评分缺口不能靠在prompt补一句话宣称已经解决。

用户本轮要求：每种游戏状态都披露同样的完整必要信息，当前行动说明按状态区分；保留调查答案；明确响应时自身效用优先、平局帮助别人；删除exercise-window说明；进一步考虑公开的相依偏好规律。最后一项是未来方向，本轮未改变隐藏偏好生成。

## 1. System/User/Tools并非三个必须手写的内容块

本模型Qwen3-4B-Instruct-2507的[官方model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)直接给出只有一个user message的示例，说明不必手写system。把游戏规则和作答要求合并到一个user message是可行的；system长短不表示任务信息是否完整，也没有本项目证据证明重复一段短system能提高训练效果。

需要保留模型原生chat template和特殊角色token格式。三个输入字段最后会序列化为一个token序列。当前Qwen模板在提供tools时会自动添加system里的工具说明，即使不写人工system也如此。把人工内容合并为一个user不等于删除模板自动产生的工具说明。

[Transformers官方工具文档源码](https://github.com/huggingface/transformers/blob/main/docs/source/en/chat_extras.md)将tools作为JSON schema或Python函数传给apply_chat_template；[模板接口文档](https://github.com/huggingface/transformers/blob/main/docs/source/en/chat_templating_writing.md)说明具体序列化格式随模型而异。当前具名行动接口属于这种常见function-calling方式。

理论上也可让模型输出文本或手写JSON再由环境解析，行动接口必须有可执行的语义，但未必必须用tools字段。本项目已采用具名tools，用户也接受，草案保留它；不同时更改parser/动作语义。tools提供的是行动集合及参数，不是Oracle答案。

[本地模板检查](../../new/prompt_state_audit_20261021/draft_checks.json)确认4种草案request均仅有一个人工user message，tools与v8相同，模板成功生成工具system头及assistant生成前缀。检查使用本地Jinja模板，不是HF tokenizer编码、模型采样或效果实验。

## 2. 共同信息保持完整，状态部分只负责当前任务

草案使用一个共同的request函数。所有提案/响应状态都包含：

1. Game rules，包括自身最终效用目标和响应平局规则。
2. Goal requirements表格及一句单元格解释。
3. 公开偏好。
4. 当前玩家全部可见私有偏好事实。
5. 公共偏好生成规则/背景概率。
6. 完整公共事件历史。
7. 已经接受、生效的承诺。
8. 当前提案顺序、各玩家剩余调查次数。
9. 当前决策和合法tools。

只有最后的当前决策说明切换：

| 阶段 | 当前状态说明 | 合法行动 |
|---|---|---|
| Proposal | 当前玩家有提案机会，无待回应offer | 此刻原生合法的OFFER/PASS/INVESTIGATE；调查次数耗尽则不显示INVESTIGATE |
| Response | 明确提案者、接受者、双方拟新增承诺、尚未生效 | ACCEPT/REJECT，并提醒响应平局规则 |
| Terminal | 无后续行动 | 不再请求模型 |

这不是两套不同信息条件的题库；共享披露内容不因proposal/response而删除。草案中删除了 `DECISIONS IN THIS EXERCISE` 和参考策略接管等内部文字。实际k、reference continuation、采样和评分合同本轮没有改变；草案不作为已激活的新协议。

## 3. Already accepted commitments与pending offer是两种物理状态

`COMMITMENTS ALREADY IN FORCE` 指此前已经被接受的承诺，不是正在提出的offer。

例如：Alex和Blair上一笔offer已经接受，轮到Casey提案。此刻没有pending offer，但Alex/Blair已经生效的承诺依然存在，仍影响所有目标的完成度。因此这个状态在proposal阶段也必须披露。反过来，第一笔offer的响应阶段可以有pending offer而没有任何已生效承诺。

草案把它写成 `ALREADY ACCEPTED COMMITMENTS`，和响应阶段的“proposed additions，NOT yet binding”分别展示。[实际环境轨迹](../../new/prompt_state_audit_20261021/memory_trace.json)包含一个proposal阶段已有承诺且pending为空的状态，直接验证这一区别。

## 4. Private Information不全来自Investigation；跨turn是显式状态重建

当前私有事实包括：

- 当前玩家自己的、没有公开的真实偏好。
- 当前玩家本人通过Investigation收到的、没有公开的真实偏好答案。

公开事实在公开表保留一次。没有提供对手的私有答案，也没有替模型填写从行为推断出的偏好或谁知道什么。

环境实现 `PrivateInvestigationRules.step` 将真实答案写入调查者的 `state.private_results[player]`。普通动作克隆状态时保留这些结果。`observation`只读取当前玩家自己的结果；每次request重新构造公共历史、自己的偏好及累计私有答案，再送给模型。

**当前是连续游戏环境 + 每步完整可见状态重建，不是不断追加assistant/user消息的长对话。** 原始request只有system/user两个messages，没有前序assistant解释；NativeStream只编码当前request。过去模型自己的推理文本不会自动保留，游戏的真实观察和自己的过去行动则通过累计状态/历史再次提供。

本轮[三决策核验](../../new/prompt_state_audit_20261021/memory_trace.json)：Alex第一步INVESTIGATE，第二步回应Blair的offer并ACCEPT，第三步回应Casey的offer。第二、第三次request都包含第一步获得的真实答案；中间另一玩家的request没有获得该私有答案。未调用模型或Oracle求解器。

这满足“必要事实不依赖模型自己记忆”的要求。是否额外携带先前assistant解释，是另外一种训练输入设计；当前没有实现，不应把环境状态持久化称为完整chat memory。

## 5. Response tie-breaking存在真实的软件/评分缺口

规范应恢复为：每个玩家在ACCEPT/REJECT阶段先比较在自身信息下的预期最终效用；自身效用平局时，比较所有其他玩家的预期最终效用总和。两层都平局时两种响应均允许。Proposal阶段不使用其他玩家效用打破自己的平局。不能把它改成当前承诺效用，也不能用固定加权总分允许牺牲自身收益。

代码核对：

| 层 | 当前实现 | 是否包含响应社会平局 |
|---|---|---|
| `training/b_sft/decision_policy.py: optimal_indices` | 自身优先，response才比较others sum | 是 |
| 私有游戏参考策略求解/认证 | 使用相应目标；冻结100个reference均有response-only social-tie认证 | 是 |
| `training/strategic_slices/values.py: extreme_value/cached_extreme_value` | 只传播ego标量utility，使用argmax/argmin | 没有完整次级收益向量 |
| `terminal_training.py: score_response` | reward=Q_own−maxQ_own，正确性只看own gap | 否 |
| `StepRollout.accept`及slice validation | optimal_indices只是own Q并列集合，不调用response tie helper | 否 |
| v8题面 | 移除了该条规则 | 否 |

[真实日志反例](../../new/prompt_state_audit_20261021/logged_response_ties.json)中有：

| 行动 | 自身预期最终效用 | 其他玩家效用总和 | 当前reward | 按响应规范 |
|---|---:|---:|---:|---|
| REJECT | 0 | 2 | 0 | 应排除 |
| ACCEPT | 0 | 4 | 0 | 应选择 |

这是从job960070的真实训练上下文复原的最后响应节点，直接按原生终局payoff和日志posterior计算，own Q与日志一致。例子中模型实际采到ACCEPT，**反例证明的是评分把REJECT也判对，不是说这次采样做错了**。前3个上下文反例不构成发生率估计。另检查selected题目中4个立即终局的响应入口未发现该问题，不能把入口检查结果推广到后续实际节点。

因此不能只加一句prompt就称“与software对齐”。完整修订需要让求值器在同一continuation/信息集下获得自身和其他玩家的Q，统一响应的正确动作集合、训练reward、验证和独立审核。其余GRPO、组内对比、采样批次不需要因此重新设计。

只有两个响应动作时，一个可审阅的reward口径是：自身Q不平局时仍用自身负regret；两者自身Q平局时再使用其他玩家收益的负regret。这避免固定加权允许牺牲自身效用。不过本轮没有擅自接入这个候选；次级Q的后续策略/剩余平局约定、数值容差、旧标签及信息指标兼容性仍需一起核验。不能把原始own-only日志改名为完整平局规范结果。

## 6. 信息筛选应区分动作影响和事前价值

用户关心的信息移除效果有两种相关但不同的指标：

- 同一物理节点保留/屏蔽一条私有观察后，最优动作集合是否改变。
- 从获取答案之前的共同belief出发，有答案与无答案的最优contingent policy有多大的预期效用差。

当前C/S主要使用Oracle信息分区/策略价值的比较，不是删除prompt字符串后的模型表现。后者如果要做，也必须检查所有泄漏渠道：私有表、其他直接披露的事实、历史assistant解释（若将来保留）、belief更新等。不能删了答案文字却保留按答案条件化的posterior，也不能同时改变隐藏world或对手策略后声称只移除了一个信息。

恢复响应次级目标后，还需区分“自身价值没有变化，但正确响应因其他玩家收益而变化”的情况；旧own-utility信息值不自动等于完整响应规范的决策影响。

## 7. 公开相依偏好规则是可行的后续方向

应固定的是**公开的关联规律**，同时每局仍抽样隐藏的联合类型。例如让某玩家的两条私有偏好只能为 `(want,want)` 或 `(avoid,avoid)`，各50%。调查第一条就能推断第二条。还应安排相关offer，使第二条偏好影响后续决策，才可能产生可验证的决策价值。

如果某条规则只是 `G1=want ⇒ G2=want`，它是单向蕴含；观察G1≠want不应自动知道G2。如果使用等价关系，应明确写成双向。公开规则不应让玩家无需调查便能知道所有隐藏值。

固定隐藏取值、每次reset都一样，会增加记忆题目答案的风险；公开规则固定、联合类型仍变化，才保留对局内推理的不确定性。

底层有限type_catalogues/world枚举能表达这种关联；v8的可读renderer目前明确拒绝非独立catalogue，以免题面错误地宣称独立。未来要增加公开依赖规则或联合类型表、定义联合先验（不能无说明套用独立权重乘积）、重新认证reference并计算C/S/D、记录新题库版本。本轮没有改这些资产。

信息消融也须保留公开逻辑：如果G1可以由仍保留的G2推出来，只删直接G1答案未必真的消除信息，测得价值接近0可以是正确结果。

## 8. 证据、草案与当前状态

- [原生状态/记忆核验及入口响应检查](../../new/prompt_state_audit_20261021/audit.py)，[摘要](../../new/prompt_state_audit_20261021/summary.json)。
- [真实训练响应平局反例](../../new/prompt_state_audit_20261021/logged_response_ties.json)。
- [草案request函数](../../new/prompt_state_audit_20261021/prompt_draft.py)，[完整消息和tools](versions/terminal_v9_state_draft_20261021/PROMPT_PREVIEW.md)，[草案记录](versions/terminal_v9_state_draft_20261021/SNAPSHOT.json)。
- [本地模板渲染检查](../../new/prompt_state_audit_20261021/draft_checks.json)；其中记录了当前v8注册快照hash，生产source门禁仍通过。

当前active仍为 `terminal-node-regret-grpo-readable-v8`。V9仅在版本索引的drafts中记录，未加入可训练versions。生产代码、数据、超参没有改变；未GPU采样或训练，没有重跑D。v8的机械CPU检查不等于本轮新发现的响应规范已对齐，按本轮明确的完整规范不应把v8称为训练就绪。
