# 丰富私有游戏的 MCTS B/P 数据审计

日期：2026-09-08。已实际生成并核验数据；没有调用 LLM、进行 SFT/RL 或运行迁移测试。

## 结论

在明确的有限私有先验和固定 MCTS 策略下，B 标签可以生成并完整核验；
本次 4 局生成 298 条 B 记录（280 个不同的输入/答案对）和 16 条 P 搜索候选。
生成完整轨迹连同 B 筛选约 16.4 秒，加入 P 复测及实际伙伴续局共 157.8 秒；
额外预算敏感性检查约 39.3 秒，全部在本机 CPU 上运行。

这解决了本候选设置下“能否实际生成”的问题，但不能把全部记录直接称为成熟训练集：

- B 对原固定策略的支持集精确，但较快识别出整条偏好行，而且对伙伴搜索配置敏感。
- P 的 16 个候选中，只有 2 个通过较严格的初筛；初筛使用独立的轻量模拟续局，
  不等于实际 MCTS 伙伴下的最优性证明。
- 增加 P 搜索预算在实际续局中找到了更好的行动：两个后期局面收益分别从 1 到 3、
  从 2 到 5。这是同局面行动比较，不是模型训练效果或普遍预算单调性。
- 6/16 个 P 位置在忽略历史 belief 后换了行动，但没有据此证明 B→P 的正向收益作用。

## 固定的候选设置

| 人数 / 每人 commitment 位 / goals / rounds | seeds | 游戏数 |
|---|---|---:|
| 4 / 2 / 12 / 4 | 62000、62001 | 2 |
| 4 / 3 / 16 / 6 | 62000、62001 | 2 |

沿用原生 generator 的 goal 图与轮转，保留 ALL_OF、独立玩家利益、不可逆 commitment、
所有合法 OFFER、MENU、PASS、ACCEPT、REJECT、CHOOSE_1、CHOOSE_2。
每次最多新增一个自身 commitment 和一个伙伴 commitment；没有削减原生行动集合。
四条从零承诺开始的完整轨迹共 147 个显式决策，均通过原生 GameState 逐步重放。
下文所有 turn 数字均指从 0 开始的原生 `turn_index`。

**先验是本次有意限制的部分。** 每名玩家公开 6 条完整候选偏好行，再私下独立均匀
抽取一条。每个 goal 初始都有 want/neutral/avoid 三种可能。候选行来自两组随机
ternary cyclic triplets，行内 goal 偏好相关；并非逐 goal 独立的完整原生先验，
也没有沿用原生偏好抽样的全部 rejection 条件。原生 goal 图不变。
给定 learner 自己的行，初始联合隐藏配置为 6³=216。
因此这里的成本不能直接外推到原生 3^(3G) 隐藏空间。

实现位于 `third_party/negotiation_benchmark/src/benac_p/mcts_oracle.py`：

- 默认每次 UCT 1024 simulations；最多在 3 个自身决策、12 个原生决策阶段内展开搜索树。
- 树外用轻量策略继续模拟到真实终局，不把截断处已实现收益当终局奖励。
- 模拟策略：75% 最大化即时预期改善的参考策略，25% 按原生行动类别探索。
  参考 proposer 的贪心部分只选 ordinary offer，随机部分和 UCT 都覆盖菜单。
- 每个模拟玩家只根据自己的私有行和公开候选集合行动；不读取其他人的实现偏好。
  root 后续决策按观察到的行动历史共享搜索统计，不按隐藏世界分别全知最优化。
- 实际伙伴每次重新执行 UCT，并从公开 oracle 行动更新候选集合；learner 行动作为干预。
  实际伙伴策略与树内轻量 continuation 不同，必须另外验证这种模型偏差。
- 搜索随机流由公开状态、角色、公开候选集合和固定 salt 确定，不含真实隐藏配置、
  实例私有 seed 或自己的类型编号。因此候选策略在自身信息条件下可复现。
- 它是有明确 continuation 假设的近似规划策略，不是精确最优 oracle 或 Nash solver。

P 提供语义边际集合和剩余联合偏好行；只给边际可能集合不能保留本先验的行内相关性。
模型答案仍为语义集合或原生行动参数，没有概率、Q 或 plan variable。
导出的是结构化审计样本，尚未制作 chat-template/tool-schema 格式的正式 SFT 语料。

## B 标签生成与核验

