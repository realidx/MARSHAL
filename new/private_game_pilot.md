# 全员私有偏好游戏：第一轮可行性审计

2026-09-08。开发审计，不是 SFT 数据、正式测试集或模型实验；没有开始训练。

## 已完成的生成

每档 10 个游戏，seed 61000–61009，共 40 个配置实例、80 条完整轨迹。
不同配置复用 seed 只是复现约定，不表示跨配置的 goal 图或偏好严格配对。
不按模型失败、oracle 价值或是否出现 MENU 筛选源游戏。

| 配置：人数 / 每人 commitments / goals / rounds | 游戏数 | 初始提案动作数 |
|---|---:|---:|
| 3 / 2 / 8 / 2 | 10 | 73 |
| 4 / 2 / 8 / 2 | 10 | 109 |
| 4 / 2 / 12 / 4 | 10 | 109 |
| 4 / 3 / 16 / 6 | 10 | 361 |

原生 generator 的独立偏好抽样及 rejection 条件保留，未把玩家绑定成同一偏好；
但 rejection 条件本身引入条件依赖，不能把最终分布描述成无约束的独立先验。
每个人只接收自己的偏好、公开 state/history、合法动作和 pending offer。
全体真实偏好只进入本地审计记录及终局计分，不进入其他人的 decision view。
所有 offer、二选一 menu、不可逆 commitment、原生轮转和响应均保留。

轨迹使用两个**明确非 terminal-rational 的采样策略**：按动作种类均匀抽样、
现有 immediate_reference。它们检查合法覆盖和物理演化，不能当作 rational
partner 数据或 P teacher。80 条轨迹均从零承诺独立重放通过。

## 初步观察

“承诺变化次数”计数实际新增承诺的响应决策；“尾部无变化回合”按原生 proposer
turn 计数，round 含 N 个 turn。这些是物理演化指标，不是规划深度或信息价值。

| 配置 | 随机：平均承诺变化次数 | 随机：尾部无变化 turns | 短视：平均承诺变化次数 | 短视：尾部无变化 turns |
|---|---:|---:|---:|---:|
| 3 / 2 / 8 / 2 | 2.3 | 0.9 | 0.6 | 5.1 |
| 4 / 2 / 8 / 2 | 3.2 | 1.6 | 0.6 | 6.7 |
| 4 / 2 / 12 / 4 | 4.8 | 3.5 | 1.5 | 13.4 |
| 4 / 3 / 16 / 6 | 8.4 | 2.0 | 2.3 | 19.5 |

随机轨迹确实覆盖 CHOOSE_1/CHOOSE_2，但这是采样覆盖，不证明 menu 的策略价值。
较大场景允许更多承诺变化，短视策略却经常重复提议被拒的 offer 或 PASS。
因此需要同时改进采集策略，不能只增加 rounds。

同一个 commitment 对某玩家关联 WANT 和 AVOID goals 的结构性冲突机会也增多：
每局平均 player–commitment 对数依次为 9.8、13.7、21.5、27.6。
这个计数没有按规模归一化，也不证明相关 goals 可达或真的改变最优行动。

## Oracle 成本探测

没有枚举原生全私有先验。辅助探测为每人建立两条互补的完整 WANT/AVOID
偏好行，玩家之间独立，实际每个 goal 的偏好均未公开。
**这是每人仅两种、goal 间高度关联且没有 NEUTRAL 的受限先验，不能当作
正式训练先验，也不能据此声称已解决全员独立 goal 偏好的监督问题。**

在每档前两个 seed 上比较同一个辅助 catalogue 的两种信息条件：
只保留一名 target 的两种可能，其余人的行公开；以及所有人都保留两种可能。
后者保留 ego 的公共两行 catalogue，ego 仅在自身推理中条件化自己的私有行。
伙伴不会通过 ego 的公共 catalogue 偷看到其真实偏好。

各条件分别探测：

1. 初始行动者对 immediate_reference continuation 的 terminal best response；
2. ego 对实际 RationalPartner 的完整初始 P 搜索。

第一轮每次 2 秒、每个 Endgame search 2,000 nodes，共 32 次调用：

| 配置 | reference best response 完成数 | ego 完整 P 完成数 |
|---|---:|---:|
| 3 / 2 / 8 / 2 | 4 / 4 | 0 / 4 |
| 4 / 2 / 8 / 2 | 4 / 4 | 0 / 4 |
| 4 / 2 / 12 / 4 | 4 / 4 | 0 / 4 |
| 4 / 3 / 16 / 6 | 0 / 4 | 0 / 4 |

