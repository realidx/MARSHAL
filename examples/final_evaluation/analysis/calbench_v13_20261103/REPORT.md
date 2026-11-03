# CalBench v13逐调用结果分析（2026-11-03）

本次分析覆盖 `runs/calbench_soc` 全部9个目录：4个新v13条件作主比较，其余5个历史条件单列；另读取先前同模型的native基线及一条v12重试作为对照。没有修改prompt、工具、游戏、评分、选择或训练，没有调用模型。复现脚本为[audit.py](audit.py)，逐题数据与断言结果为[analysis.json](analysis.json)，输入文件身份为[INPUT_MANIFEST.json](INPUT_MANIFEST.json)。

## 主要判断

1. **v13的决策重试修复已进入真实请求；独立MS依然表现较差，不能继续用同一个旧bug解释。** 52个独立MS决策重试请求都恢复完整DECISION要求。Qwen的重试DM为0；outcome仍有1次模型违令输出DM。两阶段的2114个接受动作请求都严格续接实际MS前缀，预算扣减一致。
2. **inline在共同完成题上显著优于本次独立MS，但尚未证明在全套任务上优于native。** inline对native只有每个模型净增4场会议，且中止更多题；native旧日志的截断处置也不同。
3. **MS没有稳定地产生正确的事实与共识模型。** 独立MS会把猜测写成共识，ACTION继承这些判断；inline也有同类错误，即使最终协调成功。观察到“MS文本先错、ACTION沿用”，不等于已经证明MS相对无MS产生了全部错误；需要同状态消融才能区分继承与共同偏差。
4. **inline把一部分协调问题变成了完成性问题。** 9个中止局均是4096-token循环，重试输出逐字相同；其中6个发生在决策验证重试、1个发生在首次DECISION、2个发生在CHEAP_TALK。较长输出本身不是充分解释；可见内容是在冲突约束下不断推翻自己的选择，未完成最终JSON。

## 总结果与缺失口径

以下会议成功使用**终局仍有效会议数**，不是累计轮次曾成功数。未完成局没有被置零。每局3个请求会议，完整24局共72场。

| 模型 | 条件 | 完成局 | 终局有效会议 | 全部会议成功的局 | 语义无效动作 |
|---|---|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 | native旧基线 | 24/24 | 37/72 | 5/24 | 28 |
| Qwen3-4B-Instruct-2507 | v13独立MS | 23/24 | 21/69 | 2/23 | 29 |
| Qwen3-4B-Instruct-2507 | v13 inline | 19/24 | 35/57 | 5/19 | 33 |
| outcome-99 step99 | native旧基线 | 24/24 | 38/72 | 8/24 | 19 |
| outcome-99 step99 | v13独立MS | 23/24 | 28/69 | 4/23 | 32 |
| outcome-99 step99 | v13 inline | 20/24 | 34/60 | 5/20 | 39 |

Qwen的“base”是已有指令训练的Qwen3-4B-Instruct-2507，不是预训练裸模型。四个v13条件都是同一种模型控制全体玩家的同质团队实验。

独立MS在Qwen/outcome各有22/29次轮次成功，但终局分别只保留21/28场；说明后续动作还破坏了一场已成功的旧会议。不能把累计成功数当最终协调成绩。

只给缺失局每局0至3场的范围、不补猜结果，全24局终局有效会议数范围为：Qwen独立MS **21–24**，outcome独立MS **28–31**，Qwen inline **35–50**，outcome inline **34–46**。这些是未观测局结果的边界，不是置信区间或实测全套分数。独立MS即使把缺失局按最好结果计，也低于旧native的观测总数；inline的范围则跨过native，不能下全套优胜结论。

## 同题比较

每一行只采用两个条件均完成的题；不同表行的题子集不同。

| 比较 | 共同完成局 | 前者→后者有效会议 | 后者逐题胜/负/平 |
|---|---:|---:|---:|
| Qwen native→独立MS | 23 | 35→21 | 3/10/10 |
| Qwen native→inline | 19 | 31→35 | 7/5/7 |
| Qwen 独立MS→inline | 18 | 16→33 | 12/2/4 |
| outcome native→独立MS | 23 | 37→28 | 3/9/11 |
| outcome native→inline | 20 | 30→34 | 7/5/8 |
| outcome 独立MS→inline | 19 | 20→33 | 10/3/6 |

