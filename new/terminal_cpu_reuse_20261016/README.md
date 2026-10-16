> 后续验证/测试已接入[完成即补位](../terminal_evaluation_refill_20261016/README.md)，当前源码包见该记录。本页保留CPU复用优化验收身份。

# 2026-10-16：无独立GPU smoke的CPU复用验收

用户明确目前不能跑GPU smoke。当前准备不依赖独立GPU试跑：完成CPU一致性/
缓存检查，未来由同一个正式任务前几步记录实际GPU运行情况。本轮没有提交任务、
启动GPU、下载模型或进行真实模型调用。启动方式见[当前训练文档](../../examples/strategic_slices/TERMINAL_TRAINING.md)。

## 已实现

- Reference树从固定2棵LRU改为默认512MiB估算字节预算；Q/延续值独立128MiB，
  不随树淘汰而丢失。CLI为`--tree-cache-mb`/`--oracle-cache-mb`，Slurm环境变量
  为`TERMINAL_TREE_CACHE_MB`/`TERMINAL_ORACLE_CACHE_MB`。单项超预算不保留，0
  可关闭保留；统计hit/miss/eviction/bytes和累计恢复时间。
- 窗口内保持完整枚举；k结束后复用同一冻结终局reference的精确价值。
  延续值按需填表，跨posterior/k使用相同all-world value，保持基于可见信息的
  评分belief；不使用采样隐藏world的点质量评分。缓存限定dataset/reference/
  player，行动Q还包含node/remaining k/posterior。
- 旧`extreme_value`完整遍历保留，离线独立审核仍走旧路径；训练/validation
  后续Q查询使用`cached_extreme_value`。冻结root_Q、原数据和reference策略不改。
- 同stream内相同messages/tools一次tokenization，8个回答复用prompt IDs。
  缓存预算16MiB；每个回答的seed、response limit、context检查和behavior证据
  都独立，编码缓存不依赖actor权重，记录tokenization/hit数量。
- 采样、同节点G=8、20组预算、reward/GRPO/loss、验证/保存频率和checkpoint
  规则均保持既定定义。缓存仅驻内存，不序列化进checkpoint；恢复后重建缓存。

预算控制的是缓存估算保留量，不是进程RSS。正在执行的rollout/求值也持有树/
数组，numpy基础buffer等按对象图估算；没有宣称默认预算适配所有CPU内存环境。
没有实现磁盘编译树缓存、GPU参数调优或更复杂的CPU/GPU异步重叠。

## 已通过的CPU检查

- [64项相关回归通过](cpu_tests.txt)，包括此前59项和5项新增检查：
  2/3人、k=1/2/3、max/min完整Q/策略等价；不同posterior和超过剩余局长的k；
  缓存淘汰/namespace隔离；树淘汰后Q保留；prompt只编码一次且独立检查输出预算。
- [冻结训练数据抽查](frozen_data_check.json)：2/3人各k=1/2/3，共6题；新旧Q
  最大误差均为0，所有受控节点策略一致，reference身份未改变。每次warm查询
  `tail_nodes_computed=0`，重用同一reference延续值。不是100题全量逐节点证明。
- [默认配置preflight](preflight.json)：数据身份和训练默认值保持不变，记录新增
  CPU缓存预算；不检查本地模型或GPU。

可复现：

```bash
python -m unittest training.strategic_slices.test_cpu_reuse training.social_mixed.test_native_stream
python -m examples.strategic_slices.check_terminal_cpu_reuse --output /tmp/terminal-cpu-reuse.json
python -m training.strategic_slices.train_terminal --check-only
```

冻结数据抽查记录首次树恢复累计38.72秒；6题旧Q查询合计约0.069秒，warm查询
合计约0.046秒。缓存保留6棵树，估算约504MiB，Q/延续值约18.8MiB。这个小样本
说明恢复树比这些近终局Q查询更贵，不能据此预测正式训练缓存命中率；没有把
warm-cache求值结果扩写成GPU或整个训练的提速倍率，也没有将6个样本的微秒计时
当作严格benchmark。

## 后续运行边界

不要求另开GPU smoke。正式任务沿用已有初始validation、第一步参数变化记录、
behavior/actor概率对照、有限loss检查、阶段时间和显存等诊断；异常机制不变，
有限概率偏差依旧只报警。没有增加每步验证/保存，也没有将初始几步变成额外
预算或另一个实验。首个真实任务仍可能遇到CPU测试覆盖不到的GPU依赖/显存问题。

新旧source不能混续，缓存配置也纳入现有run contract；代码更新后从base新开。
GPU吞吐、16K最长序列、真实optimizer及GPU恢复当前均未验证；这些事实不因取消
独立smoke前置条件而改变。SP臂、held-out覆盖和原test暴露等限制见此前记录。

新的[源码overlay](../local_data/terminal_node_grpo_cpu_reuse_source_20261016.tar.gz)
及[SHA/身份](source_bundle.json)适用于已有完整checkout/环境；不含数据、模型或
依赖。此前v5/v6包保留历史身份，当前启动应使用本包或当前repo代码。
