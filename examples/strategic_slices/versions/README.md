# Pipeline版本记录

**2026-11-05新800远端D入口已接入并打包，未验证：**[完整远端命令与配置](../NATIVE800_D_REMOTE_20261105.md)。
用户明确不做验证，本轮没有执行CPU/mock/GPU/模型测试。新入口run_native800_d使用已审阅prompt-v4/scorer-v1及既有800/100父reference，独立于旧run_terminal_d。
每题8独立posterior resets、当前玩家控制到native terminal、对手冻结reference、父内32并发完成即补位；own terminalD和入口protocol/social分数分列，不自动选最终100。
逐轨迹原子gzip保存与严格身份恢复；后续决策不新求Q/S。传输包new/native800_d_remote_20261105/native800-D-v1.tar.gz含748个文件、约8.2MB，不含模型或完整profile。
新注册native800-terminal-D-v1完整记录CLI/默认参数/无验证状态，实际远端执行将写pipeline_snapshot；旧prompt/Q/S/scoring/GRPO及active v8不改。训练collector/SP训练臂仍未迁移。

**2026-11-05题面v4采用用户布局：**[修改与证据](../PROMPT_USER_LAYOUT_REVIEW_20261105.md)、[完整实际system/user/tools](native800_prompt_score_v4_20261105/PROMPT_PREVIEW.md)。
共同规则移入system，当前状态保留user；这是用户最新草案对此前短system选择的更新。用户明确回应平局规则不变，开头不扩展合作目标。
目标要求＋当前状态合表，全部required actions标committed/missing；一笔offer＋response为一条历史，pending文字在回应后替换，原机会编号保留。
800当前状态与工具、5493合法调用/评分、3044world对照、7原评分测试通过；2046单事件遗漏下历史物理状态可恢复，主Q/S与scorer-v1/GRPO不变。
首轮适配检查失败及源码保留，修正调查事件序列化读取后第二轮通过；未模型D/GPU/训练，完整runner未迁移，旧active v8不变。
用户对旧v3预览的手工修改保留，旧实际请求仍以cpu_v3归档为准；本版另存v4。

**2026-11-05题面v3按8项审阅改进：**[逐项说明](../PROMPT_REVIEW_NATIVE800_20261105.md)、[完整新预览](native800_prompt_score_v3_20261105/PROMPT_PREVIEW.md)。
保留9月短system＋user＋具名tools；删inferred-query提示与工具参数重复段，回应改自然说法但保留其他玩家总收益限定。
新增当前goal逐玩家要求满足数/完成度/缺少承诺，CURRENT COMMITMENTS与直接编号历史更易读；历史物理快照保留。
800完成度对照与2046历史遗漏不变性通过；表仅由原先强制保留的公开规则/当前承诺计算，不改Q/S或scorer-v1/GRPO。
数值效用和起始独立1/3先验保留但不强制输出算式。未模型D/训练，完整runner未迁移，旧active v8不变。

**2026-11-05新800题面与回应评分CPU对齐完成：**[修改与验证](../NATIVE800_PROMPT_SCORE_20261105.md)、[完整system/user/tools预览](native800_prompt_score_v2_20261105/PROMPT_PREVIEW.md)。
按用户选择保留9月短system＋user＋具名tools；各状态完整规则/偏好/历史/额度/生效承诺，累计本人调查答案每次重建，pending独立说明。
回应仅自身Q平局时使用others-sum负regret；proposal不favor，主Q/S与GRPO不改。800入口、5493合法工具、3044同信息world对照（额外不同world2244）通过；42回应集合较own-only纠正。
新800适配器及显式data binding已实现，40social题在构造组下有原GRPO信号；非模型训练结果。完整D/collector/SP迁移未完成，D未测，旧active v8不变。

