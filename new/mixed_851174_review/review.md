# mixed-851174：40 步诊断

证据来自下载目录的 metrics.jsonl、phases.jsonl、resolved_config、experiment、四份含原始回答的 validation 和 checkpoint COMPLETE 标记。复算脚本 analyze.py，统计 summary.json。本次只分析，未改变训练目标或数据。

## 结论

不能把本次结果当作健康训练下“混训无效”的证据。首步 KL 估计和梯度范数极端异常，vLLM behavior 与 Megatron actor 概率也存在持续明显差异。参数并非完全没有更新：首步检查的145个norm张量中60个发生变化，优化器步数记录为每batch一步；这不足以证明所有权重、同步和参考模型均正确。

初始 actor/kl=7.276e9、loss=2.983e7、pg_loss=.218、grad_norm=1.041e11。此处KL是代码的 exp(ref_logp-actor_logp)-(ref_logp-actor_logp)-1 样本估计，不是精确全词表KL；尾部异常可被指数放大。KL日志为未按任务权重统计的行均值，loss按权重计算，不应简单拿两者相乘。仍可判定首步总loss远大于PG项，提示异常KL项占主导；不能仅凭标量证明各项梯度贡献。

首步更新前 actor/behavior token logprob绝对差均值.684、最大14.38；第40步均值.712。第一步actor与reference应源于同一初始checkpoint，不能以训练后正常漂移解释如此巨大的首步KL。优先检查HF reference、Megatron转换和vLLM同步，以及token位置/顺序/屏蔽对齐。缺少逐token actor/ref配对记录，目前不能定位具体出错组件。不要用关KL、clamp或增加训练步数掩盖该问题。eager绕开图执行崩溃，不自动解决概率不一致。

## 固定小验证集

| 更新数 | B正确 | P正确 | P调查次数 | SP平均玩家终局utility |
|---|---:|---:|---:|---:|
|10|4/14|7/22|6/22|1.0000|
|20|3/14|4/22|12/22|0.8125|
|30|2/14|3/22|14/22|0.5000|
|40|4/14|3/22|15/22|0.5000|

每次B只有7题×2重复，P11题×2，SP只有2初始局×2；没有step0同口径基线，SP双方都随策略变化，不是固定对手评估。此表只能说明小样本观察，不能给泛化结论。

P解释从21/22降为12/22；SP解释43/49降为12/42，平均输出446.5降为151.0 tokens。P题2bec249ba428ff3270c5是末次机会状态：step10尚有讨论终局/offer的文字，step40两个样本都只调用INVESTIGATE且得0分。不能把变短视为推理改善。B错误全集率step10与40均1/14，step20为4/14；本子集不足以断言训练整体强化了全集倾向。

## 信号与预算

B奖励混合组95/166，P111/184，SP含协议成本后的混合组742/789；SP终局utility有差异组515/789，不完整组140/789。不是完全没有可用奖励差异；这些计数不等于有效梯度比例或独立题目数。

已消耗6199298生成tokens，占6553600预算94.6%。因此40步并非只训练了计划中的40%；软目标65536被完整并发游戏组显著超出，实际平均154982 tokens/update。这轮已接近预算用尽。

## 时间与缺失信息

双H100 NVL，enforce_eager=false。三个模型初始化phase合计约50.4秒，不含driver前置检查。已完成40次优化平均91.7秒，41次rollout平均95.3秒，reference平均16.2秒。最后记录含额外一次rollout，缺train.log/EXIT_CODE，不能确定最终停止原因。

下载目录没有训练calls/units/games、逐token重算概率、train.log和step0验证；有验证原始回答。下一步应做极小固定token序列的HF/Megatron/vLLM三方一致性检查，覆盖同步前后及sleep/wake，输出逐token差值、reference原始logp和最大KL位置。在此通过前，不把checkpoint39作为健康续训起点，也不据此否定混训设计。

## 2026-09-17 后续根因更正

用户服务器诊断已定位：detach共享存储被microbatch调度器原地缩放，以及Transformers5 RoPE配置迁移漏读。修复后组批误差为零、HF/Megatron平均差降至.02479，单次诊断更新KL和梯度恢复正常。参见[交接记录](../soc_runtime_fixes_20260917.md)。以上历史异常不能归咎于混训方法；本地已同步soc-runtime-fixes至d3139d0。
