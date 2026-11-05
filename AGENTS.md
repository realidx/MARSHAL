# Strategic slices实验版本记录

用户明确要求：沿用9月可读题面与具名工具；任何prompt、工具、题目筛选、Oracle、奖励、
advantage、训练参数、采样、评测、保存/恢复或运行环境的改变都必须留痕，不得当作内部细节省略。

- 修改前读 `examples/strategic_slices/PIPELINE_CONFIG_COMPARISON_20261017.md` 和
  `examples/strategic_slices/versions/index.json`，确定当前基线。
- 已关闭的版本快照不可覆盖。语义或参数默认值变化时增加版本，保留原快照；在版本索引中列出
  与父版本逐项差异、动机、用户授权范围、完整参数及验证结果，区分已运行与仅实现。
- prompt变更必须导出实际request函数生成的完整system/user/tools样例并链接，不能只摘一句提示。
- 保存题库/selection/D测量的版本与hash；更换prompt后不能把历史D误称为新prompt的测量。
- 代码/source与注册快照必须匹配；每次实际运行必须写入完整 `pipeline_snapshot.json`，包括CLI覆盖、
  resolved config、模型/数据/source身份、采样/reward合同。配置缺失项标“未记录”，不能用今日默认值补猜。
- 旧记录与旧checkpoint保留原身份，不静默混用新接口；CPU验证不能写成GPU、收敛或效果验证。
- 2026-10-18题面审阅：保留当前玩家真实调查答案，去掉额外来源/谁由调查知道什么的提示；
  公开调查行为保留在历史。计分定义集中在GAME RULES，公开事实与当前私有事实分开。
  简化偏好support必须先证明与题库概率等价，不得删掉真实联合限制；见
  `examples/strategic_slices/PROMPT_REVIEW_20261018.md`。
- 2026-10-21：全体玩家只在ACCEPT/REJECT自身预期最终效用平局时，优先最大化其他玩家
  预期最终效用总和；不扩展到proposal。已发现v8参考策略有此规则、focal评分却只看own Q的
  缺口，不能只补prompt就声称已对齐。状态/累计调查答案必须每次完整披露；V9目前仅审阅草案。
  继续工作先读 `examples/strategic_slices/PROMPT_PROTOCOL_REVIEW_20261021.md`。
- 2026-10-21当前工作顺序：先解决游戏机制，再继续prompt。稀缺资源/有限合同/期限/联合类型的
  校准提案见 `examples/strategic_slices/GAME_MECHANISM_PROPOSAL_20261021.md`。
  新的两人非对称原型已做精确分数验证，但不等同现有轮换提案或三人游戏的认证；未激活新规则。
- 2026-10-21后续用户澄清：机制研究固定原100父游戏，允许有些题不需调查，不以额外toy代替整批。
  仅研究提出OFFER立即扣个人报价额度，调查和独立偏好保持原样，dependent preference暂缓。
  整批现为70局等价、29局新认证、1局未认证；未认证局仍保留，不能按0信号或旧profile当新标签。
  见 `examples/strategic_slices/OFFER_QUOTA_ORIGINAL_POOL_RESULTS_20261021.md`。当前未激活新训练版本。
- 2026-10-21最新用户确认：新游戏排除调查已公开偏好和本人已直接查过的偏好；不按推断、
  Q/S或真实隐藏world删目标，不额外奖励少调查/少回合。见
  `examples/strategic_slices/KNOWN_QUERY_RULE_20261021.md`。旧“固定原100”的范围仅保留为历史诊断；
  用户随后授权重新审计规模与生成方式，新100原始父游戏见`PARENT_POOL_V1_20261021.md`。
  新池不是已认证训练题库；保持旧生产active，先完成游戏/标签审计，再改prompt、测新D。
- 2026-10-22：用户同意检查“1 RR加当前玩家下一次proposal及完整回应”的有限规划窗口，
  允许相对于明确合理的评价器定义Q/S，不再把终局Oracle作为唯一候选。独立研究v2见
  `examples/strategic_slices/versions/game_design_v2_window_20261022/RESULTS.md`：26题18通过窗口认证，
  不等于修复终局标签；私有答案访问诊断不是已完成当前节点S，模型D未测，生产active仍v8。
  已关闭v1保留原终局口径；新窗口有位置/边界效应，不能直接当作已激活训练合同。