所有未完成调用均超出 wall-clock 预算；它们的 action_labels 为 null。
此外，对 seed 61000 的第一、第三、第四档 all-private ego P 搜索，分别放宽
到 10 秒和每个 search 20,000 nodes，三次仍超时。
这只说明在本机这些吞吐预算下未完成，不证明问题不可解，也不构成耗时下界估计。
不得把完成部分的最优行动或全知行动补成答案。

还发现当前伙伴推断语义的重要边界：RationalPartner 从其他 oracle 玩家的
历史行动推断偏好，但把 learner 行动作为干预，不据此排除 learner 类型。
这对旧 diagnose 的 learner 容错是有意设计；它不能被描述成完整的双向社会推断。
本轮未改这个 kernel，也未暗中假定 learner 最优。若希望伙伴从 learner 行动
学习，需要先声明具有行动似然的 learner 行为模型，并处理偏离该模型的历史。

## 输入长度与接口

使用已固定的 Qwen3-4B-Instruct-2507 tokenizer revision
`cdbee75f17c01a7cc42f958dc650907174af0554`，seed 61000、空历史：

| 配置 | 完整动作列表的紧凑 JSON 本身 | 现有参数化 native tools 的完整初始 prompt |
|---|---:|---:|
| 3 / 2 / 8 / 2 | 3,446 tokens | 2,098 tokens |
| 4 / 2 / 8 / 2 | 5,166 tokens | 2,159 tokens |
| 4 / 2 / 12 / 4 | 5,166 tokens | 2,502 tokens |
| 4 / 3 / 16 / 6 | 20,886 tokens | 2,898 tokens |

左列只是 `[action.to_dict() ...]` 的序列化；右列是
`build_player_observation(..., mode='private')` 配合 VLLMPlayerPolicy
现有 proposer system/user/tools，经官方 chat template 渲染的输入。
两者是体积诊断，不是控制了全部信息的准确率对照。
右列不含额外 B judgment、生成 completion 或后续 history，不能据此冻结 4K context。
没有测试远程 vLLM/Hermes 或 GPU trainer。

建议下一版 P 示范使用已有原生 OFFER/MENU 参数接口，内部评估仍可枚举动作；
保留 action-index 接口作诊断对照。格式转换可以精确校验动作等价，但需要单独
验证 native 参数生成的合法性；不能默默修改原正式 diagnose 的接口与评分。

## 下一轮应先解决的事项

- 采用 4 / 2 / 12 / 4 作为主体候选、4 / 3 / 16 / 6 作为复杂候选，仍不冻结正式分布。
- 先提高采集策略对有效交易、延迟收益和主动取证的覆盖，分别保留自然抽样与定向样本。
- 明确完整私有信息下的伙伴行为模型，再决定 B 支持集如何可靠计算；真实偏好不能直接作 B 答案。
- 单 goal 的可能集合可能长期都是三种，而历史已经改变相对可信程度。保留语义集合接口时，
  需要报告这种表达限制，P 继续保留完整 history；不能把边际集合冒充完整联合 belief。
- 从完整合法轨迹采集后期 P 候选，检查精确监督覆盖率；需要证明历史在所声明策略下可能。
  不能把随机生成的前缀不加说明地当作 rational partner 历史，也不能仅把 turn_index 改成残局。
- 用严格价值差、信息分支和后续决策机会认证策略样本；当前结构指标和随机 CHOOSE 均不够。
- 超时率、零信息样本、同值动作比例和采样覆盖都进入筛选报告；最终评测按源游戏家族隔离。

## 复现与数据管理

代码：`third_party/negotiation_benchmark/src/benac_p/private_game_pilot.py`。

```bash
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.private_game_pilot \
  --output-dir new/local_data/private_game_pilot_v1 \
  --games-per-cell 10 --probe-games-per-cell 2 --probe-seconds 2 --max-nodes 2000
```

默认 seed 61000；已有输出目录不会被覆盖。manifest 固定配置、策略范围和相关源代码哈希。
较大预算复测位于 `new/local_data/private_game_pilot_followup_v1/probes.json`，
对应 `oracle_probe(spec, 61000, 'all_private', 'ego_root_planning', 10, 20000)`。
输入体积记录位于 `new/local_data/private_interface_audit_v1.json`。

本轮 7 项测试加已有 endgame / SFT audit 测试共 24 项通过，覆盖私有信息隔离、
四档完整轨迹重放与复现、辅助先验定义、预算失败不输出标签。
新数据 42 个文件校验和通过；原 100 游戏审计的 122 个已校验文件内容保持不变。

`.gitignore` 忽略 `new/local_data/`、`new/artifacts/` 下生成的 JSON/JSONL 和旧审计
source_snapshot。131 个已跟踪的生成记录及快照已从索引移除，本地文件保留。
代码、测试和 Markdown 报告继续版本管理。没有提交、推送或改写历史；
历史 commit 中已有数据不会被 `git rm --cached` 清除。
