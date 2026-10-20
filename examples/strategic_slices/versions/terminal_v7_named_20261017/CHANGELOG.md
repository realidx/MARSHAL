# v7：恢复9月题面与具名工具，建立强制版本快照

- 日期：2026-10-17。
- 父版本：`terminal-node-regret-grpo-refill-v6`，实际run job960070。
- 当前：`terminal-node-regret-grpo-named-v7`；prompt=`terminal-september-named-v1`。
- 授权：用户明确要求“立刻依据9月的prompt修改新的prompt”，并独立记录9月/当下配置；之后每版留痕。
- 状态：已实现；81项CPU检查通过；未运行GPU、未提交训练、没有模型效果结论。

## 相对v6的逐项修改

| 项目 | v6 | v7 | 原因 |
|---|---|---|---|
| system | generic action-index提示 | 复用9月D完整system原文 | 恢复已采用的解释+工具合同 |
| user | JSON状态、向量、action menu | 9月自然语言规则/表格/具名信息/时间线/current decision布局 | 恢复可读题面与作答要求位置 |
| 解释指令 | system，距回答较远 | system + user末尾明确简述再调用工具 | 用户要求brief explain；不用额外长度reward |
| tools | act(action_index) | OFFER/PASS/INVESTIGATE/ACCEPT/REJECT，named arguments | 恢复具名工具；一一映射原生合法菜单 |
| OFFER | full target bitvectors | NEW named additions，映射回同一个native target | 明确已有承诺与新增承诺的区别 |
| 当前游戏适配 | 旧JSON字段 | 公共catalogue/prior、私有调查、k窗口、固定reference及自身终局目标在自然语言中展示 | 保留当前科学定义；不照抄旧0.1容差/social tie/不同生成条件 |
| 路径 | v6接口 | 训练、验证（slice/full）、最终test、新D CLI都用named | 防止train/eval接口不一致 |
| 历史审核 | legacy | 旧JSON renderer保留；独立审核从logged request识别版本 | 不改原始证据，不让历史重放静默换题面 |
| 观测 | 原有metrics | 额外记录explanation出现、字符数及tool-only calls | 后续直接核验解释是否退化；不参与reward |
| 版本身份 | recipe/source合同 | 新recipe与prompt身份，final-test=`terminal-final-test-v4-named` | 拒绝v6旧checkpoint混续 |
| 留痕 | 分散配置与source | 历史原始配置快照、全字段CSV、逐项MD、当前冻结快照、run实际快照、启动和打包校验 | 用户要求每版可逐项比较 |
| source身份覆盖 | training/runtime/YAML | 加examples脚本、配置及fixture，D source增加实际复用的frozen helpers | 实际prompt实现必须纳入hash |

## 当前沿用的全部核心配置

- base：Qwen3-4B-Instruct-2507；seed42；selected-v4共100训练题，56父/37families；validation96/test200。
- data联合身份：`6080bc30f1a70b995bb9d7bfcdc3ed633bd0ff64bfd759691cf758f4533c4379`。
- 同一初态certified terminal profile；native utility和Q不变；k=1/2/3个focal实际决策。
- 每实际node8回答；均匀预选一个原始位置推进；完成即补位并发32；20实际node组/update，最多超2组。
- reward=Q−maxQ，失败=minQ−maxQ；本node sample-std归一化，eps1e-8，range≤1e-7置0；失败独立−.2。
- 节点/回答等权、回答token平均；同批一遍/一次optimizer；clip.2、KL.01、LR按tokens cosine1e-6→1e-7。
- context16384 / response1024；train temp1/top_p1/top_k−1/repeat1，eval greedy。
- 预算6M训练response tokens；500K验证、1M恢复保存；best即时保存；best+latest/final共最多2目录。
- tree512MiB /Oracle128MiB /prompt16MiB；精确reference延续值缓存，未改评分语义。
- validation按window success选best，并列取后；正常完成预算后final-only test，8 repeats；暂停不test。
- CLI默认仍为2×H100-47；job960070实际为单H100-96，**硬件差异不是本轮新改默认值**。实际CLI覆盖另存run snapshot。
- 未改变选题、D测量、探索、loss或已确认超参；未增加未解释惩罚、长度奖励、动态过滤或best-of-8。

机器可查的**全部**CLI默认、hardware profiles、YAML、合同、source哈希在[SNAPSHOT.json](SNAPSHOT.json)，不以本节摘要代替完整配置。

## 核验与限制

- [完整prompt预览](PROMPT_PREVIEW.md)：proposal、已有承诺、response、私有调查四种实际状态；[输入fixture](input_fixtures.json)。
- [原生日志迁移检查](native_interface_migration.json)：376个上下文、2045动作、53个私有调查上下文；原生菜单及tool round-trip错配0。
- [CPU日志](cpu_tests.txt)：81项通过；覆盖具名动作、隐藏world隔离、credit快照、收集/恢复、stream refill、full evaluation、final-test和版本门禁。
- [配置检查](check_only.json)：冻结注册后运行；不加载GPU或本地大模型。
- v6原始D/selection仍按旧JSON prompt测量，**不是新prompt D**；未重新测量，未重选题。
- 这次恢复不能保证模型持续解释，也不解决重复同一错误动作、信息题训练失败、held-out信息题不足、三人多轮和匹配SP训练臂未完成等问题。
- 按用户约束不要求独立GPU smoke；没有GPU采样/训练效果/吞吐/显存/收敛证据。

完整历史及差异：[配置对照](../../PIPELINE_CONFIG_COMPARISON_20261017.md)。旧快照不可覆盖；后续任何协议/默认值/执行实现改变必须创建新版本。