- 2026-10-23 solver研究v6：统一已批准窗口100/100认证并保存后独立复核，完整终局重新求解99/100（25仍缺失），未替换正式父池或激活训练。逆向缩减必须保留影响其他玩家收益的自身平局选择；候选惯性BR和实际continuation局部修复均须完整原生认证。三人两隐藏偏好仅有两例额外容量诊断认证，不是正式题库升级。见`examples/strategic_slices/SOLVER_REPAIR_20261023.md`及独立版本快照；新Q/S/D仍未完成。

- 2026-10-23节点Q/S审计v1：终局99与既有统一窗口100已实际测量，见`examples/strategic_slices/SOLVER_QS_AUDIT_20261023.md`。
  主S为当前真实信息下完整后续策略的逐条遗漏损失，遗漏策略剩余平局均匀；另外记录当前第一步regret，不混成同一标签。
  counterfactual为0时S=null，非0信号；25的4/7个失败信息集均为零counterfactual路径，终局仍缺失。
  终局三人只有17/35两局正S；66个最大S见证通过独立LP，不能推广成所有标签对均衡/平局不变。
  调查前答案访问收益是独立诊断，不替代当前S；历史S可能涉及后续策略/更高阶信息，不全是本人偏好posterior变化。
  D、最终prompt/选题/训练未做，生产active仍v8；扩三人隐藏偏好/承诺维度仅建议，未改原100或激活新规则。

- 2026-10-23用户授权增加三人复杂度、重计算走remote；25只有在不属于有价值博弈场景时可换。
  新研究`three-player-complexity-study-v1`冻结原33局配对H2/H3/A2H2各33候选，旧100不改。
  H2新增隐藏偏好分属不同玩家；2RR/调查1/报价1/独立均匀先验不变。预定3/7终局子局与一个匹配旧reference的完整父游戏确认正S增加，非整批效果。
  25的两个末轮原生子局中，调查G2有当前报价S=1/6（独立LP与重载），因此先保留挑战案例；未补齐完整开局reference，D/典型性未测。
  远端先跑H2共33局，操作见`examples/strategic_slices/REMOTE_THREE_PLAYER_20261023.md`；重计算未在本地整批运行、未代连接远端。
  9个小样最大S见证LP通过，8个保守下界>0；A2H2原3私有S有平局依赖，不能全称稳健。生产active仍v8，未切换prompt/训练。

- 2026-10-24用户追加本地尝试及继续授权：H2全部33局实际尝试，31局原生terminal数值认证/QS；
  原46/76在候选120秒及600秒两次尝试后仍缺失，不按0或低价值替换。31/31保存后独立重载通过。
  同组正S父游戏2→9，reference路径2→3；183348个可测context仅49个正S（45个当前行动regret>0），
  reference路径仅6个正S。10个最大见证LP一致，保守平局区间均为正单点，不推广为全部49个或跨均衡稳健。
  原35的2个严格调查最优节点在入口已按reference推断确定答案；始终不给答案收益不变，不能混称信息获取收益。
  完整记录`examples/strategic_slices/LOCAL_THREE_PLAYER_FOLLOWUP_20261024.md`与本地审计v1；
  原研究关闭快照不改，H3/A2H2完整整批未跑，D/新prompt/正式选择/训练未做，生产active仍v8。

- 2026-10-24用户要求查稀疏S：诊断v1先冻结6例、v2统一补齐其余25例，原31全部完成。
  数值门槛非原因；23392个有答案歧义的私有遗漏组整组own S=0且有共同当前最优动作；
  94614/183348状态在固定reference下后续自身收益无可分辨控制空间，不能因此判无社会平局需求。
  联合遗漏入口已有历史/调查答案仅作诊断，未来新观察保留，121个正状态/10个父游戏，未替换主S49/9。
  v3另查response社会平局：395个当前Oracle动作评分敏感状态的主own S均0，其中277个终局回应
  已核对实际他人效用损失。不能再把49当作完整协议信息需求；主S/游戏/reward均未改，需讨论评分目标口径。
  47次LP检查（31个代表性原零S组、16个复合见证策略求值）一致；D仍未测。
  详见`examples/strategic_slices/H2_SPARSE_S_CAUSES_20261024.md`和独立方法/执行证据，旧快照保持原身份。

