# 新800：可读题面与回应协议评分

2026-11-05。按用户要求保留**9月短system＋user＋具名tools**，完成新800的request/解码/回应评分适配器。
当前审阅版本是`native800-prompt-score-v2`，评分组件为`native800-response-lexicographic-regret-v1`。

## 在哪里看修改后的完整prompt

- [完整system/user/tools与逐动作评分预览](versions/native800_prompt_score_v2_20261105/PROMPT_PREVIEW.md)。
- [两人proposal实际请求JSON](versions/native800_prompt_score_v2_20261105/proposal_two_player.json)、[三人proposal](versions/native800_prompt_score_v2_20261105/proposal_three_player.json)。
- [自身平局的回应实际请求](versions/native800_prompt_score_v2_20261105/response_social_tie.json)。
- [调查后的proposal](versions/native800_prompt_score_v2_20261105/proposal_after_investigation.json)、[调查后的response](versions/native800_prompt_score_v2_20261105/response_after_investigation.json)。
- [已有承诺的proposal](versions/native800_prompt_score_v2_20261105/proposal_existing_commitments.json)、[报价额度耗尽的proposal](versions/native800_prompt_score_v2_20261105/proposal_offer_quota_exhausted.json)。

这些JSON由实际`Decision.request`生成。预览MD里的评分小节只供人审，不在模型request中；不能把整份MD当模型输入。
所有800实际请求另外保存为CPU审计各父目录中的`requests.jsonl.gz`，文件hash已记录。

## Prompt具体变化

| 项目 | 新800处理 |
|---|---|
| System | 逐字保留9月D短system，不采用v9草案的单user方案 |
| Tools | 保留具名接口、原生合法参数组合与解析；没有新增免费查询或Oracle工具 |
| 规则与计分 | binary/linear、最终效用、报价/调查消耗均集中GAME RULES |
| Offer额度 | 提出就扣、拒绝不退；回应不扣回应者报价额度，逐玩家显示剩余数 |
| 调查合法性 | 只查他人未公开、本人未直接查过的偏好；不因行为推断而删目标 |
| 公共/私有信息 | 公开表与当前玩家额外私有事实分开，无谁知道什么/来源提示，无额外推断答案 |
| 所有状态共同披露 | 游戏规则、目标表、偏好事实、概率、完整公共历史、生效承诺、顺序与各玩家剩余额度 |
| Proposal | 明确无pending；只给当前合法OFFER/PASS/INVESTIGATE |
| Response | 明确双方拟新增承诺尚未生效；只给ACCEPT/REJECT |
| 回应平局 | 所有玩家先最大化自身预期终局效用，平局才最大化其他玩家预期终局效用总和 |
| Proposal平局 | 不扩展社会次级偏好；没有强制剩余平局必须均匀的错误承诺 |
| 窗口/内部策略文字 | 去掉exercise/cutoff/precomputed接管等内容，目标仍是原生终局 |
| Explain | 保留brief explanation与工具外解释，未新增解释reward或最小输出长度 |

规则中的独立1/3先验先检查完整catalogue确实Cartesian、记录的背景权重等值；不把旧9月“每人至少want一项”等联合限制照搬到新游戏。
若以后增加dependent preference或非均匀先验，当前renderer会拒绝，必须另建题面版本。

公共树仅记录调查行为；新request会克隆当前玩家视图，根据本人直接调查的真实目标补齐累计答案。
不会修改原树、披露他人的私有答案，或把行为推断填成确定偏好。多turn仍是每次重建完整可见状态，**没有新加之前assistant解释的chat memory**。

## 回应如何评分

沿用保存profile的同一信息条件、同一完整后续策略下的`Q`和`Q_others`，主Q/S/reference不改。
评分轴由整个当前节点统一决定，同题8个采样共享该轴，不能按某个采样是否选错再切轴：

```
proposal：reward(a) = Q_own(a) - max Q_own
response，自身Q不平局：同上
response，ACCEPT/REJECT自身Q平局：
    reward(a) = Q_others_sum(a) - max Q_others_sum
```

这实现原本的游戏协议，不是固定加权own＋others；再多他人收益也不能补偿非平局的自身损失。
正确动作集合调用已有response-only helper，平局容差与保存profile一致为1e-9；旧v8的1e-7正确性阈值保留原身份，不回填旧日志。
无效/截断取当前轴最差合法reward，并保留独立-0.2协议惩罚；基础设施失败不当模型reward。
同题组内sample-std GRPO advantage函数未改，未增加新的GRPO算法、reward模型、解释奖励或归一化权重。