三种条件共同完成的子集：Qwen18题native/独立/inline为29/16/33场；outcome19题为29/20/33场。这里仍然条件化于完成，不能消除“恰好困难题中止”的选择影响。

同模式跨模型对比：独立MS共同22题Qwen20场、outcome28场；inline共同17题Qwen33场、outcome29场。因此当前不能声称“后训练＋MS总是进一步提升”，也不能简单按各自不同完成子集的比例比较模型。每题只有这一次保存轨迹，没有重复采样误差估计。

## 实现与比较条件核验

- 同模型native/独立/inline的模型safetensors哈希相同；24题的完整scenario相同。没有通过不同题或权重解释差异。
- 48个无历史的首发玩家状态（两模型×24题）中，inline请求与native请求前缀逐字相同，仅最后user多出注册的通用MS后缀。后续状态已经受各自行动影响，不能当作同状态反事实。
- 独立MS接受的Qwen1081、outcome1033个动作请求，均续接真实MS请求并原样追加真实MS输出；剩余预算都等于4096减MS实际completion tokens。
- 已送达收件箱内容在配对的MS观察中逐条核对，见analysis.json的contracts字段；没有重现v11首轮收件箱丢失。
- Qwen25、outcome27个决策重试全部包含完整DECISION阶段合同，包含禁止DM和当前会议schedule要求。Qwen无DM重试；outcome有1次DM，属于看见规则后仍生成违规动作，不是同样的指令丢失。
- outcome `replan_varied_s2` 的2322-token MS包含动作JSON，v13确实接受并原样传给ACTION；该局完成但终局0场有效会议。删除格式检查解决了该拒绝路径，不代表内容因此正确。

**native基线有独立的完成性混杂因素。** 旧Qwen native保存了3次`finish_reason=length`，分别在`dense_uniform_s3`、`dense_varied_s3`、`replan_varied_s3`；旧outcome native有3次length，均在`blocked_uniform_s3`。旧runner仍继续并完成这些游戏，没有v13的“该prompt相同请求重试一次、再截断则中止局”处理。故旧native的24/24不能直接当成相同退出策略下的稳定性证据。不能从保存轨迹猜测一次新重试的实际结果，需同版本native重跑才能作严格比较。

新运行根目录保存了pipeline_snapshot、execution_identity；本地这个最小包未包含逐局pipeline_snapshot等原运行的所有附属文件。缺失参数不以今日默认补全。outcome独立MS运行观察到完整H100 NVL，另外三个新条件是47GB MIG；不将墙钟时间当相同硬件的速度比较。上述限制不影响从完整wire请求和环境事件定位文本/行动错误。

## 失败类型已经改变

下面按**轮次resolution**分类，与终局保留会议不完全相同，且各条件完成局数不同，不能直接当统一分母的失败率。

| 条件 | 不同玩家提交不同位置 | 至少一人没有有效位置提交 | 轮次成功 |
|---|---:|---:|---:|
| Qwen native | 29 | 6 | 37 |
| Qwen独立MS | 42 | 5 | 22 |
| Qwen inline | 16 | 6 | 35 |
| outcome native | 31 | 3 | 38 |
| outcome独立MS | 37 | 3 | 29 |
| outcome inline | 15 | 11 | 34 |

v12→v13独立MS的共同完成题中，Qwen23题有效会议为24→21，outcome22题为30→28。修复某条协议错误并未带来整批成绩上升；纠错后的动作还会改变后续环境和对话，不能把“工程修复通过”当成“协调能力提高”。v13同时删除了MS格式检查，也不是单一改动的效果实验。

上次v12 Qwen有17轮因缺少提交失败，本次独立MS为5轮（完成集合不同，不能把下降12轮全当修复的因果效应）。当前独立MS的突出问题已经是**提交了各自的合法选择，但并未达成共同选择**。

