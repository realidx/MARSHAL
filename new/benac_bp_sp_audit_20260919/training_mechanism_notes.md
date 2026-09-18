# 奖励、截断与 validation 实现核对

以下为当前本地代码实现，不替代 step139/step69/step59 实际训练记录的指纹核对。

## B/P

social_bp_training.reward 将正确答案记1，错误/格式失败/截断记0。core.assign_advantages 在同题组内中心化并标准化。八次回答全0时任务advantage全0；0分不是固定负advantage。不奖励中间解释的语义正确性。

## SP

Episode.accept 对每次非法或截断调用记该玩家 -0.1 协议罚分，给一次重试。恢复并完成后utility仍为自身终局效用；失败utility为None。分组是同一reset/同一玩家的四次rollout，不是同局不同玩家。若组内所有episode完成，advantage来自自身terminal utility+protocol；只要有一个未完成，该组所有成员暂不使用outcome，仅用protocol。episode-player advantage共享给该玩家全部调用，按unit内调用数分摊loss权重。因此一个含早先截断的高收益episode也可能获得正advantage；不是只惩罚截断那条回答。

## 输出上限及重复

本地训练配置和本次A均为max_new_tokens/max_tokens=1024。不是评测临时从更大训练输出预算降下来。A的Q0/BP/SP focal截断分别41/28/25次，全部没有生成工具调用。逐字检查：各截断输出的任意连续20词窗口均未重复（按\w+切词、小写）。该检查只能排除这种长度的逐字重复，不能排除语义反复、较短模式重复或幻觉驱动的重新计算。故增加budget可能恢复部分动作，但尚未测试，也不能保证决策正确。

## validation

当前distribution_sampling.select验证选择33/275道BP验证题，每题2个回答。其中B1=2、B2=2、B3=8、P1=2、P2=9、P3=5、P4=4、A0=1。完整局仅2个固定validation reset×2replicas=4局，每局全员当前模型，并非固定Q0对手。相同seed固定选题便于跟踪，却不能把很少结构扩展成总体能力证据。

pipeline.py把验证metrics/calls/games存入validation/step-N.json，但没有像训练metrics那样写入metrics.jsonl并调用tracker.log。collector的汇总以任务准确率、终局数、advantage组统计、截断计数为主，没有直接输出固定对手自身效用/团队效用/对手与focal失败归因。这解释了现有训练曲线为什么难以看出能力变化。

下一步应先补验证观测：独立开发集，不复用已看过A正式题来选择checkpoint；B/P细分与成对反事实；单独原始历史到动作组合诊断；固定Q0完整局并列合法率/截断率/完成率/自身和团队utility。用同一数据/推理条件评估所有训练臂。保存原始调用，将eval/...指标同步日志与tracker。尚未修改训练。