真实预览中的回应例子：

| 动作 | own Q | others sum Q | 新task reward | 新正确性 |
|---|---:|---:|---:|---|
| REJECT | -0.5 | 0.5 | -1 | 错 |
| ACCEPT | -0.5 | 1.5 | 0 | 对 |

只看own Q会把两者都判对。当前800中，相对保存的own-optimal集合，有42个回应入口因社会次级规则改变正确集合，含全部40个主用途social题。
其余规则仍保留：如果own确实较好，即使others很差也应优先own；两层都平局时两种回应都可；proposal不因others差异判错。

## 实际接口与接入边界

新增接口在[Decision v2](native800/decision_v2.py)、[request v2](native800/prompt_v2.py)、[共享scorer v1](native800/scoring.py)。

```python
from examples.strategic_slices.native800.decision_v2 import Decision

decision = Decision(indexed, row['node'], world, row, seed)
request_payload = decision.request
result = decision.score(generation_output)
```

`indexed`绑定原生全局node，`row`来自对应hash绑定的完整profile；realized world必须属于当前信息posterior的正支持。
接口会核对native actor/menu、自身偏好与累计答案，拒绝零CF旧fallback。旧own-only标量求值路径没有被拿来猜Q_others。
[DATA_BINDING](versions/native800_prompt_score_v2_20261105/DATA_BINDING.json)把新接口与800 manifest绑定，**没有覆盖原800导出的历史pending标记**。

own terminal D与回应社会次级regret/协议正确率需分开记录，本轮没有激活混合D排名。
40个social题不能只用own terminal D衡量是否选错。D完整runner、训练collector和新SP臂尚未迁移，不能把这个CPU适配器当成整套训练已就绪。
旧v8生产request、score、checkpoint和注册门禁保持原样且复核通过；后续新800必须显式使用此绑定，不会自动变成旧v8的新含义。

## 验证与版本留痕

- 全部800入口实际生成request；194个response状态均含同样完整共同信息。
- 5493个原生合法工具调用全部round-trip，逐动作正确性与原profile协议最优集合一致。
- 3044次同一可见信息的world对照请求完全相同（含每题原world自身800次，额外不同world2244次）；偏好事实集合、原状态不被修改均通过。
- 40个social入口用合法候选构造组，在原GRPO函数下均有正/负task advantage；这不是模型采样成功率或实际训练非零组发生率。
- 7项有针对性的CPU单测通过：own优先、proposal不favor、两层平局、数值容差、无效/截断、连续social regret及原GRPO兼容。
- [真实原生三决策记忆轨迹](../../new/native800_prompt_score_20261105_runs/cpu_v2/MEMORY_TRACE.json)：原两人1局，Alex调查Blair/Library，然后经过Blair PASS、Alex PASS、Blair OFFER再次回应；后两次本人request均仍有该答案。
  路径取自reference正支持，仅为CPU状态测试，不是模型rollout或新的采样分布。
- [CPU汇总](../../new/native800_prompt_score_20261105_runs/cpu_v2/SUMMARY.json)、[单测日志](../../new/native800_prompt_score_20261105_runs/cpu_v2/unit_tests.txt)。
- [完整v1合同](versions/native800_prompt_score_v1_20261105/DESIGN.md)、[v2文案修订](versions/native800_prompt_score_v2_20261105/DESIGN.md)。v1先完成同一800审计，v2只修单复数，score源文件未变；两轮请求和快照均保留。
- 实际pipeline snapshots：[v1](../../new/native800_prompt_score_20261105_runs/cpu_v1/pipeline_snapshot.json)、[v2](../../new/native800_prompt_score_20261105_runs/cpu_v2/pipeline_snapshot.json)。CPU workers2、数值线程1，日期按2026-11-05记录。
- [关闭验证](../../new/native800_prompt_score_20261105_runs/cpu_v2/closure_validation.json)、[关闭证据](versions/native800_prompt_score_v2_20261105/EVIDENCE.json)。

当前评分仍相对于同一保存reference，不宣称由游戏规则唯一确定所有混合策略；prompt不注入Oracle后验或reference数值。
未调用模型、未做GPU/新D/训练，不能把旧D当新题面测量。后续先审阅完整题面，再在此明确绑定上接通新D与正式训练接口。