- 2026-10-24/25用户同意继续A2H2：同原33三人局、2RR/调查1/报价1/两隐藏偏好，给一名玩家增加第二承诺选项；仍可累计，不加互斥。
  完整尝试33局，30局终局数值认证/QS，原10/49/76候选不可用；30/30独立重载通过，缺失不按零/低价值替换。
  同29可测配对主own S状态43→632、正S父游戏8→9、当前proposal损失35→518；62/78占正状态约94.8%。
  10游戏16见证共32次完整/遗漏森林LP求值一致，保守区间均为正单点；不推广全部标签或跨均衡不变。
  reference决策占用中的正S比例0.0244%→0.1080%，非模型D/advantage；社会平局信息仍单列。
  配对v1/LP v2计算冻结；直接启动导入路径失败留档，运行环境v3只补显式依赖路径和线程记录。
  见`examples/strategic_slices/A2H2_PAIRED_RESULTS_20261024.md`与v3 EVIDENCE；旧100/生产v8/prompt/奖励/训练未改，D未测。
  目前仅研究候选，未冻结正式100；后续建议审查62/78结构与零S对照，再定规模/生成分布、prompt及D，不自动继续扩大轮数/私有偏好。

- 2026-10-26用户授权先做行动—目标结构诊断：全33结构/30标签复用，68个代表context的完整原生后续Q重放一致，300项收益保守区间通过（268项可独立定值）。
  20个零S代表私有答案proposal组：8组Q相同、12组Q变化但有共同own最优动作；不推广零CF历史或其他reference。
  62/78的强S代表均有公开全want受益者，两名他人持隐藏偏好；不是全want角色必要/充分证明，不据此强制重生成偏好。
  62代表高收益合同给回应者自身增益0，通过社会平局接受；78代表也有此依赖，且后续玩家报价已耗尽，无法补救。
  focal own-S正不等于独立于对手社会平局规则。62/78分别501/98状态仅计为67/31物理骨架，不能合并历史/信念或称独立训练题。
  原调查路径62完整答案1.2134146、屏蔽答案1.0609756、最优非调查1.1067073；78为1.3333333/1.3/1.3333333。
  因而62此入口调查需要私人答案才胜过非调查；78答案有价值但调查与报价平局，不能仅由正S宣称调查严格必需。
  独立诊断v1→v4已关闭，见`examples/strategic_slices/ACTION_GOAL_STRUCTURE_AUDIT_20261026.md`；原100/主Q/S/生成器/prompt/reward/训练不变，active v8，D未测。
  新生成分布尚待讨论；建议显式覆盖有真实合作意愿差、最优报价随信息切换及不需调查的结构，未实施新选题/比例/角色限制。

- 2026-10-26用户同意结构覆盖生成：新独立候选版本`three-player-structure-coverage-pilot-v1`冻结24题/12配对，不覆盖原100或旧33。
  保持三人2RR、3/4目标、[1,1,2]行动、两隐藏分属两玩家、调查1/报价1、独立均匀偏好；新目标结构split/bundled与计分binary/mixed/linear各等量是小批覆盖分布，不是正式题库默认值。
  uniform隐藏位置与同一目标两位行动贡献者隐藏位置配对；不强制全want，不以Q/S或求解结果重抽。
  预定六例实跑，5题终局数值认证/QS，5/5独立重载；3题共6个私人正S且当前proposal regret为正，均无公开全want角色。
  index4先SearchLimit，候选600秒独立重试仍BR循环/joint不通过、未测；失败保留，不能置零或按低价值替换。18题未运行，尚无改善信号稀疏证据。
  主Q/S/原生规则/prompt/reward/训练不改，active v8，D未测；详见`examples/strategic_slices/STRUCTURE_POOL_PILOT_20261026.md`与版本EVIDENCE。

