# B/P 与 SP：social-stable-v1

本版本是新训练阶段，不是旧配方原样续训。入口仍为 `training.social_mixed.run`，只支持 bp/selfplay。保持现有原生工具、标签、训练集和 SP 场景；本次没有按模型测试表现重新筛选数据。

## B/P

每题 8 次；每域目标 4 个不同题的奖励差异组；每 update 最多 32 个候选题组。已补满域停止采样，额度用于未满域。每域覆盖/active 槽交替；覆盖按 kernel、binary/linear、information role 分层。active 使用 update 开始前快照：最近 32 步访问过、差异组 EMA >= .05 的题；没有候选时回退覆盖。EMA 每次观测系数 .2。update 内题 ID 不重复，全部生成计费。

任务 advantage 为 reward 减组均值，不除 std；非法/截断调用任务项为零，仅保留独立协议惩罚。有效组定义仍按原始奖励差异，另报合法正确/合法错误的语义对照组数。

每域任务项为有效组/8 个回答平均，再按固定 1024 对 token 求和归一化；两域各 .5。不足额仍按实际有效组平均；空域为零，不把另一域翻倍。两域均无有效组：跳过整个 optimizer（包括协议/KL和动量），但计入生成预算和采样统计。

协议项和 KL 使用所有候选回答（含全对/全错/非法/截断）的非 padding 输出 token，每回答实际长度平均，每域候选回答平均，两域各 .5。协议 coefficient=.2，KL coefficient=.01。不同项的 mask/权重明确独立，固定 1024 仅用于 B/P 任务项。这个变化会改变相对梯度尺度，不承诺保持旧比例。

## SP

保持原有 4 replica 收集与基础场景持续曝光（已有短/中/长配额）。正常完成玩家用自身终局 utility 减 update 开始前历史 baseline；其他 replica 中止不再清除其任务信号。未完成玩家任务项为零，责任调用协议负项仍有效。

baseline 按玩家数、binary/linear、proposal slots 分桶，不依赖任意 seat 编号。桶至少 16 个历史玩家 episode，否则回退全局；无历史为 0。每玩家 episode 只记一次，批内取均值后 EMA=.1 更新，供下一批使用；统计随 checkpoint 保存。这是粗粒度方差控制，不能当作状态价值或细粒度信用分配。

保留玩家轨迹等权、轨迹内调用平均、每调用 token 平均。未完成轨迹仍计入总体轨迹分母，不把 survivors 重新归一化为整批。这仍存在完成筛选与轨迹长度权重偏差，不宣称无偏。

## LR、验证、恢复

实际 optimizer LR 在每次更新前设置为 `1e-7 + .5*9e-7*(1+cos(pi*progress))`，progress 为本批采样前已消耗 tokens / 冻结总预算，上限 1。不加 warmup。底层 scheduler 继续推进/保存，但下一步应用 LR 由 token 进度覆盖。生成预算以完整题组/已接纳完整局为边界，末批可能超过预算。

第 0 步 validation 保留；B/P 改为 temperature=0，SP 保留 1；验证版本变为 v3，不能与旧曲线直接拼接。最佳模型继续使用 checkpoints.py 的既定评分公式，严格更高才替换（并列保留较早）；最后模型单独保留。现有按步验证间隔保留，未改成 token 间隔。

同配方恢复必须保持总预算、reference、数据和 recipe，恢复采样/EMA统计及 optimizer 状态。旧配方不可直接 resume；需要导出 HF actor 后作为明确的新阶段启动。BP→SP 若使用 BP 导出作为 model，reference 也来自该起点，不能称 Q0 reference。

## 验收边界

CPU 测试覆盖固定分母公式、padding/microbatch梯度不变、候选上限、去重、全零跳过、恢复统计、SP失败不连带清零和验证。

记录加权 loss、clip fraction；每十个 collection steps 记录 log-probability 空间的分项梯度范数。此项不是模型参数梯度，也不是跨 microbatch 完整梯度；不据此宣称参数尺度验收完成。完整分布式测试需要 ray/Megatron/vLLM 环境，本地缺 ray，尚未完成 GPU 验证。没有远程提交或运行模型。

## v2 B 递进题更新

当前 recipe 为 `social-stable-v2-b-bridges`，默认数据为 data_reasoning_v6。B 候选在 likelihood/procedure/raw 间轮换，详情见 data_reasoning_v6/README.md。其余目标、SP baseline、LR 不变。v1 与 v2 不允许原样 resume；版本名由入口写入 experiment.json。
