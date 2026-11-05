# 用户草案审阅与题面v4

2026-11-05。采用用户给定的共同规则system＋当前状态user＋原具名tools布局；用户随后明确“保持现有回应平局规则，只改表达”。此前短system选择由这次完整草案覆盖。原稿逐字保存在[USER_DRAFT.md](versions/native800_prompt_score_v4_20261105/USER_DRAFT.md)，v1/v2/v3关闭快照保留。

[完整实际system/user/tools预览](versions/native800_prompt_score_v4_20261105/PROMPT_PREVIEW.md)包含8种原生状态；每个JSON由实际Decision.request导出，预览的评分段仅供人审，不发送给模型。[设计](versions/native800_prompt_score_v4_20261105/DESIGN.md)、[参数与source](versions/native800_prompt_score_v4_20261105/SNAPSHOT.json)、[数据绑定](versions/native800_prompt_score_v4_20261105/DATA_BINDING.json)。

## 对用户草案的处理

- 共同规则放system、具体玩家/目标/偏好/历史/状态放user，可以清楚区分稳定规则与每次变化的状态。这里不是要求模型进行两次调用：一次request仍同时携带system、user、tools。
- 开头改成自然英语，并只要求自身预期最终收益；指向下方回应平局规则。没有采用“helping each other as much as you can”这个可被解读为所有行动都合作的目标。回应仍先最大化自身，再在自身平局时比较其他玩家预期最终收益总和，最后平局两者皆可；proposal不添加合作优先级。
- 保留v3精确数值规则、其他玩家总收益限定和起始独立1/3先验。仍说明偏好固定、根据可见证据更新；不强制输出算式。具名tools及合法参数、解码、scorer-v1逐字不变。
- GOALS AND CURRENT STATUS合并完整目标要求与当前状态。每项required commitment写名称和[committed]/[missing]，另列当前共享完成度；不只列尚缺项，以免丢失linear分母和完整规则。pending不计入。
- 合并表逐项状态已经披露全部当前承诺，不再重复CURRENT COMMITMENTS表。当前100父游戏的每项行动至少用于一个目标；未来若有未用于目标的行动，会单独披露其状态，避免丢失报价合法性所需事实。
- 一笔offer与response使用同一历史条目。待回应时以“These proposed additions are not yet binding.”结尾；收到回应后替换为“Alex chose REJECT on this proposal. No commitments were added.”，或“Alex chose ACCEPT on this proposal. These additions are now binding.”。不会在已解决报价上同时出现not-yet-binding与ACCEPT/REJECT。原机会编号保留。
- 本人的真实调查答案继续在每次private information重建并持续显示，公开调查记录保留，不增加来源标签/他人私有答案或assistant解释记忆。

## 历史物理表与主S

省去每条历史before/after表不是直接假定无影响。承诺单调增长、完整当前状态始终披露。逐条遗漏一个原生事件时，用当前承诺减去其余已接受NEW additions的并集，得到被遗漏事件的新增承诺；原编号确定其位置，从而恢复其余事件的历史before/after状态。2046次单事件遗漏检查全部一致。因此这次表示变化对主S的逐条遗漏保留了原可见物理信息，不改原Q/S；此保证不推广到联合遗漏多条历史的独立诊断。

## 实际验证与边界

800入口完整承诺与goal完成度、5493合法工具调用及评分、3044同信息world对照通过，其中2244为不同world；7项原评分单测通过。2046历史单条遗漏下剩余事件状态可恢复。三本人决策CPU路径中调查答案持续出现。与v3全部800工具schema逐项相同，评分源码未改。

首次CPU检查暴露调查事件只有to_dict()提供action字段，而非对象属性。失败run、当时source与注册均保留；修正为读取原生序列化字段后，第二次全量CPU通过。这是题面适配器实现检查，非游戏/求解器/模型失败。

实际成功run：[pipeline_snapshot](../../new/native800_prompt_score_20261105_runs/cpu_v4_attempt2/pipeline_snapshot.json)、[SUMMARY](../../new/native800_prompt_score_20261105_runs/cpu_v4_attempt2/SUMMARY.json)；首次失败另存cpu_v4/FAILED.json。新版D必须重新绑定prompt-v4测量，未沿用历史D。未调用模型/GPU、未训练，完整D/collector/SP迁移尚未完成；旧生产active v8不变。

用户已直接编辑v3预览的首个示例，使该预览不再匹配v3关闭时的hash；本次保留该用户修改，没有恢复或覆盖。原v3实际请求与完整原始预览仍保存在cpu_v3/previews，hash与旧EVIDENCE一致。此差异单独记录于新run的closure_validation.json，不把用户草案当作旧实际请求。
