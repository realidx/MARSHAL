# 一次免费调查的时机诊断v1

见[机制说明](../../examples/strategic_slices/GAME_FREE_INVESTIGATION_TIMING_20261021.md)。

`verify_timing.py`已用CPU精确分数枚举运行：

- 原三合同toy：免费开局查X达到5/3的全类型上界。
- 固定相关目标：立即/延迟查询均为1，不查1/2。
- 后续公开事件选择相关目标：立即3/4，延迟1，不查1/2。

后一个toy枚举162/324/9个完整可见信息策略，含PASS，结果和策略保存在`results.json`。
原型有明确的两组互斥偏好约束；不是当前原生游戏或三人均衡认证。

已执行命令：`/opt/anaconda3/bin/python new/free_investigation_timing_20261021/verify_timing.py`。
完整参数、环境和输入source hash在`pipeline_snapshot.json`。关闭的输出不可覆盖，重复运行会拒绝；后续变更使用新目录/版本。
无模型、GPU、训练或生产协议变更。