inline并未全面提高动作执行能力。共同完成题上，Qwen独立MS→inline语义错误25→33，outcome23→37。新运行的错误分类：Qwen独立MS占用目标18、缺schedule7、错item2、重复目标2；Qwen inline分别14、6、2、11；outcome独立MS分别26、1、1、4；outcome inline分别24、3、2、10。协调更多但更多无效动作可以并存，因为一次重试有时能修复错误，也因为失败原因分布不同。

## 具体轨迹一：重试修复救回了一个会议

outcome `dense_uniform_s1` 第一场，Agent0的slot5实际有errand #5，MS却认为自己没有安排，ACTION直接schedule5并被拒绝。

- v12的下一次ACTION只发DM，试图重开协商，最终缺schedule，会议失败。
- v13的Agent0同一逻辑call5生成 `reschedule(item5,5→2)` 加 `schedule(meeting1,5)`；三人最终都提交5，该轮成功。

这是“具体合同恢复改变输出”的直接轨迹证据，但两版还同时有删除MS格式检查的改变，且后续轨迹会分叉，不能用这一例估计整批修复效果。v13初次MS读错日历仍未消失。

来源：[v13 Agent0调用](../../../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/dense_uniform_s1/transport-agent-0.jsonl)、[MS](../../../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/dense_uniform_s1/ms/transport-agent-0.jsonl)、[环境事件](../../../../runs/calbench_soc/outcome99_belief_v13_r2-stream-1065395/games/dense_uniform_s1/events.jsonl)。

## 具体轨迹二：独立MS把偏好变成不存在的共识

Qwen `loose_varied_s1` 第一场：Agent0最终坚持slot1，Agent1/2坚持slot4。Agent1的MS认为Agent0已经认可4，实际上没有收到这样的确认；还声称Agent0原提议slot5会迫使自己移动高成本errand，但自己的slot5在日历上是空闲的。Agent0的MS则声称slot1是唯一可不移动自己errand的空闲位置，实际自己的1/2/5/7均空闲。

这些不只是“对心理状态的不同合理猜测”，还包含可直接核查的日历和对话事实错误。ACTION随后将这些错误叙述当作理由，分别提交1、4、4。该局独立MS终局0/3，而native和inline分别3/3。

inline的第一场轨迹通过告知Agent0在slot4有cost8的errand，改谈slot5，最后三人都提交5。**但成功并不代表MS正确：** inline Agent1的thinking却把“slot4的errand需要移动”理解成Agent0愿意把errand移到slot5；这与实际“在空闲slot5开会、无需移动errand”不同。行为协调成功掩盖了错误的他人状态叙述。

所以较稳妥的解释是：inline保留原生行动上下文，与行动一起生成分析，观察上有更好的协议协调；独立MS存在错误判断被下一阶段沿用的轨迹。不能仅据此证明显式MS是在准确地执行ToM，也不能区分“额外思考”与“特定心理状态思考”的贡献。

来源：[独立MS事件](../../../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/games/loose_varied_s1/events.jsonl)、[独立MS Agent1](../../../../runs/calbench_soc/qwen4b_belief_v13_r2-stream-1065394/games/loose_varied_s1/ms/transport-agent-1.jsonl)、[inline事件](../../../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/games/loose_varied_s1/events.jsonl)。

## 具体轨迹三：inline能使用新信息，但不保证复杂约束下退出

outcome `replan_varied_s1` 最后一场：Agent0先提议slot0，Agent2/3指出该位置已经被前一会议占用，并建议2。Agent0随后改选2，三人一致提交2，整局3场均成功；native该局1场。这是合理的信息更新和协议协调的正面例子，仍不能单独归因于MS而排除更长thinking/输出扰动。

相反，Qwen `blocked_uniform_s3` 的决策重试在thinking中反复讨论“slot7是自己唯一空闲位置、Agent2在7有硬block、必须提交、又不能这样提交”，直到4096-token截断。其他中止也反复在“不允许占用/没有共同空闲/不应移动承诺/必须给动作”间循环。有些叙述把敏感errand视为不可移动承诺，或把没有共同确认位置理解成不能给任何有效个体提交；这些是可见推理模式，不是证明整个环境真的无解。