**2026-11-04新版800候选已筛选并原生核对：**[覆盖配额、重复限制与结果](../SLICE800_COVERAGE_SELECTION_20261104.md)。
600训练候选/80父、200验证/20父，父与入口无交叉；获取信息A60/B20、已有信息利用320、估值160、规划160、回应80。
255入口保证至少两次本人决定；100父验收见证与60信息LP见证保留，同父物理骨架≤3；800可见事实/合法行动/答案支持与角色检查通过。
[800索引](../../../new/slice800_candidates_20261104/v1/ENTRY_INDEX.md)和[父游戏划分](../SLICE800_PARENT_SPLIT_20261104.md)可审查。
实际时限优化362父×用途/232父×actor，不宣称全局最优；3种typed结构跨split共享。仍须固定最终prompt/回应评分再测新D，未选最终100或训练，active v8。

**2026-11-04调查答案访问与前后S链条已核验：**[109/39/87分类与数学对接](../QUERY_ANSWER_ACCESS_20261104.md)。
235入口/51父的353个合法调查目标全部full/blind核验，整批706次独立LP通过。
109入口的调查严格优势依赖答案，39答案有增益但无答案仍严格更优，87无当前答案仍达原最优收益；不能混算信息获取覆盖。
353分支的答案增益与下一次本人context的既有私人S概率加权和一致，3522次条件belief对照通过。
三人答案必需16入口来自5父，需控制集中度；仅完成独立诊断，800/split/D/test未执行，生产active v8不变。

**2026-11-04入口供给审计完成：**[800之前的实际供给与集中度](../ENTRY_SUPPLY_AUDIT_20261104.md)。
100父全扫描，526569个正CF信息入口；1684个正own S、235个调查严格最优候选（答案因果收益未核验）。
正S中1124个只剩一次本人决策；两人/三人前两父各占正S46.1%/59.8%，应保护多步链条并限制重复结构。
589个原生小子树长度核对及全库存重读/旧计数对照通过。[逐父供给表](../../../new/entry_supply_20261104_runs/all100_v1/PARENT_SUPPLY.md)。
仅完成库存，800配额、train/validation成员、D/test尚未执行；生产active v8不变。

**2026-11-04合格65/35父池已完成：**[验收结果与完整入口](../QUALIFIED_PARENT_POOL_65_35_20261104.md)。
65两人/35三人，信息/估值/规划主用途分别40/15/10与20/5/10；现有182份profile足够填满，本轮未生成新题。
100个canonical父游戏、100来源组、90种目标结构；60个信息见证独立LP与100题见证全部行动Q重放通过，200资产hash核对通过。
实际62局有正own S；这是D前父池，不保证任意入口有训练信号。[逐题索引](../../../new/qualified_parents_6535_20261104_runs/review_v1/INDEX.md)保留参数、事实、Q及入选证明。
800/train-validation/test/prompt/D仍待接通，生产active v8不变。下方各阶段记录保留当时身份。

**2026-11-04父池目标65/35：**[组成草案与现有供给](parent_pool_composition_65_35_v1_20261104/DESIGN.md)。按用户偏好以65两人/35三人为目标；两人已有66可测、40有own S；三人保守去同源后27组有own S。60/20/20能力用途仍为提案，规划见证需审查，正式父100/800未选，生产不改。

**2026-11-04候选父游戏标签统一审阅完成：**[输入范围、方法与结果](../CANDIDATE_PARENT_LABEL_REVIEW_20261104.md)。83份profile补齐、7缺失保留；旧S/分布对照及249个不裁剪森林核验通过。私人答案组LB为辅助数学诊断，非新主S/筛选门槛；原100独立，D与800未做。

**2026-11-04父池/800范围澄清：**[用户决定与数学说明](slice800_design_v1_20261104/DESIGN.md)。父游戏允许按结构/标签迭代重抽；800含训练候选和验证，测试来自最终100之外的新父游戏。Q/S公式、门槛、比例待观察候选标签后讨论；仅设计记录，未生成/筛选或更改生产。

**2026-11-04 Q/S行动profile独立审阅：**[报告](../QS_ACTION_PROFILE_REVIEW_20261104.md)、[方法快照](qs_action_profile_v1_20261104/SNAPSHOT.json)、[单例18项LP核验](qs_action_profile_witness_v1_20261104/SNAPSHOT.json)。
原Q/标量S不改，补行动表/分布/当前与后续损失；原100已补算99题，25缺失，全部旧Q/S/遗漏分布匹配；三人448节点例18项强制动作LP匹配。D未测、未选800、生产仍v8。