- 2026-10-29远端结构池回传已核对：正确runtime_v4剩余18题17认证/QS并17/17独立重载；与本地合并22/24、22/22重载。
  缺4/11，11候选600秒重试仍内部SearchLimit；保留失败，不当零/低价值替换。错误数值环境取消作业与两次启动前失败隔离，不混入。
  2733归档文件hash、原480项source和题库身份匹配；所有成功题cutoff_leaves=0，实际到原生第6次proposal终局，不是有限深度近似叶。
  14/22有任一种own S：私人11题87状态、历史4题27状态，合计114/246713=0.0462%，112当前动作regret>0；reference正S63状态、占决策概率质量0.5476%，非模型D。
  仅10完整配对：私人正S父游戏uniform5/10对shared_goal4/10；合并历史变5/10对7/10，不能硬设同目标隐藏位置优于随机。
  bundled9/11对split5/11有own S，全linear5/6有信号但缺失两题也是linear；小样分层关联非因果/效果证明，正式100分布未定。
  14父游戏15最大渠道见证原生剩余游戏Q重放全匹配，未新做遗漏森林LP/跨reference稳健性；主Q/S/prompt/reward/训练未改，active v8，D未测。
  见`examples/strategic_slices/STRUCTURE_POOL_RETURN_AUDIT_20261029.md`及独立审阅v1 EVIDENCE；旧关闭报告不改。

- 2026-10-29用户要求停止盲目推进、先审查三人具体流程：见`examples/strategic_slices/THREE_PLAYER_WALKTHROUGH_20261029.md`。
  [1,1,2]仅为本轮可求解实例参数范围，不是原GameSpec限制，也未确定为正式父池默认；实际新24index10为[1,2,1]，与旧original_index10不是同一题。
  使用保存reference重放该例公开历史并按native step持续私有答案；448节点、三个答案context的Q/S匹配，完整/遗漏LP及目标最优面边界给S=[5/18,5/18]。
  最优报价Q17/18包含最后P1在自身proposal平局时的reference混合；仅此固定reference下核验，不宣称跨均衡唯一；调查前Q优势71/810与当前S不同。
  当前已实现的节点Q/S不等于已导出新版800slices；模型控制长度/退出续接、最终prompt与response评分对齐、D仍需审查，不将旧k=1/2/3分布自动激活为新设置。
  用户流程为父游戏池→800候选slices→D→100训练slices，不能将最终100混写为100父游戏；本轮不生成候选、不测模型、不改游戏/prompt/reward/训练，active v8。
  独立走读v1保存source/input/实际pipeline_snapshot与验证证据；先完成用户审查，再推进数据与训练配置。

- 2026-11-04用户授权审阅行动分布型Q/S，并已同意slice入口起控制当前玩家至原生终局（训练代码未激活）。
  独立profile v1保留旧Q/标量own S，新增遗漏主观Q、真实入口下遗漏后续行动Q、相对regret向量、canonical完整/遗漏分布与TV/JS；
  S精确分为当前动作与后续损失，不用softmax/温度猜LLM，不把canonical分布变化当D或直接难度排序。
  原20261021父池100请求、99终局reference补算/重新认证，25仍缺失；全部旧Q/S/已保存遗漏分布逐项匹配。
  260971可测context：主S正1452、相对Q变化17614、canonical分布变化8786；3278829零CF仍不可测。
  16,204个全主S零context仍有相对Q变化，7,491个有分布变化；含平局/社会次级，不等于模型学习信号。
  原三人33局只有12个正own S；H2/A2H2及结构24保持独立身份，未冻结升级正式100。
  结构24index10的448节点/3答案复核及18次强制动作LP匹配；只限固定reference，不证明所有平局/跨均衡稳健。
  见`examples/strategic_slices/QS_ACTION_PROFILE_REVIEW_20261104.md`与三个独立快照/实际pipeline_snapshot。
  不按新描述直接挑800，不混用旧D；prompt、response评分对齐及正式来源/去重/覆盖仍待审查，生产active v8。

- 2026-11-04用户再次明确：制作合适父游戏允许依据结构/Oracle标签迭代保留、淘汰、重抽和补充，
  不沿用“首批100必须不变”的限制；每批身份、接受/拒绝/失败与替换关系留痕，不把失败当低S。
  800包含训练候选与验证；测试来自最终100父游戏之外的新父游戏，不占800。最终100训练slice仅由训练候选D选择。
  train/validation数量及是否按父隔离、测试规模未定，不能默认旧504/96/200或800全训练。
  Q/S具体公式/门槛/配额在观察候选父标签后再讨论；场景覆盖方向基本认可，不等于固定比例获准。
  新设计记录`examples/strategic_slices/versions/slice800_design_v1_20261104/DESIGN.md`给出相对行动价值、
  分布效用加权及regret/TV关系；不是已激活指标、数据生成或selection，生产仍v8。

