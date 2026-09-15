# 两张 A100 上独立的 B/P 与 self-play 短训练计划

状态：参数提案与实施顺序；尚未改动正式配置、合并数据或启动训练。用户运行服务器命令，助手准备代码、命令并分析下载结果。

## 实验边界

两个实验均从已测试的 `Qwen3-4B-Instruct-2507` 相同初始权重启动，各自独立 optimizer、reference、采样随机数流、日志和 checkpoint。Self-play 首轮不加载 B/P checkpoint。这样分别检验细粒度监督和终局收益信号是否能带来改善；将来可再做 B/P→self-play 的组合实验。

两次实验顺序执行，每次使用 GPU 6/7 两张 A100-40G。先 B/P，后 self-play。不能把不同任务下的同样 30 updates 当作相同计算预算；同时记录生成 token、训练 token、完整游戏数、玩家轨迹数、真实 Adam 更新数和墙钟时间。

## 已有实现与缺口

- B/P：`examples/social_bp/grpo.yaml` 已有原生工具 reward worker、课程、验证与 checkpoint 路径，但仍为六卡布局：4 actor + 1 rollout + 1 reference，100 steps、eager、每训练卡 accumulation 32。不能仅改 GPU 数后直接启动。
- 依赖检查 `training/b_sft/check_bp_training_env.py` 仍锁 transformers 4.51.3；本次服务器 rollout 环境使用 4.57.3。需要检查实际训练 import/API 兼容性，不能为了通过检查简单删掉版本限制，也不应无依据降级已验证的 rollout 环境。
- ROLL 已有训练状态 offload/reload、vLLM sleep/load 与权重同步相关接口，可优先复用；双卡切换、CUDA graph 恢复、同步后采样是否使用最新权重尚未验证。
- Self-play：`examples/outcome_selfplay_nus/rollout.py` 的 HTTP 记录仍为 `gradient_ready=false`。完整游戏环境已可用，但没有可靠的原始生成 token IDs、behavior log-probs、玩家轨迹 loss mask 与训练 batch 对接。不能将现有 HTTP JSON 直接当作优化器输入。

## 共用双卡执行方案

采用同步的“采样→打分/reference→更新→权重同步”，首轮不混用多个 policy 版本。

1. 采样阶段：每卡一个 TP=1 vLLM 副本，CUDA graphs，每卡最多 16 个在途请求。B/P 按单次回答排队；self-play 按完整游戏并发推进，局内保持时序。
2. 更新阶段：两卡共同承担全参数训练，BF16、gradient checkpointing、microbatch 先从每卡 1 开始。优先检验现有 ZeRO-2 路径能否在实际峰值下运行，显存不足再评估 ZeRO-3；不能预先承诺 4B 全参数状态、激活、推理 KV 和 reference 同时驻留两张 40G 卡。
3. 阶段切换时释放/卸载非当前阶段状态，不常驻第三份 reference 占一张卡；reference 计算排成独立阶段。状态移到主机内存与使用 CPU 执行 Adam 是两回事，本轮不默认引入 CPU optimizer。
4. 固定初始 reference。验证显存水位、权重同步正确性、graph 恢复及每次切换耗时。B/P 的 reference 输出可在精确的 prompt+生成 token+模型版本键下缓存；新输出不能复用旧输出的 log-probs。
5. 性能报告分别计采样、reference/old-log-prob、前后向、同步和验证耗时。目标是每小时有效更新与可学习样本，不把持续 100% GPU utilization 作为必要条件。

## 实验 A：B/P

首轮 30 updates，step 0/10/20/30 验证；每轮 16 题（8 B + 8 P），每题独立 8 次，共 128 回答。PPO epoch 1，目标每轮恰好一次 Adam 更新；若两卡 DP=2、microbatch=1，候选 gradient accumulation 为 64，必须以实际 pipeline 的分片/批次展开和 optimizer step 计数核对。

数据方案：先冻结下一版训练包，保留原 train/validation/test 边界。B 不再给直接读取调查真值题训练配额；原 B/P、非 test 短桥梁和新 L0 合并后按语义去重、结构 family 核对 split。

候选每轮 8 个 B 来源配额：新 L0 2 个（轮换三道 train 题，最多占 B 的 25%）、其他短行为桥梁 3 个、原行为 B 3 个。按 10 步窗口兑现形成/更新/维持、多元素 favored 等能力覆盖，来源池重叠时按语义 ID 去重。旧共享结构 L0 保留为后续桥梁，不再承担最低入口角色。三道新 L0 来自一个家族，重复曝光不算增加独立场景。

P 每轮四池各 2：完整信息决策、不完整 belief 决策、结果使用、信息获取。信息获取尽量保持调查正/负配对。后续决策对照尚未补齐的能力如实标记，不宣称覆盖完备。

首 30 步固定曝光方案，不因一次验证或某组全错临时过滤困难题，不自动按旧 L0–L4 标签进阶。全零组保留记录、不给任务优势；记录 B/P 各自产生非零任务优势的数量，防止名义 1:1 实际由 P 主导。若整个更新批都没有任务优势，明确记录并诊断，不把仅 KL 驱动的参数变化报告为任务学习。

