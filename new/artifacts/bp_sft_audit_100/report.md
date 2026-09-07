# B/P SFT 数据生成审计（开发集）

**不是最终测试集；没有模型调用或训练结果。**

生成 100 个源游戏，595 个不同决策信息状态，1347 条去重 B/P 示例。

| 项目 | 数量 |
|---|---:|
| sources_with_planning | 100 |
| completed_trajectories | 200 |
| attempted_trajectories | 200 |
| empty_history_beliefs | 400 |
| all_actions_tied | 149 |
| interventions | 283 |
| sources_independently_checked | 84 |
| distinct_topologies | 95 |

## sample_kinds

```json
{
  "planning": 380,
  "semantic_belief": 967
}
```

## belief_supports

```json
{
  "avoid": 123,
  "neutral": 109,
  "neutral|avoid": 102,
  "want": 163,
  "want|neutral": 39,
  "want|neutral|avoid": 431
}
```

## planning_status

```json
{
  "exact": 380,
  "outside_remaining_turn_budget": 215
}
```

## planning_phases

```json
{
  "proposal": 199,
  "response": 181
}
```

## demonstrations

```json
{
  "ACCEPT": 89,
  "MENU": 62,
  "OFFER": 98,
  "PASS": 39,
  "REJECT": 92
}
```

## optimal_kind_sets

```json
{
  "ACCEPT": 71,
  "ACCEPT|REJECT": 55,
  "MENU|OFFER": 44,
  "MENU|OFFER|PASS": 131,
  "OFFER": 9,
  "OFFER|PASS": 14,
  "PASS": 1,
  "REJECT": 55
}
```

## failures

```json
{}
```

## input_characters

```json
{
  "semantic_belief": {
    "min": 2973,
    "median": 3182,
    "max": 3769
  },
  "planning": {
    "min": 3550,
    "median": 3944,
    "max": 10778
  }
}
```

## per_source_seconds

```json
{
  "median": 0.5715304159966763,
  "max": 1.6838881250005215,
  "sum": 66.7408456360572
}
```

## 生成与解释边界

- 固定 3 人、每人 2 commitments、8 goals、2 rounds、menu enabled；一个伙伴的一个未知偏好，其余行公开。
- 源游戏先固定；query 在保证三个类型均合法的候选中采样，不按模型错误或策略机会筛选。
- 每个源游戏两条采集轨迹：动作类别均衡和合法动作均匀；隐藏世界从声明的等权目录独立采样。
- 主轨迹中的 ego 决策全部保留 B；剩余原始 proposer turns <=3 时尝试精确 P 标签。
- 每游戏最多一个 proposal root 扩展 expert/普通 offer/menu 分支，不要求它有正信息收益；保留全部证据分支与原始权重。
- 四条空历史 B controls 是独立题目，不把观察后的标签伪装成初始信息；其中 singleton controls 没有延续轨迹。
- 完整 Q 与最优集合留在审计层。示范先在最优动作类别间采样，再在类别内部采样；展示顺序独立打乱。
- 输入使用白名单，不包含源 seed、实际隐藏世界、Q、标签证书；P 的正确显式判断是设计内 oracle assistance。
- 所有样本 development_audit_only，不划正式 train/test；同源及同构变体未来必须归入相同源家族。
- 未进行 tokenizer/Hermes 运行时验证时不得称为可直接开训。字符数不是 token 数。
- 独立搜索验证复用环境转换和伙伴 kernel，验证 ego 搜索及分支加权，不是独立的伙伴理性证明。
- 未按信息机会挑选；B/P 标签和动作分布仅描述本采集策略。复制和分支数不增加独立游戏数。

## 复现

```bash
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.sft_data_audit --output-dir new/artifacts/bp_sft_audit_100 --seed 50000 --games 100 --workers 4 --resume
```

## 实际 tokenizer 验证

固定 tokenizer revision：`cdbee75f17c01a7cc42f958dc650907174af0554`。全部 1347 条示例通过模板/token roundtrip、目标语义与 completion-only mask 边界检查。

| 任务 | 总 tokens 中位数 | P95 | 最大 | 目标 tokens 最大 |
|---|---:|---:|---:|---:|
| semantic_belief | 1273 | 1443 | 1516 | 33 |
| planning | 1519 | 4329 | 4436 | 24 |

超过总序列上限的样本数：{"2048":141,"4096":75,"8192":0}。没有进行截断。

这是本地模板和 token 检查；尚未通过远程 vLLM/Hermes 服务或 GPU trainer 的实际运行。

## 本批数据揭示的问题

- 149/380 个 P 局面所有动作同值，应与主要策略训练分开处理。
- 没有 CHOOSE_1/CHOOSE_2 的 ego 示范，不能声称已覆盖 menu responder 能力。
- MENU 示范已出现，但本批没有仅 MENU 最优的局面；同值动作覆盖不能证明获得了主动取证策略。
- 400 条 B 是空历史 controls，审计时有意保留；不能照此比例直接组成正式训练集。
- 100 个不同源种子有 95 个去标号公共超图；5 组同构游戏未来划分时应放在同一源家族。
- 生成主轨迹按采集策略保留，分支是定向增广；它们不能混作独立随机游戏估计。