- 2026-11-04用户同意继续统一候选父标签：H2/A2H2/结构24共90已整批尝试版本，83已有reference全部补齐profile，
  7缺失保留；H3原33未整批求解，不混入。原100新版99独立复用、25未解决。
  完整Q复用hash核对旧标签；同一保存reference逐条重放全部旧S/遗漏策略，均匹配；249个实际裁剪forest与
  不裁剪原生展开的全部root行动Q/策略一致。仅裁固定对手下严格零CF分支，所有可到达自身动作保留；
  继承原认证/重载证据，未新做均衡搜索或全树认证。v1零计数字段失败保留，v2修计数，v3仅child缓存；
  三题v2/v3解压labels逐字节相同。pilot workers2、remaining workers4均线程1，实际snapshot/CLI完整留痕。
  H2/A2H2/结构池正own S49/636/114，正父9/31、10/30、14/22；相对Q变化12710/23170/12623。
  辅助私人组LB=sum(w maxQ)-max(sum(wQ))，当前后恢复完整信息的放松问题；逐组核对LB<=当前损失<=全S。
  私人LB正父6/31、7/30、11/22；结构11父来自9种geometry且无公开全want，A2正组约94.8%集中62/78。
  LB非新主S/筛选阈值，仍依赖固定reference/CF权重，不是跨均衡或模型D。结构位置/计分关联仍小样不作因果。
  见`examples/strategic_slices/CANDIDATE_PARENT_LABEL_REVIEW_20261104.md`及独立快照/EVIDENCE；
  目前仅完成标签与重抽方向审阅，未生成新父游戏/正式100/800/测试、未定门槛比例、未测D或训练，active v8。

- 2026-11-04用户提出父池65两人/35三人，替代助手未激活50/50建议，作为制作目标记录。
  60/20/20能力目的配额仍是助手草案（两人40/15/10、三人20/5/10），未最终确认或激活。
  现有两人66可测，40正own S，26zero-own-S均有相对Q变化；26中22有静态/动态报价差异，只是规划待审来源。
  原三人/H2/A2按原index每组计一个，16组有正own S；结构池按pair计11组，共27组可供信息用途审查。
  更窄私人当前LB正来源为12+9=21组；保守分组仅估容量，不合并变体/历史/信念，不宣称已验收。
  先审现有供给，按实际缺口补抽；25仍挑战/缺失。见`examples/strategic_slices/versions/parent_pool_composition_65_35_v1_20261104/DESIGN.md`。
  无新生成/选题/D/训练，active v8，800仍train候选+validation，test在父100之外。

- 2026-11-04用户授权制作合格65/35，不足时新生成/重算后补入；qualified-parent-pool-65-35-v1已完成。
  182份已有可测profile验收，选65两人/35三人，主用途信息/估值/规划40/15/10与20/5/10；现有供给足够，无新生成。
  100canonical/100来源组，90种typed geometry、同种最多3；同原index变体/结构pair各至多一个，不按Q/S大小排名。
  60信息见证独立完整/遗漏LP，所有own最优遗漏策略上的保守S下界均>1e-8；100题见证全部行动终局Q重放通过，200资产hash通过。
  估值入口要求Q非平、单条S零且相对regret变化；规划入口要求调查仍合法但严格次优，15后续机会/5回应取舍见证。
  继承原reference认证/重载，不是新搜索100均衡或跨reference证明；实际62局有正own S，不保证任意入口有模型信号。
  数据new/qualified_parent_pool_65_35_20261104/v1，parents SHA5404947669e4a762ce8914eabd40dcfb060e921aadda0705b75dcfc6057cd3a2。
  原25及其他缺失保留挑战/未测身份；82未选来源有逐项理由。逐题索引及关闭证据见QUALIFIED_PARENT_POOL_65_35_20261104.md。
  仅完成D前父池，800/train-validation/test/prompt/训练仍未接通，D未测；生产active v8不变。旧关闭快照不覆盖。

