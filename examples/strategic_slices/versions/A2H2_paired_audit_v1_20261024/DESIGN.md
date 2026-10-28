# A2H2配对机制审计 v1（运行前冻结）

用户2026-10-24同意继续。沿用复杂度研究v1已冻结的33个A2H2候选，与同33个H2配对；不根据结果改题。
增加一名玩家的第二个承诺选项，并将其一个原有目标改为需要该选项；依然是累计承诺，没有加入互斥规则。
隐藏偏好、独立均匀先验、2RR、调查1、报价1、每个报价每方最多新增1项均不变。

求解沿用three-player-complexity-study-v1，无source/default修改。实际run单独保存完整CLI/config/source与输入hash。
A2H2首次完整尝试：workers=2、memory_gb=0（macOS不声称施加内存限）；其余remote默认值：
max_nodes600000、construct180s、solve600s、audit300s、metric1200s、case3600s；epsilon1e-8、tie1e-9；
inertia_then_joint、max_sweeps512、joint_evaluations400、repair_passes8；只接受完整终局数值认证profile。

本报告脚本相对父稀疏S诊断新增：
- 只读比较A2H2/H2，覆盖均保留33局；标签缺失保留身份，配对统计仅取两臂均测量交集。
- 主own S、社会response平局信息诊断分列；终局response诊断核对保存的实际secondary loss。
- 同public node/own type/其他调查答案下，比较遗漏同一私有答案后可兼容场景的own最优动作交集。
  proposal没有共同最优且私有S为正，才计入相应信息改变当前行动的组；不把response平局当proposal改进。
- context比例、父游戏等权比例、reference决策占用权重分别报告，不冒充模型访问频率或D。
- 严格最优调查另查答案是否已可按reference推断；不把全部query gap叫作信息获取价值。

不改变游戏/求解/主Q/S/prompt/reward/advantage/采样/训练，active仍v8。
本冻结时报告尚未运行；完成情况另写EVIDENCE及execution_records，不回填或覆盖本快照。