固定公开前缀后，一个 oracle 玩家的输出是“自己的候选行 + 公开状态/候选集合”的
确定函数。因此观察它的行动只需逐行检查它自己的剩余候选，无须反向求解整棵博弈树。
各玩家原始先验独立；逐步观测的似然按行动者自己的行因子化，支持集始终保持 Cartesian。
本实现利用这个性质做精确筛选。它是此候选策略的结构性质，不是所有私有博弈的普遍性质。

审计另维护全部 216 个联合配置，逐步筛选后与因子化结果比较；所有前缀通过。
真实隐藏配置始终保留。原生引擎独立验证全部实际状态转移和最终收益。
测试还穷举抽样可达状态的全部原生动作，核对 compact adapter 与原引擎的动作/转移等价。

| B 指标 | 结果 |
|---|---:|
| 实际 oracle 观测/标签更新次数 | 119 |
| 缩小完整偏好行集合的观测次数 | 22 |
| B 筛选额外总耗时（利用已有动作计算缓存） | 9.29 秒 |
| 最慢一次 B 筛选 | 1.44 秒 |
| 导出 B 记录 | 298 |
| 不同输入/答案对 | 280 |
| 集合大小 3 / 2 / 1 的记录数 | 42 / 28 / 228 |
| 导出更新对：集合缩小 / 集合保持 | 42 / 107 |

每次观测最多选 2 个缩小的 goal、1 个保持的 goal，导出观测前后各一条。
这些是有意覆盖更新/不更新的采样计数，不是自然分布中的信息性比例。
部分相邻观测造成重复输入，298 不是 298 个独立训练样本。

具体例子：`n4_k2_g12_r4_s62000/b1/g0`，learner 为 P1。
P2 接受首个 offer 后，G0 的集合由 `{want, neutral, avoid}` 变为 `{want, avoid}`。
P2 的完整候选行由 `[0,1,2,3,4,5]` 变为 `[0,1,3,4]`；被排除的两行在 G0 上均为 neutral。
这不是“接受意味着 want”，而是根据全部 goal 偏好候选和实际 UCT 行为作出的筛选。
具体 offer、完整前缀、候选行和答案均在本地样本中。

### B 对伙伴策略的敏感性

每局取最早 3 个缩小候选集合的观测，共 12 个。保持前缀和已观察行动不变，
分别用加倍预算或更换 salt 的行动模型重新检查当前行动的似然支持。
这是局部行为模型错配测试，没有将整个旧历史宣称为新策略生成的轨迹。

| 当前行动模型 | 与原支持集相同 | 保留真实类型 | 得到空支持集 |
|---|---:|---:|---:|
| 2048 simulations，原 salt | 5/12 | 10/12 | 1/12 |
| 1024 simulations，salt=17 | 3/12 | 7/12 | 5/12 |

原固定模型的标签没有因此变错，但它们不具备对这些策略变化的自动稳健性。
训练可能学到固定有限预算搜索的行为特征，需要在新伙伴下另外检验。
此外，所有三个非 learner 玩家的完整行在 turn index 3–5 时已经被识别，
也就是第 4–6 个 proposer turn 结束前；游戏仍有 16 或 24 个 proposer turns。
这说明本先验过快暴露整条偏好，后续多数 P 位置实际已不再有伙伴类型不确定性。

## P 候选质量

每局从 learner 实际到达的非平凡决策位置按轨迹位置等距选 4 个，共 16 个：
13 个 proposal、3 个 response。所有根动作均至少访问一次。
比较原 1024 次、2048 次以及 1024 次 salt=17 搜索，并使用独立随机流进行
256 次配对轻量续局评估。初筛要求三个搜索返回同一原生动作，且相对即时参考
行动的配对收益差近似 95% 下界大于零。该筛选是探索性筛选，没有多重比较校正，
同一动作要求也可能拒绝价值相近的不同好动作。

| 指标 | 结果 |
|---|---:|
| 原预算与双倍预算动作一致 | 11/16 |
| 原 salt 与新 salt 动作一致 | 4/16 |
| 忽略公开证据、恢复初始候选集合后动作变化 | 6/16 |
| 通过上述初筛 | 2/16 |

“恢复初始集合”是错误 belief 的消融，不能把与原历史矛盾的输入当作正确训练示范；
它也改变了搜索中其他模拟玩家使用的公开 belief，不是独立的纯 B 因果效应估计。

初筛通过项：

- `n4_k3_g16_r6_s62000/p1`：第 7 turn 的 response，CHOOSE_2；
  相对即时参考动作的轻量续局收益差 0.168，近似区间 [0.105, 0.231]。