**2026-10-29用户审查：**[真实三人游戏完整走读](../THREE_PLAYER_WALKTHROUGH_20261029.md)。
明确[1,1,2]为研究实例规模、非原框架固定规则；以新24池index10的实际[1,2,1]展示生成/9world/公开历史/私有答案/Q/S/终局分支。
原生448节点后续重放核对三个答案Q/S，独立LP给本例S区间[5/18,5/18]；17/18的Q含reference在proposal剩余平局上的混合，非唯一均衡标签。
新版800候选、控制长度/退出续接、prompt和D仍待审查接通；本轮仅文档和单例验证，不改规则或推进选题/训练。

**2026-10-29结构覆盖24题回传核对：**[完整统计、配对与见证](../STRUCTURE_POOL_RETURN_AUDIT_20261029.md)。
剩余18题17认证/QS且17/17独立重载；合并为22/24，缺4/11。14题有任一种own S，共114状态（私人87、历史27），112有当前动作损失。
2733文件hash/480项原source身份核对、15个原生终局后续Q重放匹配；仅10个完整隐藏位置配对，不能宣称定向位置普遍更好。
所有成功题非终局截断叶为0；原规则/主Q/S/prompt/reward/训练未改，D未测、active v8。下方保留各历史阶段状态。

**2026-10-26结构覆盖候选版本：**[方法、数据与实际执行](../STRUCTURE_POOL_PILOT_20261026.md)。
独立24候选、12配对：目标依赖/计分覆盖，随机隐藏位置与同目标贡献者隐藏位置配对；不强制全want，不按Q/S重抽。
偏好独立均匀与原生规则/终局Q/S不变；试验计分覆盖比例单独留痕，不是正式100分布。预定六例CPU实跑，5题终局认证/QS且5/5独立重载，3题共6个私人正S；1题重试仍缺失、18题未跑。
尚未证明改善稀疏S，D/训练未测，生产仍v8。

**2026-10-26行动—目标结构审计：**[结论与案例](../ACTION_GOAL_STRUCTURE_AUDIT_20261026.md)、
[最终关闭证据](A2H2_structure_answer_channel_v4_20261026/EVIDENCE.json)。
v1结构/原生节点重建，v2仅扩展到报价额度证明无后续承诺变化的尾部，v3回查调查入口，v4分解答案渠道。
原方法和每次输出关闭保留；全部复用已有reference，不改主Q/S、生成器、prompt或训练。D未测。

**2026-10-24/25 A2H2配对检查：**[整批结果](../A2H2_PAIRED_RESULTS_20261024.md)。
主求解沿用研究v1；新增[配对报告v1](A2H2_paired_audit_v1_20261024/SNAPSHOT.json)、
[完整/遗漏森林LP v2](A2H2_witness_LP_v2_20261025/SNAPSHOT.json)、
[显式导入环境v3](A2H2_audit_runtime_v3_20261025/SNAPSHOT.json)，旧方法快照不覆盖。
30/33认证/QS，29个可测配对；32次LP核对一致。首次直接导入失败保留记录，不能写成测量成功。
每次实际执行单独pipeline_snapshot；30/30独立重载通过，已关闭为[v3执行证据](A2H2_audit_runtime_v3_20261025/EVIDENCE.json)。生产active仍v8，D/训练未执行。

**2026-10-24稀疏S原因诊断：**[全批证据](H2_sparse_S_social_audit_v3_20261024/EVIDENCE.json)、
[结果报告](../H2_SPARSE_S_CAUSES_20261024.md)。先关闭6例方法v1，再以v2统一补全其余25例，
v3单列既定response社会平局的信息需求；不把联合遗漏或他人效用静默并入主S/训练。

**2026-10-24 H2本地执行与诊断：**[全部结果与实际预算](../LOCAL_THREE_PLAYER_FOLLOWUP_20261024.md)。
沿用关闭研究v1源码，33次尝试31局认证/QS，46/76较大预算重试仍缺失；31/31独立重载通过。
新诊断与每次CLI有各自snapshot，不覆盖研究快照或激活训练。
10个最大见证LP通过，独立关闭为[本地审计v1](three_player_local_audit_v1_20261024/SNAPSHOT.json)。

