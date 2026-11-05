# Native800题面v3：降低状态重建负担

2026-11-05。用户逐项审阅8点：解释system/user，删推断仍可查提示，简化回应平局措辞，
希望把理解负担降到belief/planning，讨论数值计分/先验，理解历史与当前承诺，删工具参数重复说明。
保留用户此前选择的9月短system＋user＋具名tools；不改scoring-v1/原生游戏/800名单/主Q/S/GRPO。

## 逐项实施

- 删除“A preference you inferred from behavior is still eligible...”整句；原生合法性和tools enum不变。
- 回应句改自然表达“favours the other players more overall (a higher total expected final score for them)”；
  保留复数与总收益限定，避免三人局“帮助某一人”歧义。标题限定response，去掉句尾重复proposal提醒，评分仍不对proposal用social。
- 新增CURRENT GOAL STATUS：逐goal、逐player列已满足/所需承诺数、全局当前完成度与缺少的承诺。
  goal是所有玩家共享的完成度，不称某player独立完成goal；不同玩家偏好决定各自收益。
  只根据公开goal要求和当前已接受承诺计算；不计pending新增、不算预期收益/最优动作/hidden preference。
- CURRENT COMMITMENTS替代ALREADY ACCEPTED COMMITMENTS标题，解释已接受且仍生效、pending不计入。
- 历史事件直接以编号＋actor行动描述开始，去掉重复Observed player choice标记；
  原历史每个动作、回应、参数及历史承诺before/after表完整保留，caption改为普通Commitments wording。
  不删除history：它仍是belief证据，也不删除对既有S信息口径可能重要的历史物理快照。
- 保留精确binary/linear/＋1/0/−1计分和expected final score目标，不强制输出数值/枚举所有终局。
  “尽量want、避免avoid”可作直觉，不替换Oracle所用精确规则。
- 先验压成短段，仍明确起始独立1/3、共同知识、偏好固定、之后用证据更新；保持原catalogue/记录先验等价验证。
- 删除“OFFER takes...INVESTIGATE takes...PASS/ACCEPT/REJECT...”及其legal argument重复段；
  实际JSON schema、具名动作参数和解码不改，brief explanation＋一次工具调用要求保留。

## 对信息与标签的影响

新增目标状态是f(公开goal要求,当前commitments)，两者本来就在所有完整/遗漏信息条件中强制保留。
因此它不会进一步分裂Oracle遗漏信息集，不是新的S信息项，不重算或改名现有Q/S。
此推论不适用于直接给posterior、推断偏好、当前最优动作或预期效用；本版本不给这些内容。
presentation可能降低模型认知/记账负担，模型D必须绑定本版重新测；未用旧D宣称新效果。

## 验证

新源码AST检查后冻结；同一800CPU request/score审计、全部合法工具round-trip与profile最优集合匹配。
逐800节点，目标完成度与原生goal_satisfaction独立对照；逐条删除历史、清空私有结果但保留当前承诺/规则，目标状态表不变。
同信息隐藏world请求不泄漏、累计调查答案三本人决策持续保留、旧7项评分测试沿用。
实际完整system/user/tools预览和JSON按新request函数导出；每次run完整pipeline_snapshot记录。
评分源文件、800及父池hash、旧关闭版本与生产v8不改；未运行模型/D/GPU/训练，完整runner迁移仍后续工作。