- `n4_k3_g16_r6_s62000/p3`：第 20 turn 的 proposal，向 P3 OFFER；
  自身最终目标向量 `[1,1,1]`，伙伴 `[0,1,1]`；收益差 0.129，近似区间 [0.070, 0.188]。

其他 14 条保留为待审计候选，未标为 certified optimal 或自动选入 SFT。

### 实际 MCTS 伙伴续局，而非树内参考策略

主审计每局在初始 P 位置取 8 个配对隐藏配置，对 teacher / 即时参考动作分别续局，
后续所有玩家使用原 1024 次 UCT 并实际更新 belief。
四局平均收益差为 -0.625、-0.25、-0.125、0；样本小，不能宣称初始 teacher 优于参考策略。
该检查耗时 136.6 秒，占主审计 157.8 秒的大部分。

额外每局按时间顺序取一个后期 proposal，在 1024/4096/16384 次、两个 salt 下复测。
再固定首行动，让实际 1024 次 UCT 伙伴继续游戏。此时伙伴类型已全部识别，
8 次重复实际是同一确定配置的复现，不是 8 个独立测试局。

| 源游戏 / turn | 原 1024 teacher | 16384 teacher | 即时参考 | 忽略历史 belief 的行动 |
|---|---:|---:|---:|---:|
| 4/2/12/4，62000 / 7 | -1 | -1 | -1 | -1 |
| 4/2/12/4，62001 / 7 | 1 | 3 | 3 | 3 |
| 4/3/16/6，62000 / 12 | 2 | 2 | 2 | 2 |
| 4/3/16/6，62001 / 5 | 2 | 5 | 4 | 5 |

这些均为该局 learner 自己的最终收益，不是跨玩家排名。
最后一个例子中，原 teacher 提供给 P1 的 MENU，高预算 teacher 改为向 P3 的 MENU。
同初始状态和伙伴下，首行动差异带来了 3 分的实际后续收益差；没有借用容易局面的高分。
但 16384 次的两个 salt 仍只有 2/4 个位置动作相同，不能宣称加预算已解决教师稳定性。
原先验消融在这四个位置也没有表现得更差，不能据此宣称 belief 利用已得到收益验证。

## 数据与复现

代码：

- `third_party/negotiation_benchmark/src/benac_p/mcts_oracle.py`
- `third_party/negotiation_benchmark/src/benac_p/mcts_bp_audit.py`
- `third_party/negotiation_benchmark/src/benac_p/mcts_bp_followup.py`
- `third_party/negotiation_benchmark/tests/test_benac_p_mcts_oracle.py`

```bash
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.mcts_bp_audit \
  --output-dir new/local_data/mcts_bp_audit_v1 \
  --games-per-cell 2 --simulations 1024 --eval-samples 256 --actual-samples 8

PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.mcts_bp_followup \
  --source-dir new/local_data/mcts_bp_audit_v1 \
  --output-dir new/local_data/mcts_bp_followup_v1 \
  --actual-samples 8 --eval-samples 1024

PYTHONPATH=third_party/negotiation_benchmark/src python -m pytest -q \
  third_party/negotiation_benchmark/tests/test_benac_p_mcts_oracle.py \
  third_party/negotiation_benchmark/tests/test_benac_p_private_game_pilot.py \
  third_party/negotiation_benchmark/tests/test_benac_p_endgame.py \
  third_party/negotiation_benchmark/tests/test_benac_p_sft_data_audit.py
```

复跑须使用新的输出目录，程序不覆盖已有运行。审计使用本机 `python` 的 Python 3.12 /
NumPy 1.26.4；没有安装新的依赖。7 项新测试和 24 项相关回归测试通过。
manifest 保存配置和源码哈希；checksums 保存输出校验和。
游戏、真实偏好、原始轨迹、B 样本、P 候选、内部 Q 统计/收益均仅在
`new/local_data/` 下，已受 `.gitignore` 排除，没有加入 Git。

本轮没有改动原正式 Diagnose kernel、评分或接口，也没有修改已有论文工作。
这些是同一批开发游戏上的审计与追查，不是 train/test 划分后的泛化结果。

## 后续应据此决定的事

先保留这批数据作为可检查的机制样本，不直接扩成大规模 SFT。
后续最有价值的改动是增加私有候选的多样性、避免一次行动过早识别整条偏好，
以及明确训练 B 时需要适应固定伙伴还是伙伴策略池。
P 教师应同时记录搜索预算稳定性和实际伙伴续局价值；不能只依赖轻量模拟器的排名。
收益或动作变化与 B/P 改善仍需由独立 Diagnose 和训练消融区分。