**2026-10-23三人复杂度研究v1：**[设计与完整快照](three_player_complexity_v1_20261023/SNAPSHOT.json)、
[小样有效性/25价值见证](../THREE_PLAYER_COMPLEXITY_20261023.md)、[远端指示](../REMOTE_THREE_PLAYER_20261023.md)。
H2优先，原100保留，25不直接删除；远端33局效果仍待运行，不激活训练。

**2026-10-23节点Q/S审计v1：**[可执行约定](node_qs_audit_v1_20261023/DESIGN.md)、
[完整快照](node_qs_audit_v1_20261023/SNAPSHOT.json)、[整批结果与真实案例](../SOLVER_QS_AUDIT_20261023.md)。
终局99/窗口100完成测量，66个最大S见证通过独立LP；三人信息信号稀少。25仍缺失，D/训练未运行，active仍v8。

**2026-10-23 solver研究v6：**[逐项变化](terminal_solver_repair_v6_20261023/CHANGELOG.md)、[完整结果](../SOLVER_REPAIR_20261023.md)：统一窗口100/100认证/重载复核；完整终局99/100、25缺失。版本独立登记，旧v1/v2设计和远端快照保留；未激活训练或测新Q/S/D。

**2026-10-22有限窗口检查：**[设计v2与结果](game_design_v2_window_20261022/RESULTS.md)：原100开局树缩小约4/8.7倍；
预定26题18通过窗口认证、8缺失。4个父游戏验证私有答案访问收益；非终局标签补全，未测完整S/D或训练。

**2026-10-22远端实际结果：**[本地核查](../../../new/remote_solver_results_20261022/LOCAL_REVIEW_20261022.md)确认多版本合计85/100认证、15缺失；
新Q/S/D与训练未运行。下方“远端尚未运行”等内容是此前交付时的历史状态。

**当前设计统一快照：**[游戏 / solver / Q/S/D v1](game_design_v1_20261021/DESIGN.md)，
[完整参数与组件hash](game_design_v1_20261021/SNAPSHOT.json)。设计版本与生产active分开记录，旧快照不覆盖。

**远端求解交付：**[CPU指南](../REMOTE_SOLVER_20261021.md)和
[本地验收](../REMOTE_SOLVER_VALIDATION_20261021.md)对应独立研究版本
`strategic-parents-remote-terminal-solver-v1`；固定原始100池，未激活训练版本或执行远端任务。

**新游戏研究版本：**[已确认的调查目标规则](../KNOWN_QUERY_RULE_20261021.md)、
[新100原始父游戏](../PARENT_POOL_V1_20261021.md)及
[12例终局认证检查](../PARENT_POOL_V1_PROBE_20261021.md)另行登记，生产active仍v8。
父游戏池没有按求解成功或Q/S/D替换成员，当前7例认证、5例无可用结果、88未尝试。

**原100父游戏整批研究：**[完整结果](../OFFER_QUOTA_ORIGINAL_POOL_RESULTS_20261021.md)为70局等价、29局新认证、1局仍缺失；
99个有效配对真实调查见证6→16。求解预算、初始化和旧profile起点重试分别有snapshot；未激活新训练版本。

**当前研究：只给OFFER增加个人报价额度限制，调查机制保持原样，dependent preference暂缓。**
[首轮14次终局认证结果](../GAME_OFFER_QUOTA_RESEARCH_20261021.md)与
[独立研究记录](game_offer_quota_research_20261021/SNAPSHOT.json)已保存；未激活为训练版本。

**2026-10-21免费调查时机诊断：**[精确检查](../GAME_FREE_INVESTIGATION_TIMING_20261021.md)发现，
原合同toy免费开局调查已达收益上界；若后续公开信息改变相关目标，等待收益1可严格超过开局的3/4。
[独立快照](game_free_investigation_timing_draft_20261021/SNAPSHOT.json)仅登记机制诊断，未激活生产规则。

**当前优先游戏机制设计，prompt改版暂停。**
[合同选择机制提案](../GAME_MECHANISM_PROPOSAL_20261021.md)及
[独立设计记录](game_contract_choice_draft_20261021/SNAPSHOT.json)验证了一个新两人校准模型：
同预算下调查5/3，最佳offer试探4/3；二值信号/更多试探机会控制的调查优势为0。
它不是当前原生轮换游戏的证书，未激活规则、未改题库/生产代码/参数；index另列game_design_proposals。