9个inline中止局分布为4个dense、4个replan、1个blocked；6次发生在验证重试、1次在首次DECISION、2次在CHEAP_TALK。全部两次尝试的响应文本哈希一致。重试提供了规定的第二次机会，但没有给这些确定性循环带来新结果。独立MS另有Qwen1个MS循环与outcome1个ACTION循环，均重试后仍截断。逐次头尾、阶段、用量和文件位置见analysis.json的failures。

来源：[outcome成功例](../../../../runs/calbench_soc/outcome99_inline_v13_r2-stream-1065397/games/replan_varied_s1/events.jsonl)、[Qwen循环](../../../../runs/calbench_soc/qwen4b_inline_v13_r2-stream-1065396/games/blocked_uniform_s3/transport-agent-0.jsonl)。

## 资源消耗

包含失败尝试的实际计数：

| 条件 | 物理调用 | prompt tokens | completion tokens |
|---|---:|---:|---:|
| Qwen独立MS | 2164 | 7,879,792 | 334,627 |
| Qwen inline | 958 | 4,768,997 | 296,835 |
| outcome独立MS | 2069 | 7,356,335 | 312,961 |
| outcome inline | 944 | 4,570,629 | 277,648 |

inline总token比独立MS分别少38.3%/36.8%，但这是整个实际运行计数，包含完成不同题数、早停和不同轨迹，不能解释成固定同工作量下的节省。每次行动都是上限4096，不等于真实test-time算力相等。独立MS普通ACTION均值约144/145 tokens；MS均值约165/157（含失败尝试），大部分回合并非预算被正常MS耗光。inline输出均值约310/294、median约248/240。约束冲突导致的少数极长循环与正常较长thinking需要分开看待。

## 对研究假设意味着什么，以及下一步

当前最有支持的结论是：**prompt的接入方式显著影响协调；单独增加一段显式心理状态文本并不会自动提高能力；MS错误可被后续行动沿用。** inline在完成子集上的结果比独立MS好，但更多中止和执行错误仍需要处理。当前数据不支持“后训练与MS稳定叠加提升”的结论。

下一步优先级：

1. 补同一v13 runner/退出策略下的两模型native对照，使用新输出目录保留旧身份；先使稳定性和全套成绩可比。此项仅建议，本次未启动。
2. 把完成率、中止原因、有效会议数与无效动作分开报告，固定24题不按成功/中止筛题；未知结果保持未知。
3. 若要判断“MS本身”是否有效，加入通用简短分析、相近输出长度的对照，并比较同一环境状态下的输出。当前两阶段还改变了指令位置，inline还改变了thinking历史，不能把两者差异全称为分阶段的因果效果。
4. 对同一批节点分别标记本人日历事实、对话承诺、他人状态推断和最终动作合法性；不以漂亮MS文字或最终成功代替这些指标。当前未做全量人工语义标注，不报告猜测的错误率。
5. 只有确定需要新的循环处理/预算/解码策略后才另建版本。直接加大token上限不针对当前自我重复机制；本次不修改prompt或解码，也不擅自追加实验。

## 其余历史目录

| 目录 | 保存的题数 | 已调度会议 | 比较身份 |
|---|---:|---:|---|
| bp-step139-formal-857442 | 12 | 5 | 旧12题formal，非当前24题MS条件 |
| mixed-step59-formal-857444 | 12 | 5 | 同上，不同checkpoint |
| selfplay-step69-formal-857446 | 12 | 6 | 同上，不同checkpoint |
| new-bp99-866677-biinv-v1-stream-868933 | 24 | 36，终局36 | 旧checkpoint/native条件 |
| old-bp99-860494-biinv-v1-stream-868934 | 24 | 44，终局44 | 旧checkpoint/native条件 |

12题formal旧结果没有保存当前diagnostics的final_valid_meetings字段，保持未记录，不能填0。旧24题的36/44不自动并入本次模型配对；当前主要对照只采用已核对权重哈希的Qwen与outcome-99基线。