- 2026-11-04用户同意先做800入口供给表；qualified-parent-entry-supply-v1完成100父全扫描。
  保存1832020行中1305451零CF fallback排除，526569正CF观察context精确去重后无额外重复；不同隐藏world不算多入口。
  正own S1684（私人1083/历史681可交叉），对应405物理骨架；骨架仅诊断集中度，不能合并历史/信念。
  两人正S前两父占46.1%，三人59.8%；1124正S入口仅剩一次本人决策，340保证至少两次、220视未来回应而增加。
  235个调查严格最优候选、189保证至少两次本人决策，但答案因果收益未验，不等同合格信息获取题或新D。
  估值24049/规划1803沿用父池谓词；回应社会遗漏846另列，不混入own S。60指定见证继承LP，不称全部1684新LP认证。
  原生所有合法路径本人决策次数min/max（包括当前proposal/response）已589小子树枚举匹配，非reference期望或模型长度。
  两题pilot库存与整批解压字节相同，526569库存重读/身份/计数通过；新code与每run完整pipeline_snapshot留痕。
  供给报告ENTRY_SUPPLY_AUDIT_20261104.md；优先核验235调查答案收益、保护链条与限制父/骨架集中，再定800配额。
  600训练候选/200验证、80/20父隔离为拟采用划分，成员未定；不自动每父8个或把65/35当800硬比例。
  未选800/分配split/生成test、未改Q/S/solver/prompt/reward/训练，D未测，active v8；旧关闭快照不覆盖。

- 2026-11-04用户授权继续235调查入口核验：strict-query-answer-access-v1完成51父/235入口/全部353合法调查目标。
  同一公开调查/回合额度/reference保留，仅屏蔽该目标后续私人答案；完整收益全匹配旧调查Q，706独立full/blind序列LP一致。
  F=max_query full，B=max_query blind，N=保存最佳非调查Q（允许之后正常调查）。109答案对严格调查优势必需，39有增益但B>N，87无当前答案仍达F。
  109来自25父/50物理骨架、104保证至少两次本人决定；三人16仅来自5父/10骨架，11保证至少两次本人决定。
  A+B共148入口/33父/70骨架，不把剩余B-N全称纯公开信号，也不据C判游戏/调查/全部信息无用。
  strict-query-answer-chain-verification-v1另从原生历史走到首次本人决定，353分支/3522次后继context条件belief匹配，
  full-blind=概率加权既有private S全通过，误差约1e-15；是事前答案访问与已有S的衔接核验，不替换主S或泛化所有历史S。
  200调查分支有正加权private S是分支数，不与148入口混用；109/39/87仅query_gap>0子集，不代表三人仅5父有信息价值。
  方法/CLI/source/CPU workers2与线程1/hash/LP及235逐题索引已留痕，报告QUERY_ANSWER_ACCESS_20261104.md与独立关闭证据。
  下一步按强获取/混合动机/已有信息利用/估值规划/回应确定800覆盖与重复限制；800/split/test未选，D未测，游戏/主Q/S/prompt/reward/训练未改，active v8。

- 2026-11-04用户“继续1”授权确定并制作800覆盖/重复/split；slice800-coverage-selection-v3与slice800-native-export-v1已完成。
  600训练候选/80父（52二人28三人）、200验证/20父（13二人7三人），按父人数×原主要用途各20%留验证；入口/父无交叉。
  主用途总配额A60/B20/正ownS利用320/估值160/规划160/回应own40/social40；各split3:1，非Q/S大小或模型D排名。
  各split三人入口30-40%，实际训练377/223、验证137/63；训练每父≤12、验证≤16，A每父≤6/B≤4/信息利用≤10，同父物理骨架≤3。
  保护100父原主用途见证（60信息见证继承LP），至少25%保证多步；实际255保证≥2次本人决定，357恰1次、188视后续回应增加。
  信息利用320中多步82、私人211/历史112可交叉、仅后续损失42；所有800原生观察ID/动作/答案/条件支持/角色/覆盖通过。
  从526569库存确定性缩减26492proposal候选；全部稀缺获取/正S/规划及见证保留，海量角色按登记hash分层缩减，不称全库存全局最优。
  v1预import语法失败、v2第一阶段364覆盖后np.int64写日志失败保留；v3只修日志并固定v2rank命名空间，三次候选hash一致。
  v3时限解362父×用途/232父×actor，阶段status1/0/1/1，不宣称最大多样性/最优负载；有限时限重跑名单可能不同，实际hash冻结。
  数据new/slice800_candidates_20261104/v1，trainSHA9e327dcdb84d001d21ed9270043d1e1544a155f1bfaf1f335d578ca6aee139ad，
  validationSHA15eb6363da844699ef9c0eeea196f9580d76021495f3fb0f331a7389d496b5a8；manifest866070bc90f322a10fa849c2b7049bf6509f7efcb6859b6f5da84064e3807841。
  model_facts与oracle_annotation分开，后者posterior/隐藏world/Q/S不得进入模型；条件world不重置父先验，完整终局focal控制合同尚未接入训练。
  typed geometry有3类跨split共享，不称family隔离；40social回应需正式D前接通protocol评分/prompt，own-only不能表达该差异。
  报告SLICE800_COVERAGE_SELECTION_20261104.md与800索引/父split/完整snapshot/独立关闭证据保留；最终prompt/D/最终100训练slice/测试/训练未做，active v8不变。