候选超参沿用旧 B/P 提案：LR 1e-6、warmup 5 updates、clip 0.2、KL coefficient 0.01、entropy bonus 0、PPO epoch 1。保持 temperature 0.8、top_p 1、top_k disabled、输出 1024、正确 1/其余模型失败 0、无作答 retry/length penalty。以上不是最优参数声明。

验证候选：旧固定 64 个 validation checkpoint 各 4 次，另加新 L0 的 3 个 validation 题各 8 次，共 280 次/评估。旧直接真值题可作单独监控，不纳入行为 B 主指标。训练 3840 回答，四次验证 1120 回答，另计端到端检查；test 暂不运行。

判断重点：B 接受/拒绝更新与维持分别改善、错误全集和错误排除是否减少、favored 是否正确；P 调查正反例与后续动作是否同时改善；截断与混合奖励组变化。每个 checkpoint 对少量固定关键题做解释核对，接受题不能仅因标签正确就认定时序推理已修复。

## 实验 B：Outcome self-play

从同一个 base 重新开始。候选 30 updates；每轮 **8 个真实训练初始局 × 4 条完整轨迹 = 32 局**，便于使用最多 32 个并发游戏槽。每个初始局组固定实际隐藏世界、公开状态和玩家位置，仅改变采样随机数。不能仅共享模板 ID 就混为同一 advantage 组。

从现有 60 个 train 初始配置均衡轮换，按窗口保持人数、轮数和 binary/linear/mixed 等分布。不用 B 教学残局替换，不按 solver 收敛、base 成功与否或当前组收益方差筛掉完整局。配置数不等于独立策略场景数。

首轮对手/更新选择：一批完整游戏中所有位置均使用固定的当前 policy π_t；整批完成后，用每位玩家自己的回报更新同一个共享模型，之后同步 π_(t+1)。不引入历史对手池或局中更新。固定 base 对手用于评估，避免只与共同变化的自己比较。

Reward 沿用已测试版本：每个玩家自身终局 utility，加该玩家已记录的协议扣分（每次无效调用或截断 -0.1），最多一次协议 retry；网络/服务失败不扣分，失败或不完整组不送入优化器。utility、protocol、combined 分开记录。

Advantage 按“同一实际初始局 × 玩家位置”在四条轨迹间比较，不混玩家、不拿他人的回报赋给自己。首轮使用组内均值/标准差的 GRPO 估计，并处理全同回报的零优势组。特别记录 utility 有差异、仅协议分有差异、完全恒定三类：标准化会使仅 -0.1 差异的组也产生显著 advantage，不能把这些信号误报为策略进步。

梯度对齐：同一玩家轨迹的回报信号只作用于该玩家实际生成的 assistant token。解释与工具参数都属于输出；系统文本、用户状态、环境反馈、历史重放和他人回答不计算本玩家 loss。失败输出和重试保留为各自真实调用，不悄悄丢掉被扣分的生成。长游戏不能仅因有更多决策获得更高权重；先在玩家轨迹内归一化，再按玩家轨迹平均。精确 batch 大小取决于实际玩家轨迹数，不直接照搬 B/P accumulation 64。

原始 token IDs、采样分布对应的 behavior log-probs、old-policy 重算一致性、loss mask、policy version 和终局回报归属全部需要端到端验证。沿用每次输出 1024、temperature 0.7、v4 prompt；上下文容量按完整局实际输入检查，不能静默截断历史。LR/clip/KL 可先以 B/P 的 1e-6/0.2/0.01 为候选，但需核对轨迹 loss 的归一化尺度。

评估候选：固定抽 6 个 validation 初始局（4 个双人、2 个三人，覆盖计分方式与轮数），轮换 learner 位置，其余玩家使用冻结 base，每位置 4 次，共 56 完整局/评估；step 0/10/20/30 共 224 局。训练最多 960 局。正式冻结名单时如无法满足该组成，明确调整数量及依据。

评估记录自身原始 utility、相对同条件 base 的变化、按位置/计分方式分层结果、协议失败/截断、调查次数和对照决策。general-sum 不只报胜率或所有人收益之和。末轮 checkpoint 可增加同模型对局作为诊断，不能替代固定对手评估。

## 实施与放行顺序

1. 本地冻结 B/P 新混合数据与小验证，准备独立 run manifest、双卡配置和环境核验脚本。
2. 用户在远程跑小型训练预检：至少两次 rollout→update→同步循环，验证实际 Adam step、参数确实变化、采样读取新权重、显存/耗时；保存并恢复 checkpoint，核对 optimizer/scheduler/RNG 状态。预检结果不作为正式 30 步实验的起点。
3. B/P 从干净 base 启动 30 步，用户下载 step 10/20/30 结果分析；助手同时在本地实现 self-play 的训练数据接口，不操作服务器。
4. Self-play 完成独立的完整局→按玩家分组→loss→update→权重同步和恢复检查，再从干净 base 启动自己的 30 步。
5. 两次短实验结束后，分别决定是否扩大。B/P 若只改善拒绝捷径或 P、self-play 若只降低协议扣分，都不足以证明完整目标已改善。暂不做大规模扫参，也不凭未实测的 GPU 时间预算承诺完成时长。

两次实验先各自做任务内评估；若要比较训练方法的迁移效果，可对各自 step 30 checkpoint 交叉运行同一套 B/P 小验证与固定对手完整局评估，另记评估成本。只有一条训练种子的短实验不支持统计显著优劣结论。
