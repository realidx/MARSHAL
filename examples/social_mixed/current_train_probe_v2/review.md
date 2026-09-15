# 本次用户审阅修订（以此节及重新导出的实际prompt为准）

B/P版本bp-plain-language-v5；self-play版本outcome-plain-language-v7。尚未rollout。

- 决策目标改为实现想要的目标、避免不想要的目标；仅响应别人offer且两种回应对自己同样好时帮助他人。删除expected final score、score ties及uniformly at random；self-play system同样修改。
- PREFERENCE CONDITIONS只列偏好值域、每玩家至少want一个目标、每目标至少一个非neutral玩家、共同知识及偏好不变。不再描述抽样、重抽或等概率。
- COMMITMENT OPTIONS删除not a state snapshot。
- B不再出现“assess the requested belief; do not take a game action”或重复禁令；只提供SUBMIT_BELIEFS工具。
- Preset event改为“the player was required to do this, rather than choosing it”，保留被安排动作与主动选择的事实差别。
- 删除revealed-value推导提示、枚举候选行为、保留全集/排除值、继承再更新等解题步骤。B只定义输出字段及简短解释要求。
- favored/undetermined以证据是否明确支持某个偏好表述，不以模型自己是否会做题来定义。
- 当前待响应对象与本轮之后的提案顺序分开列出；不再使用first entry includes ...括号。
- 全linear规则不提binary，全binary规则不提linear，mixed同时解释。

注意：删除先验分布和并列随机规则后，原teacher标签不一定仍由可见题面唯一支持。尤其微弱favored及P的初始分布belief需要另审。此轮只修订题面，没有悄悄修改标签或扩大undetermined判对范围；manifest已标记这两项待复核。


## 实际审阅文件

- bp_review.md：69题的实际system/user文本，requests.jsonl包含完整工具定义。
- selfplay_review.md：12个训练初始局的实际system/user文本；后续历史沿用同一动态入口。
- P4完整15核心+1诊断，包括binary/linear获取信息及全部三个结果分支；父子对应见p4_links.json。
- 其余B/P保持上轮题ID，便于后续比较；共68核心+1独立诊断，尚未启动rollout。

## 验证

本次20项回归测试通过，32个脚本完整局通过，启动前实际请求与审阅稿比对通过。生成器、teacher求解、奖励及1024输出预算未修改。下一轮的标签语义复核尚未完成；这些检查不代表新措辞已获模型效果验证。