- 2026-11-05用户授权先修改prompt与回应评分，并明确保留9月短system＋user＋具名tools。
  native800-prompt-score-v2已实现新800专用request/decode/score接口（examples/strategic_slices/native800/decision_v2.py），旧v8生产文件不改、注册门禁通过。
  system逐字保留9月D；各phase完整规则/目标/公开与本人私有事实/先验/历史/生效承诺/顺序/调查与offer额度，pending不混作已生效。
  说明OFFER提出即扣额度不退、调查消耗proposal且只查非public/本人未直接查过的他人偏好；不按推断删目标。
  原公共树不保存实际答案，request克隆actor视图按本人直接调查slot重建累计真实答案；不显示对手私答/推断真相/来源标签，不加assistant解释memory。
  全体仅response自身预期终局Q平局时favor其他玩家总收益，不扩展proposal，也不声称保存reference剩余平局均匀。
  评分沿用同续接Q/Q_others：节点统一选轴，proposal和非平局response用own负regret，own-tied两响应才用others-sum负regret；不加权牺牲own。
  正确集合用既有helper/profile的1e-9（旧v8正确性1e-7保留历史身份），无效/截断当前轴最差reward另-0.2，GRPO组内sample-std不改，主ownQ/S不改。
  v1完整CPU通过，v2仅单复数文案、scorer-v1不改；两次快照/完整实际request均保留。800/5493合法调用/3044world对照通过（含原world800，额外不同world2244）。
  42响应入口正确集合相对own-optimal纠正，含40social题；40构造合法组均给原GRPO正负advantage，不代表真实模型训练有信号。
  原两人1局CPU三本人决策轨迹证实调查Blair/Library答案在后续proposal与response仍披露；非模型采样分布/效果验证。
  完整预览versions/native800_prompt_score_v2_20261105/PROMPT_PREVIEW.md，原始JSON无Q/S/后验，预览的评分小节仅供人审不进模型。
  DATA_BINDING.json显式关联800manifest866070...与prompt-v2/response-lex-score-v1，不覆盖原800导出pending字段或历史D。
  own terminalD与protocol/social指标需分列，不能用ownD单独评价social题；没有激活混合D排名。
  新800request/score适配器已完成，但完整D runner/训练collector/SP臂未迁移，未GPU/模型D/训练，旧active仍v8；见NATIVE800_PROMPT_SCORE_20261105.md和v2关闭证据。

- 2026-11-05用户8点题面审阅后native800-prompt-score-v3完成：保留9月短system/user/namedtools，scoring-v1逐字不改。
  删“A preference you inferred...”与“OFFER takes...”整个参数重复段；schema/实际合法动作/decoder不改，不按推断删调查目标。
  Response用“favours the other players more overall (a higher total expected final score for them)”保留复数/总收益，避免三人局单一other player歧义。
  新CURRENT GOAL STATUS逐goal列各玩家met/required、共享completion、missing承诺；只当前已接受状态，不含pending/预期Q/推断偏好。
  新表=f(publicrules,currentcommitments)，两者原S所有遗漏条件始终保留，所以非新可消融S信息项，不重算Q/S；可能改变模型D，须绑定新题面测量。
  CURRENT COMMITMENTS重命名旧ALREADY ACCEPTED；历史直接编号actor行动，去Observed标记，但历史动作/回应/参数/承诺before-after表完整保留，不擅自删影响历史S口径的物理快照。
  保留精确binary/linear/want+1/neutral0/avoid-1与expected finalscore，不强制输出数值/枚举终局；起始独立均匀先验压短但不删。
  800目标完成度与原生环境一致、2046单事件历史删除与每节点私有结果清空时目标表不变；800/5493tool/3044同信息world（额外2244）及既有评分单测通过。
  实际预览versions/native800_prompt_score_v3_20261105/PROMPT_PREVIEW.md、DATA_BINDING显式绑定800及prompt-v3/scorer-v1；v1/v2和历史D保持身份。
  逐项解释PROMPT_REVIEW_NATIVE800_20261105.md；完整D/collector未迁移、未模型/GPU/D/训练，旧active v8不变。

