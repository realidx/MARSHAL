# Native800题面第三轮审阅：状态记账与belief/planning

2026-11-05。用户提出8项审阅意见，已制作`native800-prompt-score-v3`供检查。
新完整[system/user/tools预览](versions/native800_prompt_score_v3_20261105/PROMPT_PREVIEW.md)，
[实际response JSON](versions/native800_prompt_score_v3_20261105/response_social_tie.json)。评分小节只供人审，不是模型输入。
旧v1/v2与800数据不覆盖；本次评分组件仍为原`native800-response-lexicographic-regret-v1`。

## 1. System和user的区别，是否必须拆开

System承载通用角色/行为约束，本项目只保留9月“遵守可见信息、简短解释、一次工具调用”的短规范。
User承载当前游戏规则、事实与当前决策。两者经chat template编码成一个token序列，并非两次采样或两个模型。
角色标记是模型训练格式的一部分；不应把system更长或内容重复当作推理能力更强。
[Transformers官方chat template说明](https://huggingface.co/docs/transformers/main/chat_templating)解释了角色与序列化关系。

这里不是必须拆成两条人工message。保持模型原生template的前提下，可以把所有人工内容合并到user。
本项目没有做过对照来证明拆分更好；当前保留两条，是延续用户上次明确选择的9月接口组织。
工具仍在独立schema字段给出，最后由模型原生模板处理；它不是另一段需要模型单独作答的题。

## 2. 删除inferred preference仍可调查的句子

已删除“A preference you inferred from behavior is still eligible if it meets those rules.”。
保留“他人、非公开、本人未直接查过”的合法性定义，注册tools仍列出实际合法组合。
环境没有因为推断已确定、Q/S低或实际world而删除目标；游戏/Oracle/合法行动不改。

## 3. Response tie-breaking的自然表达

采用更口语化的版本，但保留复数和总收益限定：三人局可能帮助一名玩家同时损害另一名，
只说“favours other player”不足以确定选择，不能与现有sum-of-others评分默认为同一规则。

```
Response tie-breaking (for EVERY player): When responding to an offer, first maximize your own expected FINAL score using the information available to you. Only if ACCEPT and REJECT give you the same expected final score, prefer the response that favours the other players more overall (a higher total expected final score for them). If both levels are tied, either response is acceptable.
```

规则标题已限定response，去掉原句末重复的proposal提醒；软件仍不在proposal平局时加社会目标。
没有改变score、参考策略、Q_others定义、数值容差或GRPO。

## 4. 每个decision point给当前目标进度

赞成。v2本来已给当前承诺，所以不必单靠history恢复所有当前物理状态；但仍要自己把目标要求与承诺逐项对照。
v3补充CURRENT GOAL STATUS，减少这部分记账，保留belief和后续行动取舍。

目标完成度是全局共享的；各玩家偏好不同，得到的收益才不同。不能说“Alex单独完成了该goal”。
新表逐goal列每名玩家满足/需要的承诺数、当前完成度、还缺的承诺。真实例子：

| Goal | Alex | Blair | Current completion | Still needed |
|---|---|---|---|---|
| Orchard（binary） | 0/1 | 1/1 | 0 | Alex.Maple |
| Garden（linear） | 0/1 | 1/1 | 1/2 | Alex.Cedar |

这里只算已经接受的承诺，不把pending offer算作已生效；也不给未来动作效果、最优行动、推断偏好、posterior或预期收益。
当前承诺表仍完整保留，包括未参与任何goal的承诺，不能只靠目标进度表反推全部物理状态。

信息一致性理由：新表是`f(当前commitments,公开goal要求)`，两项都在原完整/所有允许遗漏条件中强制保留。
所以它不会进一步区分原Oracle的遗漏信息集，不是新的可消融S信息项，不需要重算Q/S。
这不意味着模型难度完全不变：它正是为了降低人/模型记账负担，模型D必须绑定新题面测量。

800节点的新completion与原生goal_satisfaction全部匹配；2046次逐条移除公共历史、以及每节点清空私有结果而保留物理状态，状态表均不变。

## 5. 要数值计算，还是“多完成want、避免avoid”

保留精确数值规则，不强制模型输出算式或逐动作数值。自然语言解释可以围绕belief与planning展开。
“多完成want、避免avoid”是直觉，不能完整替代现有优化目标：linear有分数完成度、avoid有负收益、不确定性还需要期望比较。
例如一个want全完成同时一个avoid全完成得0；只有半个want完成、没有avoid得0.5。只强调want数量可能选错。

因此v3没有改binary/linear、want=+1/neutral=0/avoid=-1或expected final score，也没新增“枚举全部终局/输出精确计算”的格式要求。
进一步改变效用形式会改变游戏/solver/标签，不属于本轮题面简化。

## 6. 背景偏好分布有多重要

它定义开局不确定性。未知偏好的概率会影响belief更新、预测回应、调查价值与最优动作；无共同先验，一般不能唯一复现当前Oracle的期望Q/S。
某些节点的最优动作对先验不敏感，但不能因此在整个题库都不提供它。

v3将其压成短段：非公开偏好开局独立抽取，want/neutral/avoid各1/3；玩家共同知道，偏好之后固定，根据自身信息和公共历史更新belief。
这里的1/3是起始概率，不是每步重新抽取，也不是每个历史之后的posterior仍为1/3。
完整catalogue与记录均匀先验等价检查保留，未把独立关系或联合限制静默省掉。

## 7. Observed player choice与binding状态是什么

Observed player choice来自9月题面，用来区别玩家主动选择与外加preset事件；当前新800原生历史均为玩家行动，反复写此标记没有额外信息。
v3改成直接“1. Alex investigated...”“2. Blair passed...”等编号行动；行动者、参数、回应及完整历史顺序均保留。

历史中的before表表示该次offer提出前已接受的承诺；after表实际是该次response之后的承诺。
OFFER只提出新增；ACCEPT才生效；REJECT不增加。这些是历史时刻的物理快照，不等于当前状态。

ALREADY ACCEPTED COMMITMENTS表示**现在已经被接受、仍生效的全部承诺**，不是pending offer。
v3改名CURRENT COMMITMENTS，并说明pending新增不计入；proposal和response都显示它。
历史快照目前完整保留，只改普通Commitments wording，不删掉可能影响既有历史S条件的信息；当前目标进度已单列，玩家无需靠历史重算现在。

## 8. 删除工具参数重复段

已删除从“OFFER takes partner...”到“Use one of the legal argument combinations...”整段。
工具JSON schema已经提供字段、类型及合法组合；实际tool interface和decoder保持原样。
仍要求brief explanation、解释在参数外、一次注册工具调用；没有把结构化行动改成随意文本。

## 实际文件与验证范围

- [v3实现合同](versions/native800_prompt_score_v3_20261105/DESIGN.md)、[request源代码](native800/prompt_v3.py)、[共享scorer（未改）](native800/scoring.py)。
- [完整请求预览](versions/native800_prompt_score_v3_20261105/PROMPT_PREVIEW.md)、[数据绑定](versions/native800_prompt_score_v3_20261105/DATA_BINDING.json)。
- [本轮实际snapshot](../../new/native800_prompt_score_20261105_runs/cpu_v3/pipeline_snapshot.json)、[CPU汇总](../../new/native800_prompt_score_20261105_runs/cpu_v3/SUMMARY.json)。
- 800入口、5493合法工具round-trip、3044同信息world对照（含原world800，额外不同world2244）通过；与原profile协议最优集合一致。
- 原7项评分单测和三本人决策调查答案持续披露核验通过；40social构造组的原GRPO正负advantage检查通过，非实际模型采样效果。
- [关闭验证](../../new/native800_prompt_score_20261105_runs/cpu_v3/closure_validation.json)、[关闭证据](versions/native800_prompt_score_v3_20261105/EVIDENCE.json)。

800/父池/主Q/S/scorer/GRPO/旧版本不改；未做GPU、模型D或训练，完整D/collector迁移仍后续工作，旧active v8保持原身份。
