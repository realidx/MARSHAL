# 2026-10-16：Terminal node GRPO v5 训练准备

已将用户确定的协议接入现有 ROLL 训练、验证、checkpoint 和 final-test。
当前可以准备 **slice 臂 GPU smoke**，不是已完成 GPU 验收或正式两臂实验。
本轮没有安装依赖、下载权重、调用模型、提交 Slurm 或启动 GPU。

当前协议/本地与 SoC 启动命令见[训练文档](../../examples/strategic_slices/TERMINAL_TRAINING.md)，
历史 v4 文档完整保留在[归档](../../examples/strategic_slices/TERMINAL_TRAINING_LEGACY_V4.md)。

## 已完成

- `terminal-node-regret-grpo-v5`：同一实际上下文8回答，连续负regret，组内mean/
  样本std；随机执行一个原始样本，最多k节点；丢弃的7个不展开后缀。
- 所有回答训练，节点/回答等权、token平均；20实际节点组目标，默认最多超2组；
  全批固定behavior，一次梯度累积更新。无过滤、补采、分数选路或旧跨轨迹baseline。
- 失败按全部合法动作最差值评分，独立−0.2 protocol项；抽中失败立即终止。
- 所有候选/失败response token计费；验证500K、恢复保存1M、best/final去重沿用。
  新增连续regret、零信号/动作重复、入口链/节点曝光和Oracle/生成耗时日志。
- 旧checkpoint和旧入口题数参数拒绝兼容；source/data/model合同仍严格校验。
  native独立回放已支持新的reset、候选和随机推进种子，同时保留旧D回放。
- 训练reward与严格0/1评测分开；验证增加合法regret、失败按最差动作regret、
  root/信息root分层；验证累计tokens和test tokens独立，test不参与best选择。

## 验收证据

| 检查 | 结果/证据 |
| --- | --- |
| CPU回归 | [50项全部通过](cpu_tests.log)：包含native回放、posterior不泄露、组内连续值、失败/随机推进、跨批采样、精确恢复、批次排空、loss梯度/token mask、独立监控调度、best/final/test生命周期。 |
| 默认配置与冻结数据 | [preflight](preflight.json)：100 train /56 parents，96 validation，200 test；20组×8、1024/16K、6M、500K/1M。 |
| 父游戏隔离/根价值 | [data check](data_check.json)：train/validation/test parent不相交；100 root members中89非平坦，11平坦，数据未修改。 |
| 真实冻结数据mock | [CHECK](mock_check.json)：两批各20节点组/160回答，分别14/13入口链，共27题；下一批恢复完全一致。 |
| 40组记录完整性 | [group audit](mock_group_audit.json)：320回答，同组prompt/scoring一致、8独立种子、恰好1个选中、所有loss权重=1。 |
| 单条真实数据多步独立回放 | [native replay](native_replay.json)：重新构造native轨迹、posterior和Q。 |

mock回答、token IDs和logprobs都是合成的；其任务活跃比例、完成率、奖励或严格正确率
**不是模型能力证据**。原始mock记录保存在 `new/local_data/terminal_node_grpo_mock_20261016/`，
纳入git的本目录只保存小型验收报告。

## 检查后仍剩的事项

1. **新协议GPU smoke/resume必须实测**：真实behavior logprob与actor偏差、一次
   optimizer更新、梯度、显存、耗时、保存和恢复。现有本机Python有numpy/torch，
   没有transformers/Hydra/dacite，未验证真实chat template、完整Hydra构建或
   16K最坏序列。已有SoC环境运行手动命令；旧GPU结果不替代v5结果。
2. **真实模型的信号覆盖仍未知**：连续reward保留已采到的价值差异，8个相同
   错误动作仍全零。11道平坦入口全是k≥2（7道k2、4道k3），都不是保护题；
   其中8道旧D在后续同题面确实有价值差异，其余3道只由整链损失/完成差异入选。
   这不等于11道整题都无信号，但它们入口不可能有task advantage，后续仍须
   按新sampler实测。详细ID在data_check；没有静默删除/重选数据。
3. **CPU Oracle开销**：现有reference cache仅保留2棵树，随机入口会重复恢复。
   真实数据mock需数分钟；它还包括下一批两次精确恢复检查，不是2次GPU update的
   耗时估计。新增计时分别记录collection、action-value查询和模型生成；树恢复等
   在collection剩余部分。GPU smoke应核对CPU是否成为主要瓶颈再决定缓存规模。
4. **完整匹配SP实验臂仍待准备**：本轮实现slice臂，不能宣称正式slices/SP实验
   已就绪。旧通用SP数据测试还存在既有prompt哈希失配，见
   [失败记录](legacy_shared_test.log)：`Prompt changed since label review: training/b_sft/social_named_probe.py`。
   没有通过修改review哈希绕过审核；相关共享padding/概率/上下文检查单独通过。
5. **评测覆盖限制**：没有独立强acquisition held-out family；test已在旧base D
   分析出现，不是从未查看的盲测。严格最优率、连续regret、completion和终局效用
   都须观察，不能只看completed-only效用或把mock活跃度当收敛证明。

## 传输与启动

保留原selected-v4数据包；只从中复制数据，不用旧source覆盖当前实现。
新的[源码overlay](../local_data/terminal_node_grpo_source_20261016.tar.gz)及
[SHA/身份](source_bundle.json)供已有完整MARSHAL checkout和SoC环境使用，
包含训练相关source/config/fixtures和当前操作文档；不含数据、权重或依赖。
部署到目标repo前先保存目标已有工作，再解包并校验`TERMINAL_TRAINING_SOURCE.json`
中的各文件hash，重新运行`--check-only`。本轮仅生成本地包，没有传输或部署。

按训练文档先1-update暂停、再恢复1-update；正式6M从base新开，清除smoke限制。
