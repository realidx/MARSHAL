# B/P探测与P后续价值审计（2026-09-22）

## Q0脚本

在训练机使用同一Q0权重，提交以下脚本（本地未提交）：

```bash
sbatch examples/social_mixed/sbatch_q0_bp_probe.sh /absolute/path/MARSHAL /absolute/path/Q0 /absolute/path/new-bp-probe-output
```

沿用已经运行过的O探测服务配置，单GPU启动服务并自动记录权重hash。输出目录必须不存在，仓库须已提交且干净。当前固定32个训练case产生B 256条、Pplus 224条，均为每题8次；4题P因现有训练资格过滤未发送。temperature=1、max_tokens=1024、concurrency=32。配方版本变化会改变日程，不能假设与早先O探测逐题一致；requests.jsonl和protocol.json记录本次确切身份。

已有服务可直接运行：

```bash
python -m training.social_mixed.reasoning_probe --views B Pplus --cases 32 --seed 42 --concurrency 32 --base-url http://HOST:PORT/v1 --model SERVED_NAME --checkpoint-hash HASH --output /absolute/path/fresh-probe-output
```

`summary.json`报告正/负/masked/非法/截断、可评分数、正负混合组、全错/全可评分回答正确组、零/单个可评分回答组、case/parent覆盖；`detailed_summary.json`按case及来源/终局与多步分层。masked、非法、截断不制造语义奖励对照。“全可评分回答正确”不代表8个回答全部有效且正确。请求已本地准备，尚无B/P真实生成结果。

## 后续价值审计结果

- 497题中174题所有动作立即终局。根据每个后继承诺状态、目标完成规则及逐世界偏好，独立重算payoff，全部与存储表一致。这里不需要未来伙伴策略；仍沿用已有定性LP和奖励容差审计。
- 174题为139 train、35 validation，均有原P训练资格。
- 323题存在非终局后继，其中175 train和71 validation具有原P训练资格；其余77题为29+4个无负例、30+14个隔离题。
- 109个非终局案例的源setup/history有INVESTIGATE事件。这只是历史信息依赖的线索，不证明这些题标签一定错误。
- 统一variant=0实际渲染后发现309对相同P请求；共同世界上的价值表差异为0，三态标签差异为0。这没有发现有限库内直接冲突，但不是对未出现历史的充分性证明。

## 具体依赖路径

`PrivateWindow.__init__`通过历史transcript中的调查对象构造各玩家information_groups；`PrivateWindow.response`使用背景世界权重与历史行动策略概率传播counterfactual reach，再在信息组内求条件期望；偏离路径使用初始prior及已获得私人信息。`reasoning_bank.replay/labels`从原历史节点取已求解tree的后续价值表。

P渲染保留剩余调查次数，却不提供全部历史调查对象、其他玩家的已知信息分组或源prior。现有LP只改变当前世界权重，不重新求解这些后续策略。因此世界集合全覆盖不能自动保证固定后续价值表是P可见信息的函数。

## 当前决定与边界

未修改数据、标签或p_train_eligible，未把175道多步train P自动删除，也未宣称已发现175道错题。完整C/D仍缺多步后续策略独立性认证。

真正补齐需要：为相同P可见状态构造不同的隐藏历史/信息分组条件，重新求解后续策略，再检查现有正负标签是否跨条件保持。单次清空历史重算或仅检查现有重复prompt都不足以完成全范围认证。若改为只用139道直接终局P，这是新的训练范围，必须明确为受限实验，不能悄悄替代原C/D。

复现：

```bash
python -m training.social_mixed.audit_p_continuation
python -m unittest training.social_mixed.test_reasoning_probe training.social_mixed.test_p_world_scope -q
```

逐题结果见p_continuation_audit.jsonl；同prompt对照见p_continuation_pairs.jsonl；统计见p_continuation_summary.json。审计已完成上述范围，但多步标签认证本身尚未完成。
