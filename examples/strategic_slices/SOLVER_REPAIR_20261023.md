# Solver修复与整批验证，2026-10-23

**已批准的有限窗口：100/100 有可用认证参考策略。完整终局：99/100 认证，缺失 index 25。**
两者是独立口径，不能把窗口结果当成补齐了终局Oracle。正式100父游戏、游戏规则、独立先验和生产active v8没有改变；没有改prompt、训练算法、奖励或GRPO参数，也没有测新Q/S/D或启动训练。

## 1. 实际阻塞是什么

远端先前各版本合计85/100，剩余15局的最后一轮重试构树最长约3秒，主要失败在联合策略搜索和认证。
因此这些失败不能统一解释成“树大，计算机穷举不动”。树展开、寻找策略、确认策略满足规范，是三个不同环节。

本轮确认并修复了三处可操作的问题：

1. **无关末端决策占用了大量求解变量。** 新的逆向消去只处理在所有兼容world中都能确定的行动，保留公共历史、私有信息集和原生行动的完整树用于最终审核。计算时把已解决子树作为收益向量复用。
2. **每次best response都重置剩余平局，可能破坏已稳定的选择。** 新候选保留当前分布中仍然最优的部分；只有全部失效时才重新分配。旧认证本来就允许在剩余最优动作间非均匀混合，本轮没有改终局效用或放宽认证。
3. **局部修复用了另一套后续走法的收益。** 完整BR可能在后面的自身收益平局处换选择。拿它当前节点的动作来修补当前策略的局部社会平局，可能反复修不对。现在按候选策略的实际continuation计算局部收益，按深度修补，再独立认证。

还有一个必须保留的自由度：**proposal中自己收益相同、别人收益不同的选择，不能随意消去。** 它会影响更早的ACCEPT/REJECT社会平局。最终安全缩减保留这种选择；三人响应的own/others-sum都平局但各玩家收益不同的选择也保留。早期实验中更激进的缩减仅是候选生成器，原始记录保留，不能称为保持全部平局自由度的最终版本。

主要实现：[逆向缩减](../../new/sparse_solver_v1_20261023/reduction.py)、[复用计算与惯性BR](../../new/sparse_solver_v1_20261023/engine.py)、[实际continuation修复及终局runner](../../new/sparse_solver_v1_20261023/run.py)。生产solver没有被静默替换。

## 2. 完整终局结果

本轮用同一份代码重新求解全部100局，得到：

| 项目 | 结果 |
|---|---|
| 两人局 | 66/67认证 |
| 三人局 | 33/33认证 |
| 合计 | 99/100，缺失25 |
| 成功局最大root私有信息条件化偏差 | 2.220446049250313e-16 |
| 成功局最大局部支持动作偏差 | 4.440892098500626e-16 |
| 成功局耗时中位数 | 约3.75秒，含构树/搜索/审核等 |
| 保存后重新加载独立复核 | 99/99通过，无重新搜索或修复 |

[整批结果](../../new/sparse_solver_v1_20261023/full100_v1/results.json)、[实际运行快照](../../new/sparse_solver_v1_20261023/full100_v1/pipeline_snapshot.json)、[独立重新加载完成记录](../../new/sparse_solver_v1_20261023/full100_v1_reload/COMPLETE.json)。

99个成功局全部在惯性BR前端得到稳定候选，不需要后面的数值联合求解。这不能推出任意一般和游戏都存在纯固定点，也不是和远端旧环境做过控制变量的速度对照。上述时间是本地CPU实际wall time；不是GPU或训练效率。

“终局认证”指完整原生树所有叶子都到native terminal，并通过原有数值own-utility epsilon-Nash、局部支持、私有信息和响应社会平局检查。epsilon仍为1e-8、平局容差仍为1e-9；不是符号精确解、唯一均衡或正式sequential-equilibrium证明。通用旧证书的`full_game_equilibrium_verified=False`原样保留，不靠改一个flag扩大声明。

## 3. 同一有限窗口的100个参考策略

沿用用户已经批准、v2已记录的窗口：从入口锚定，覆盖1 RR及当前玩家下一次proposal和完整回应；原生终局更早到达则停止。所有玩家在该共同截止点比较已生效承诺收益，不加尾部rollout或价值网络。

对原100局统一使用该窗口：首轮惯性BR 98局认证；60经另一个固定玩家顺序认证，46经联合数值求解及完整审核认证。没有只给失败题缩短窗口，也没有换父游戏。

- [首轮整批结果](../../new/sparse_solver_v1_20261023/window100_v1/results.json)
- [46/60补充候选及完整认证](../../new/sparse_solver_v1_20261023/window_retry_v1/results.json)
- [统一100-reference索引](../../new/sparse_solver_v1_20261023/bounded_references100_v1/REFERENCE_INDEX.json)
- [整批保存后独立复核](../../new/sparse_solver_v1_20261023/bounded_references100_v1/COMPLETE.json)

