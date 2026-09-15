# Self-play 分类、随机候选库与完整局测试

本轮不生成B/P标签、不调用solver或模型、不启动训练。旧数据文件保持不变；新候选和诊断采样单独冻结。

## 旧数据的实际问题

| 数据 | 初始配置数 | 同构结构数 |
|---|---:|---:|
| 旧train | 60 | 4 |
| 原validation | 12 | 2 |
| 原test | 12 | 2 |

结构比较允许玩家、承诺、目标重命名；保留动作数量，忽略轮数、偏好与评分方式。三者没有结构重叠，但验证/测试各只有两个结构，无法据12个配置宣称覆盖12类策略。结构相同不自动等于答案泄漏。

旧训练库来自curriculum.py中人工指定的六个命名模板，其中有同构结构。隐藏偏好与回合顺序有随机性，结构本身不是每局重新随机生成。foundation同时绑定无avoid与linear，adaptation绑定含avoid与mixed，tradeoffs绑定含avoid与binary；因此阶段差异不能简单解释为难度递进。

旧库没有以solver收敛作为准入条件，这一点保留。新工作也不使用solver失败、模型成功率、收益正负或方差作为入选门槛。

## 新随机候选

36局来自原生generate_game，每局保存seed、完整GeneratorConfig和真实抽样偏好。24局双人、12局三人；binary/linear/mixed各12局；无avoid与含avoid两种公开偏好生成规则各18局。评分与偏好支持交叉，避免旧阶段的完全混淆。

新库有15种同构结构，36种不同的精确游戏/真实偏好配置。新train与原validation/test无结构交集，与旧train有1个结构重合。新库内部同构重复没有人为剔除，已记录，不能称为36种独立策略内核。

只因结构属于已有heldout才重新取预先确定的下一个seed，拒绝记录见generation_attempts.jsonl。原生生成器自身仅按合法性约束重采样：连通目标结构、每人至少want一个目标、没有所有人均neutral的目标等。没有教学前缀、人工承诺状态或收益筛选。

这仍是有界的小游戏配置分布：双人3–4个目标、每人2–3个承诺选项；三人3个目标、每人2个承诺选项。轮数与规模未完全交叉，三人本轮只有2/4轮。它用于高效诊断，不声称全面覆盖，不自动替换训练集或设定正式采样比例。

## 分类含义

每局可以有多个标签：共享承诺收益、同目标want/avoid冲突、共同正收益或不同正收益、第三方影响、连续公开证据机会、部分完成。标签表示结构支持这些现象，不能证明每条实际rollout都必须使用相应推理。

额外枚举承诺位模式，记录各玩家物理收益上下界及是否存在同时达到各自物理最大收益的状态。它没有考虑时间内战略可达性，不是策略标签，也未用于筛选。

D1–D3只是初步工作量提示，综合未知槽位数、初始合法动作数、目标依赖元数、共享承诺和机会数。4/5轮或更大分支/三方依赖列D3；短双人、少量未知和较少依赖列D1，其余D2。评分方式和偏好支持另列，不以旧level直接充当难度。是否平滑需要真实模型行为校准。

所有局的investigation_value、reasoning_quality和reward_variance仍为unmeasured。调查合法不表示值得调查，隐藏偏好改变不表示最优动作一定改变。

## 冻结抽样：16个初始局 × 4条独立完整轨迹 = 64局

从新train的玩家数×评分方式×偏好支持12个格子各取1局，具体索引在任何模型调用前按固定规则决定；从原validation按结构配置覆盖取4局。没有抽test，也不按已实现偏好、物理收益或模型输出挑样本。全部玩家用同一个初始Qwen3-4B-Instruct-2507模型；两端点仅作吞吐并行。

