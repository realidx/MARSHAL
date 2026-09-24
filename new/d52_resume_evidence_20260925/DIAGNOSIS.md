# D52 续训审查

发现请求与评分命名变体不一致：InteractionCollector 对静态题调用 request(task)，paired_requests.request 默认 variant=0；reasoning_scoring.score / social_bp_training.reward 使用 task.name_variant。记录中的第 43 步 P 示例 name_variant=1，原 completion 本地重评分复现 ValidationError；仅将评分 variant 设为实际请求的 0 后为合法、正确、奖励 1。

对归档 step26–52 全部静态 calls 中 invalid_action，用当前本地 interaction_bank_v1 对应 task 进行上述离线重评分：

|类型|日志 invalid_action|按请求 variant0 恢复合法|其中正确|
|---|---:|---:|---:|
|B|294|284|182|
|Pplus|348|325|176|
|静态O|61|53|34|

合计 662 个原记为无效的回答恢复合法，其中392个正确。不是新模型生成，也不是修复后训练效果；仍需逐题核对归档来源 commit/data manifest 与本地 bank 的一致性。该接线错误足以污染任务 advantage 和协议惩罚，不能再将这批训练当成干净的训练方法/数据集假设检验。短交互 O 不纳入此重评分统计。

续训恢复路径指向 checkpoint25；metrics 有26–52更新，另一个39行不是完整 optimizer metrics。梯度范数0.525–2.200，clip fraction约1.11–1.79%，实际LR9.186e-7→7.119e-7。数值量级本身不是上述评分错误的排除证据。

B 864回答中275次截断，约31.8%，是与评分接线错误分开的仍存问题。CalBench README报告6/24完整协调、3/24最优、headline0.486188；本批没有同链checkpoint25的配对测试，不能单凭D52终点归因为续训使泛化下降。

本次未改训练代码、未启动或提交训练。应先修复静态请求 variant 传递、做请求到评分回归核查，并确认错误首次引入位置后再选择恢复点；不能通过重算日志撤销已发生的参数更新。

## 2026-09-25 进一步核验

- `git log`：interaction_training.py 首次出现在 da0e670（2026-09-24 14:01:54 +0800），新静态请求漏传 name_variant。其父提交 reasoning_training.py:190 和 core.py:256 均显式传 task.get('name_variant',0)。不能据此追溯归罪于全部旧实验；本条新collector训练链需追查checkpoint25之前。当前bank与da0e670中的tasks.jsonl逐字节SHA256相同（37063c55133f6b3b1c159a77a271886e9d5daafb22711935baa684241f033dd1）。
- B 275个截断全部 task_advantage=0、protocol_advantage=-0.2。有抑制截断的惩罚，并非完全无梯度。语义标准化只纳入合法且可评分回答；正确+截断本来就不会构成语义正负对比。修正映射后仍有17组“有截断，合法回答全对”，这17组仍没有语义对比。
- B 108组中，实际26组有任务信号；离线按实际请求变体修正后58组有信号。正task advantage回答72→155。离线重评分不代表修复后模型学习结果。
- P 108组有信号36→58；静态O54组有信号22→27。后半段任务抽样不同，不能将原始正确率差直接称为同题退化。
- short O：54组×8=432条轨迹，399条正常终局、33条失败；40/54组非零advantage，178条轨迹正advantage。26–38为23/26有效组，39–52为17/28。每步2个短交互组，占O组数一半；三任务等权，所以它的名义任务权重为总量1/6。多决策轨迹按长度摊分权重，不能用call数量声称更大更新权重。
- 短交互始终以variant0同时生成与解码，不经过静态teacher的name_variant评分错误。隐藏世界和伙伴策略均按replica采样，奖励差异不是纯策略差异；不能把有advantage当作已经获得正确信用分配的证明。全部为两人、最多2–3次ego决策、固定选定策略伙伴，并非多模型自由协商。
- 此27步中O108组涉及108道不同题；B108组涉及107题；P108组涉及108题。该区间基本没有同题重测，不能从前后分段均值推出逐题学习/遗忘；也不能说曝光问题已经验证解决。

离线统计脚本：`PYTHONPATH=. python new/d52_resume_evidence_20260925/audit_learning_signal.py`。不发模型请求，不修改训练或评分源代码。

## 修复落地与验收

已修复 interaction collector 两处静态 request 的 variant 传递，新增生成前工具 schema 一致性检查；记录call的实际variant。版本升级 interaction-v2-name-contract，启动recipe与restore均拒绝旧interaction-v1的直接恢复。增加短交互生成数量校验与分模式信号metrics。启动器运行新回归测试。

验收：18项单元测试通过（全500静态题gold提交到真实评分器、错配拦截、恢复边界、完整collector权重、失败事务性、协议与masked规则）；原生800条短交互回放通过，1866次live decision。bank SHA与原训练commit一致。报告见fixed_pipeline_preflight.json。

限制：本地无hydra，完整configuration测试未执行成功；未提供真实tokenizer，因此本次CPU preflight未检查真实token长度；没有GPU训练验收。启动脚本保留上述真实环境检查。没有修改用户paper文件、没有启动远端训练。旧测试对已废弃paired-5采样槽的断言改为当前四个不同B题组覆盖检查。
