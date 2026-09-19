# SP 与 MARSHAL 实现对照

日期：2026-09-19。只读审查；没有修改训练代码或配置。

## 来源边界

对照本地 git 历史快照 `24d1e57`（2025-09-12），而不是把当前已经多次修改的 ROLL 环境管理器当作原版。该快照不是经独立认证的论文最终运行版本。配置入口为 `examples/multi_games/agentic_val_multi_games_selfplay.yaml`。当前 BENAC 路径为 `training/social_mixed/{core,pipeline,workers}.py`。

## 已确认差异

| 项目 | MARSHAL 历史快照 | 当前 BENAC SP |
|---|---|---|
| advantage | reinforce；按 tags 组织 reward 归一化，玩家分开处理；reward whitening、return、advantage normalization/whitening | 同 reset、同 seat 的 replicas 的终局 utility 减均值除标准差 |
| 失败 | env_manager 对格式错误、超长调用 get_losing_state；环境负责定义失败结果 | 重试一次仍失败后中止；所有玩家 utility=None；含该 replica 的组 outcome advantage 全零 |
| 辅助奖励 | format_reward 与 compute_length_penalty 加入 turn reward | invalid/truncation 调用单独负 advantage，合法调用不继承此惩罚 |
| PG 聚合 | 默认 seq-mean-token-sum；开启 dual clip | 每次调用先按实际输出长度平均，再按玩家轨迹调用数分配权重；普通 clip |
| KL | k3，配置系数 0.20 | k3，配置系数 0.01；同时乘轨迹权重 |
| LR | 1e-6，cosine_with_min_lr，warmup_steps=10 | 1e-6，constant_with_warmup，warmup=0 |
| rollout | batch_size=384，temperature=0.6 | 原生生成 temperature=1、无 top-p/top-k 截断；同 reset 多 replica |

384 不能直接解释成与当前同口径的游戏数或独立组数。KL 系数比值也不等于实际正则强度比值：loss 聚合不同。

## 代码证据

- 历史 `env_manager.py` 306–308：错误/超长进入 get_losing_state；749–750：格式与长度项加入 reward。
- 历史 YAML：45 rollout batch；53 reinforce；58 KL；72–79 scheduler；106 temperature；134–142 turn scores 与 normalization。
- 历史 `agentic_config.py` 185–186：默认 seq-mean-token-sum。
- 当前 `core.py` 的 Episode 接收结果与 units：失败中止、utility=None；assign_advantages：任一成员未完成则组任务信号全零。
- 当前 `workers.py::weighted_objective`：逐调用实际长度平均、轨迹权重、k3 KL。
- 当前 `functionals.py::normalize_unique_values_by_player` 显式处理 p0/p1，不能未经适配用于三人；历史中同名函数亦存在，需继续核对历史函数体后再移植。

## 对修改方向的结论

1. self-play 范式相同，估计器、失败语义与损失尺度并不相同。不能将当前实现称作已经复现 MARSHAL 训练。
2. 首要适配点是失败语义。MARSHAL 将失败交给游戏规则生成结果，BENAC 当前将其视作没有终局结果。不能把对抗游戏的失败方输/对方赢直接移植到 general-sum，也不能凭空补零。
3. 回到 MARSHAL 风格 return/baseline 可以消除同 reset replica 全员完整这一特有前提，但并不会自动解决 BENAC 未完成局的收益定义。必须先明确规则，不能选择性删除失败轨迹后宣布问题已解决。
4. KL、归一化、长度项必须作为完整目标核对，不能单独把 0.01 改成 0.20。原始 turn return 也不等于精确的逐动作因果信用分配。
5. cosine 有真实历史配置依据；调度器是否生效及如何对应预算仍需运行状态核对。
6. 暂不修改 SP 数据、奖励、温度或算法。本审查没有运行 GPU，也没有声称找到退化的唯一原因。

## 尚未完成的验证

- 历史各游戏 get_losing_state 的具体分数、长度奖励尺度与 return 打包细节。
- 历史 rollout batch 与 optimizer update 的实际粒度；scheduler 后端生效路径。
- BENAC SP 场景收益结构审查属于另一项任务，本文不以动作频率推定收益错误。