| ID | 划分 | 玩家 | 轮数 | 目标 | 评分 | 偏好支持 | 难度提示 |
|---|---|---:|---:|---:|---|---|---|
| random-v2-2p-binary-foundation-0 | train | 2 | 2 | 3 | binary | [0, 1] | D1 |
| random-v2-2p-binary-adaptation-1 | train | 2 | 3 | 4 | binary | [-1, 0, 1] | D2 |
| random-v2-2p-linear-foundation-1 | train | 2 | 3 | 4 | linear | [0, 1] | D2 |
| random-v2-2p-linear-adaptation-2 | train | 2 | 4 | 3 | linear | [-1, 0, 1] | D3 |
| random-v2-2p-mixed-foundation-2 | train | 2 | 4 | 3 | mixed | [0, 1] | D3 |
| random-v2-2p-mixed-adaptation-3 | train | 2 | 5 | 4 | mixed | [-1, 0, 1] | D3 |
| random-v2-3p-binary-foundation-0 | train | 3 | 2 | 3 | binary | [0, 1] | D3 |
| random-v2-3p-binary-adaptation-1 | train | 3 | 4 | 3 | binary | [-1, 0, 1] | D3 |
| random-v2-3p-linear-foundation-1 | train | 3 | 4 | 3 | linear | [0, 1] | D3 |
| random-v2-3p-linear-adaptation-0 | train | 3 | 2 | 3 | linear | [-1, 0, 1] | D3 |
| random-v2-3p-mixed-foundation-0 | train | 3 | 2 | 3 | mixed | [0, 1] | D3 |
| random-v2-3p-mixed-adaptation-1 | train | 3 | 4 | 3 | mixed | [-1, 0, 1] | D3 |
| validation-3p-0 | validation | 3 | 2 | 2 | binary | [-1, 0, 1] | D2 |
| validation-2p-6 | validation | 2 | 4 | 2 | linear | [0, 1] | D3 |
| validation-3p-2 | validation | 3 | 3 | 2 | mixed | [-1, 0, 1] | D2 |
| validation-2p-7 | validation | 2 | 5 | 2 | mixed | [-1, 0, 1] | D3 |

## 记录与分析

每局每次请求即时写入game_calls；games.jsonl包含所有完成、协议失败及基础设施失败的轨迹。失败不补成零终局收益。相同reset/相同玩家位置跨4次采样分别计算终局utility均值、标准差和范围；只有4次均完成才判定是否零outcome advantage。协议成本单独列出，不混成utility。

保留已有self-play协议：原生工具、1024输出、非法/截断每次-0.1协议成本、至多一次重试；网络/客户端错误不新增协议惩罚。它与B/P无重试的任务奖励不同，本轮未改变两者规则。

summary.json记录完成率、截断/非法调用、调查次数及逐玩家收益组。reasoning质量仍需读完整trace，重点检查信息归属、收益计算、时序、是否根据调查结果改变行动。不能把文本短或动作合法当作解释正确。此轮是分层开发诊断，不报告全分布准确率或正式胜率；固定对手与正式评估方案仍待训练实验统一。

## 运行方式

只检查包与原生回放，不加载模型：

```bash
python -m training.social_mixed.selfplay_probe --check
```

远程仓库根目录，沿用两张已分配GPU和已有环境，启动两个带CUDA graphs的vLLM端点：

```bash
/raid/chenjiahao/conda_envs/mas/bin/python -u examples/social_mixed/a100_evaluate.py \
  --selfplay-audit \
  --candidate /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --base /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --output "$SP_RUN"
```

运行前设置CUDA_VISIBLE_DEVICES为实际分配的两张卡，并把SP_RUN设为新的绝对路径。启动器保持每卡TP=1、max_num_seqs=16、显存比例0.65，检查通过后才加载模型。总并发最多32，每个端点16；未测当前服务器吞吐。

如已有常驻端点，可直接运行下式，避免再次加载；两端点served-model-name须分别是social-learner与social-base，且均为同一初始模型：

```bash
python -u -m training.social_mixed.selfplay_probe \
  --learner-url http://127.0.0.1:18091/v1 \
  --opponent-url http://127.0.0.1:18092/v1 \
  --output "$SP_RUN"
```

## 主要文件

- train_candidate.jsonl：36个随机完整局候选，未接入训练。
- old_classification.jsonl：旧84个train/validation/test初始配置的结构分类；test只做结构审核。
- candidate_classification.jsonl、probe_classification.jsonl：新候选与抽样的分类。
- probe_resets.jsonl：实际16个测试初始局；manifest.json记录hash、数量、来源与配置。
- generation_attempts.jsonl：每次候选seed的准入记录。

32次本地脚本完整局回放已通过，终局收益独立复算；没有模型调用。这不能证明模型rollout质量或GPU吞吐。
