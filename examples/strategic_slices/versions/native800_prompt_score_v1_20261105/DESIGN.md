# Native800完整题面与回应协议评分v1

2026-11-05。用户明确授权先修改prompt与回应评分，并选择保留9月短system＋user＋具名tools。
适用于冻结新800候选；旧v8及全部已关闭历史快照保留，未切换旧训练入口或启动模型/D/训练。

## Prompt相对于v8与v9审阅草案

- 短system逐字沿用9月D；具名OFFER/PASS/INVESTIGATE/ACCEPT/REJECT与原生合法组合schema不改。
- 保留9月可读表格/完整公共历史与brief explanation要求，不新增解释reward/最小token数。
- binary/linear计分集中GAME RULES；目标表只作一句解释。
- 每个proposal/response都给同样完整规则、目标、公开/自身私有事实、生成概率、公共历史、已生效承诺、proposal顺序与各玩家剩余额度。
- 当前状态区分无pending的proposal与待接受/拒绝、尚未生效的offer；已生效承诺在两种状态都披露。
- 明确报价提出即扣个人offer额度、拒绝不退、回应不扣自己的报价额度；调查消耗proposal、只查未公开/本人未直接查过的他人偏好。
- 调查行为公开、答案私有。每次request按实际查询历史与真实world重建本人累计直接答案；不把对手私人答案或推断出的偏好填入事实表。
  克隆actor视图，不改原公共树/另一玩家的状态；不依赖模型记住之前答案，不额外携带assistant解释历史。
- 公共与额外私有偏好分开，不加“谁由调查知道了什么”来源标签。先验证catalogue独立Cartesian且与记录的均匀先验一致，才写独立1/3；否则拒绝渲染。
- 全体仅ACCEPT/REJECT自身预期终局效用平局时favor他人总收益；不扩展到proposal、不声明剩余平局必须均匀（保存reference可非均匀）。
- 删除exercise-window/cutoff/precomputed策略等内部说明，玩家目标仍为原生终局。

## 同一节点的评分合同

输入为原profile的全部合法动作own Q与Q_others；两者使用相同完整后续策略/当前信息，主Q/S/reference不重算、不改定义。
proposal使用own负regret。两个原生回应own Q不平局时也用own负regret；只有两者均own最优时切换为others-sum负regret。
轴由整个节点统一确定，不能给同一组不同采样各自选择评分轴。禁止固定加权总分补偿自身损失。
正确集合统一使用原decision_policy.helper与保存profile的1e-9平局容差；旧v8正确性1e-7不冒充新合同。
无效/截断仍取当前轴最差合法reward，另保留-0.2协议惩罚；基础设施错误不算模型reward。
GRPO同题组内sample-std advantage保持原样，未设计新的训练算法；连续reward单位保持原生效用。
own terminal D、社会次级regret与协议正确率分别记录；本次不擅自激活一个混合D或新D选题排名。

## 实现与验证范围

新增examples/strategic_slices/native800包的request/scoring/Decision接口，供新800的D/验证/训练适配器显式调用。
绑定原生全局node与profile，核对合法动作/actor/自有信息/条件world，拒绝零CF旧fallback。
旧生产训练/评测request及score不静默修改，正式训练采集/完整D runner迁移尚未完成，active仍v8。

CPU验证全部800实际生成request；完整偏好事实、隐藏world不泄漏、工具一一round-trip、每个合法动作协议正确性匹配旧profile.optimal。
真实40social回应在原GRPO函数下应有非零task advantage；合成检查禁止牺牲own换others、proposal不favor、双层平局均合法。
原生支持路径回放三次本人决策验证调查答案持续存在；这是CPU检查，不是模型采样或效果实验。
导出实际函数的完整system/user/tools实例与全800request hash，每次运行有CLI/source/data/environment完整snapshot。
未做GPU、模型D或训练；源数据及旧D保持原身份，新prompt不能复用旧D名义。