- 2026-11-05用户完整题面草案后native800-prompt-score-v4：共同规则system＋具体状态user＋原具名tools，最新草案覆盖此前短system偏好；用户明确只改表达，response自身平局时比较others-sum不变，proposal不扩展合作。
  目标完整要求与当前状态合表，required commitment逐项标committed/missing＋共享completion；pending不计入。当前100行动均被目标覆盖，未用行动提供状态fallback，不丢当前物理状态。
  一笔offer＋response合一条，pending仅not-yet-binding，解决后替换回应及生效结果；原机会编号保留。删历史冗余物理表后，2046单事件遗漏中其余历史before/after可从完整当前状态/其余accepted NEW additions/缺口编号恢复；只对主S逐条遗漏，不推广联合多条历史诊断。
  800/5493工具评分/3044同信息world（2244不同world）和7评分测试通过，三本人决策累计答案持续；工具逐项等于v3，scorer-v1/主Q/S/GRPO及800身份不改。
  首轮CPU适配失败因PrivateQueryEvent.action仅存在于序列化，失败snapshot/source保留cpu_v4；使用to_dict字段后cpu_v4_attempt2全量通过，无模型/求解效果结论。
  用户手工修改v3预览首例保留，旧实际v3请求以cpu_v3/previews和原EVIDENCE为准；不把手稿称旧实际请求。新预览versions/native800_prompt_score_v4_20261105/PROMPT_PREVIEW.md与独立EVIDENCE，详见PROMPT_USER_LAYOUT_REVIEW_20261105.md。
  新prompt需重新测D，尚未模型/GPU/D/训练，完整D/collector/SP未迁移，旧active v8不变。

- 2026-11-05用户授权接入新800远端D runner，明确不做验证。native800-terminal-D-v1仅实现并打包，未CPU单测/语法验证/mock/GPU smoke/模型执行，不能继承prompt-v4检查当runner验证。
  新run_native800_d(.py/.sh)独立于旧入口；使用v4原prompt/scorer-v1、冻结800和65/35父reference，不改主Q/S/GRPO/旧active。
  每题8独立条件posterior world draws，focal每次决定到原生终局，对手reference；非旧k=1/2/3。父内32 completion-refill，父间顺序以限制reference内存，不声称跨父满载。
  每个决策完整状态/历史/本人调查答案重建，无Oracle入prompt。入口scorer输出own/protocol分列；后续节点仅合法性记录，不新求Q/S，非训练collector。
  own D=max入口ownQ-实际终局均值，不截零；任一未完成则D=null并保留缺失界/完成样本估计。非法/截断不自动重试；HTTP/环境失败停机留证，不记为模型零分。
  每完成replica原子gzip保存；strict source/model/config/endpoint/data resume；未完replica同seed重来。运行/attempt完整pipeline_snapshot写实际CLI、环境、模型/input/source身份。
  远端通用单GPU/外部endpoint和Slurm入口，无个人conda路径、无下载/安装/自动提交；模型路径必须用户指定。完整说明NATIVE800_D_REMOTE_20261105.md。
  transfer包new/native800_d_remote_20261105/native800-D-v1.tar.gz约8.2MB/748文件，SHA119361cee325789484f263563e5b4e77f3d9fa790574b06558490695fdd0721a；含源码/冻结入口/reference/native job，不含模型/完整profiles/旧日志。
  实现快照versions/native800_d_runner_v1_20261105/SNAPSHOT.json与独立EVIDENCE标未验证；打包有独立pipeline_snapshot，不是D测量。尚未远端实际执行、最终100未选，训练collector/SP训练未迁移。