**2026-10-21审阅：**active仍为v8；发现响应平局规范在参考策略与own-only训练/评分间存在缺口，
因此不能把现有v8称为本轮完整规范下的训练就绪版本。已生成
[V9状态化题面草案](terminal_v9_state_draft_20261021/PROMPT_PREVIEW.md)，仅在index的drafts登记，
未激活、未改变生产代码/数据/参数。事实核对和后续设计见
[完整审阅](../PROMPT_PROTOCOL_REVIEW_20261021.md)。

当前active版本由[index.json](index.json)确定。历史配置及差异见[逐项配置对照](../PIPELINE_CONFIG_COMPARISON_20261017.md)。各历史SNAPSHOT注明原始证据、sha256与回溯记录身份；配置缺失不能用当前默认值补造。

| 版本 | 记录 |
|---|---|
| 9月BP /866677 | [快照](september_bp_866677/SNAPSHOT.json) |
| 9月SP /866677 | [快照](september_sp_866677/SNAPSHOT.json) |
| 9月D /881010 | [快照](september_d_881010/SNAPSHOT.json) |
| 10月terminal v3 /915731 | [快照](terminal_v3_915731/SNAPSHOT.json) |
| terminal v6 /960070 | [快照](terminal_v6_960070/SNAPSHOT.json) |
| terminal v7 /未运行GPU | [修改清单](terminal_v7_named_20261017/CHANGELOG.md)、[prompt](terminal_v7_named_20261017/PROMPT_PREVIEW.md)、[快照](terminal_v7_named_20261017/SNAPSHOT.json) |
| terminal v8 /未运行GPU | [逐段审阅](../PROMPT_REVIEW_20261018.md)、[修改清单](terminal_v8_readable_20261018/CHANGELOG.md)、[prompt](terminal_v8_readable_20261018/PROMPT_PREVIEW.md)、[快照](terminal_v8_readable_20261018/SNAPSHOT.json) |

- [5个历史run的全部resolved字段对照](HISTORICAL_ALL_RESOLVED_FIELDS.csv)：412种字段路径。
- [历史实际options与v7全部CLI默认值对照](ALL_RUN_OPTIONS_AND_V7_DEFAULTS.csv)：null与NOT_RECORDED区分。
- 每目录保存完整system/user/tools request，不用“prompt没变”代替证据。

## 建新版本

1. 修改版本常量，选择新目录。先写CHANGELOG.md：父版本、授权/动机、逐项差异、完整配置入口、检查与限制。
2. 导出**正式request**生成的PROMPT_PREVIEW.md及JSON；导出脚本当前指向v8，下一版需要同步指定新目录/版本。不覆盖已关闭版本的文件。导出/审计脚本拒绝覆盖已有SNAPSHOT的目录。
3. 核验数据、D与selection的实际版本/hash；变更prompt但复用历史选题时显式标明，不把旧D改名为新D。
4. CPU检查完成后执行 `python -m examples.strategic_slices.freeze_pipeline_version --directory 新目录名`。parent默认原active版本，也可显式`--parent`。脚本拒绝覆盖版本，冻结CLI默认、profiles、YAML、合同、source和review文件hash，并更新active索引。
5. `train_terminal`和source overlay打包入口先核对注册快照；source或冻结的prompt发生未登记改变时失败。GPU运行时另存 `pipeline_snapshot.json`：实际CLI覆盖、最终resolved config、数据/模型/source身份和训练合同。
6. 临时CLI覆盖保存在独立run快照；有意改变协议/默认值必须建新pipeline版本。v8不得resume v7/v6；保持版本一致的恢复也必须通过原有严格合同检查。

注册快照不是训练结果：当前v8只完成CPU检查。真实run的环境、日志、checkpoint、指标属于其实际版本，应保存在run目录并追加结果记录，不得改写已冻结的配置快照。根目录[AGENTS.md](../../../AGENTS.md)要求后续修改持续执行此流程。