集合中保留每个reference的原始run、source、result和文件hash。求解阶段不同不改变共同的游戏、窗口、效用、信息或认证合同；历史记录没有改名为新运行。

随后完整实跑了[一条命令入口](../../new/sparse_solver_v1_20261023/pipeline.py)，再次完成生成→补充搜索→保存→独立重载100个reference：[端到端完成记录](../../new/sparse_solver_v1_20261023/pipeline_e2e_v1/COMPLETE.json)、[实际100个reference索引](../../new/sparse_solver_v1_20261023/pipeline_e2e_v1/references/REFERENCE_INDEX.json)、[100个独立审核](../../new/sparse_solver_v1_20261023/pipeline_e2e_v1/references/INDEPENDENT_AUDIT.json)。入口先核对研究注册source hash，缺失或审核失败不会写成功完成标记。

这解决了当前100题在这个明确评价器下生成参考策略的计算阻塞。**当前节点Q/S的正式定义/消融实现、模型D、prompt及训练评分对齐仍不是本轮已完成的工作。** 窗口的边界/位置效应也仍需在实验设计中说明。不能把reference集合直接叫训练题库，或声称已修复v8的own-only评分缺口。

## 4. 第25局还缺什么

完整终局的第25局仍无可用标签。独立sequence-form LP与受限策略Nash搜索能够产生普通own-payoff Nash候选，但补齐逐节点合理性后会出现收益偏差，不能用于监督。

一个保存的数值根残差仅约6.8e-15，却含6个负概率分量；规范化后仍有约0.444的局部偏差，归零小概率后失败信息集由4变7。这证明“数值残差很小”不等于有效策略；也说明概率边界与零概率历史的信念切换必须在最终审核中处理。[原始对照诊断](../../new/sparse_solver_v1_20261023/boundary25_v1/diagnosis.json)。

当前off-path约定依然是：counterfactual reach恰为0时，用初始先验条件化自己的偏好与调查答案。没有擅自改成另一种信念，也没有证明这套额外约定在该局不可能满足。重复的支持、顺序、LP、MILP和fictitious-play尝试均有记录；失败不赋0、不删除题目、不据此断言不存在均衡。

## 5. 是否还只能有一个隐藏偏好

另外做了**不替换正式100题**的容量诊断：固定原池首个三人3目标和首个三人4目标的结构，按预定词典顺序把额外公开偏好改为独立私有支持。

两局都在**两个隐藏偏好、9个world、两轮、原生终局**下通过认证，公共树分别121641和170835节点。这说明“三人最多一个隐藏偏好”不是现阶段的绝对算法边界。

三隐藏偏好版本在本轮30秒预算下失败，不能报告为已支持。[四次完整诊断结果及raw版本](../../new/sparse_solver_v1_20261023/capacity_v1/results.json)。这些是容量检查，不是新100题库或规模普遍可解的证据。当前仍先构建完整公共树，再做缩减，尚未实现任意大游戏的免全树求解。

## 6. 独立基准与复现

仓库已有10月4日的[旧Gambit比较](../../new/local_data/strategic_slices_solver_comparison_v1/REPORT.md)，本轮没有把它遗漏成“从未做过基准”。该旧实现的稠密sequence tableau可能远大于公共树；当前一个两人失败局未经缩减时，单矩阵估计约93GB。

本轮新增稀疏sequence-form编码，并在真实失败局上对照随机策略收益及完整BR的LP值；另测已知混合均衡。直接MILP和PyGambit16.7.0对照没有成为整批成功后端，超时和接口错误记录都保留。不能把普通Nash候选称为通过我们完整逐节点合同，也不能把失败的预备接口调用当作求解性能结果。

Sequence form用于两人一般和博弈有成熟理论依据：[Koller、Megiddo、von Stengel原文](https://ai.stanford.edu/~koller/Papers/Koller%2Bal%3AGEB96.pdf)、[Gambit算法说明](https://gambitproject.readthedocs.io/en/stable/algorithms.html)。这些并不保证本游戏的任意规模或额外off-path/社会平局合同都能快速求解。

运行命令、CPU依赖和输出说明见[研究目录README](../../new/sparse_solver_v1_20261023/README.md)。所有实际run保存`pipeline_snapshot.json`、完整source副本/hash和原始成功/失败结果。默认不依赖GPU或Gambit。

五项CPU测试通过：真实游戏收益与完整BR等价、两人/三人缩减引擎对照、已知混合均衡、局部continuation修复反例，以及保留影响别人收益的自身平局选择。未进行GPU、LM采样、收敛学习或训练效果验证。
