# 800入口候选v1：覆盖、重复限制与父游戏划分

2026-11-04。已按用户“继续1”完成可审查的800候选，600训练候选/200验证，所有800原生状态与覆盖检查通过。
这是测D之前的数据版本，**不是最终100个训练slice，也尚未接通正式模型prompt、回应评分或训练**。

## 场景配额及实际结果

| 主用途 | 训练候选 | 验证 | 合计 |
|---|---:|---:|---:|
| 获取信息A：答案对调查严格优势必需 | 45 | 15 | 60 |
| 获取信息B：答案增益、但无答案仍值得调查 | 15 | 5 | 20 |
| 已有信息利用：逐条own S正 | 240 | 80 | 320 |
| 估值：相对行动价值改变、保留共同最优选择 | 120 | 40 | 160 |
| 规划：回应或后续机会使短视基线选错 | 120 | 40 | 160 |
| 回应：自身行动Q有差异，own S零 | 30 | 10 | 40 |
| 回应：自身Q平局，社会次级选择 | 30 | 10 | 40 |
| **合计** | **600** | **200** | **800** |

400个信息获取/利用、320个估值/规划、80个回应，是本轮覆盖预算，不是理论最优比例或根据模型表现调参。
入口保留全部真实交叉标签与所有逐条S，只指定一个主用途计入上表；A/B沿用353分支答案访问核验。
C类不计为答案必需/混合获取信息，但如有其他已核验价值仍可通过相应用途进入。
不以最大Q跨度、S数值、canonical分布距离或reference频率排序难度，最终模型相关性留给D。

## 去哪里看名单

- [800逐题索引：split、来源、主用途、actor、阶段与窗口](../../new/slice800_candidates_20261104/v1/ENTRY_INDEX.md)。
- [100父游戏划分、逐父数量与角色分配](SLICE800_PARENT_SPLIT_20261104.md)。
- [600训练候选JSONL](../../new/slice800_candidates_20261104/v1/train.jsonl)、[200验证JSONL](../../new/slice800_candidates_20261104/v1/validation.jsonl)。
- [完整汇总](../../new/slice800_candidates_20261104/v1/SUMMARY.json)、[manifest与文件hash](../../new/slice800_candidates_20261104/v1/MANIFEST.json)。

JSONL把`model_facts`与`oracle_annotation`分开：前者为实际原生可见事实、自身偏好/累计调查答案、公开历史和合法行动；
后者为完整行动Q、逐条S、条件world支持和posterior，仅供Oracle与运行时采样，不得送入模型。
原raw的ego示例偏好没有当作当前focal真实偏好。这里尚不是最终system/user/tools请求。
profile/reference继承原冻结父池hash依赖，不重复复制大型文件；移动数据时需保留manifest所记父池资产。

## 划分与重复控制

父游戏按人数×原主要用途六层，各20%留验证：训练80父（两人52/三人28），验证20父（13/7）。
父游戏和入口重叠均0；目标结构typed geometry仍有3类跨split共享，**不宣称family完全隔离**。
Oracle结构覆盖参与设计；没有模型D或目标模型验证成绩参与划分，所得是覆盖设计分布，不冒充原生成分布的无偏样本。

实际训练入口两人377/三人223，验证137/63，总计514/286。父65/35没有机械变成入口配额；
本轮单独要求各split三人入口占30–40%，实际分别37.2%和31.5%。

- 训练每父上限12、验证每父16；实际分别1–12、2–16，并未强制每父8题。
- 同父物理骨架最多3入口，全部满足；这只是重复密度控制，未合并不同历史/信念/私人答案。
- 每父A最多6、B最多4、信息利用最多10；没有因为某局拥有几百个正S历史就大量重复加入。
- 全部100父的原主要用途见证保留，其中60个信息见证继承独立LP保守正下界。

## 剩余窗口与信息渠道

当前玩家从入口控制到原生终局；对手沿用同一保存reference。条件world应从该入口posterior采样，不能独立重置为父先验。
本人决策次数包含proposal及被要求的response，计当前入口；范围是所有合法路径，不是模型实际输出turn数。

| 实际窗口覆盖 | 训练候选 | 验证 | 合计 |
|---|---:|---:|---:|
| 保证至少两次本人决定 | 182 | 73 | **255** |
| 恰好一次本人决定 | 266 | 91 | **357** |
| 至少一次，后续被报价时可能更多 | 152 | 36 | **188** |

各split保证多步入口比例至少25%。单次本人决定也可能需要预测他人回应，继续保留关键报价和回应题。
320个信息利用入口中，82个保证多步，私人渠道211个、公共历史渠道112个（可交叉），42个仅后续策略受损、当前动作损失为零。
因此没有把已有S全部缩成最后一步动作错误；也没有假设800都是三turn轨迹或沿用旧k=1/2/3比例。

## 验证与优化的实际范围

从526569个信息context建立26492个proposal shortlist。全部稀缺信息获取、正S、规划及100父见证保留；
海量估值/回应在相同约束标签的物理bin先取hash最小3条，再每父/role/长度band取hash最小64条。
后一缩减是明确的候选抽样，不声称在全526569库存上全局最优。

时限MILP选出的名单满足全部硬配额、重复、渠道、窗口与split约束，覆盖362个父×用途、232个父×actor组合。
v3四阶段status分别1/0/1/1：父×用途、负载、hash阶段达到时限，只父×actor阶段在固定前阶段覆盖下证明最优。
不能把当前362或最终名单称为全局最大多样性/最优均衡负载；seed和hash固定也不保证换机器在时限内得到完全相同名单。
当前实际名单、source与hash固定保存，后续重跑产生新run身份。

独立原生导出逐一核对800入口：真实公开历史、承诺/预算/pending、合法菜单、观察ID、自身偏好/累计答案、条件支持、角色谓词和窗口全部通过。
Q/S直接继承hash核对的原profile，reference认证与100旧见证证据保留；没有宣称新求800均衡或新做每入口LP。
40个社会次级回应题自身Q平，需要正式D/训练前把prompt与协议评分接通，否则own-only奖励无法表达该区别；本轮未静默改变reward。

## 版本与执行记录

- 筛选方法实际版本：`slice800-coverage-selection-v3`；导出数据：`slice800-native-export-v1`。
- [覆盖合同v1](versions/slice800_selection_v1_20261104/DESIGN.md)、[v2语法修复](versions/slice800_selection_v2_20261104/DESIGN.md)、[v3日志修复](versions/slice800_selection_v3_20261104/DESIGN.md)、[原生导出合同](versions/slice800_native_export_v1_20261104/DESIGN.md)。
- v1在import前语法失败，修复阶段AST/过早启动错误一并[记录](../../new/slice800_selection_20261104_runs/v1_pre_snapshot_failure.json)，未创建数据。
- v2完成候选缩减，优化第一阶段得到364覆盖，但np.int64日志保存失败，[失败运行保留](../../new/slice800_selection_20261104_runs/select_v2/FAILURE.json)。
  v3仅修日志数值转换，并固定v2的rank命名空间；prepare_v2/select_v2/select_v3候选文件字节hash完全相同。
  v3实际时限解为362，不将v2未导出的364解冒充本批结果。
- 实际snapshot：[v2准备](../../new/slice800_selection_20261104_runs/prepare_v2/pipeline_snapshot.json)、[v2失败优化](../../new/slice800_selection_20261104_runs/select_v2/pipeline_snapshot.json)、[v3筛选](../../new/slice800_selection_20261104_runs/select_v3/pipeline_snapshot.json)、[800原生导出](../../new/slice800_candidates_20261104/v1/pipeline_snapshot.json)。
- [优化状态与gap](../../new/slice800_selection_20261104_runs/select_v3/OPTIMIZATION.json)、[关闭验证](../../new/slice800_candidates_20261104/v1/closure_validation.json)、[关闭证据](versions/slice800_native_export_v1_20261104/EVIDENCE.json)。
- `train.jsonl` SHA256：`9e327dcdb84d001d21ed9270043d1e1544a155f1bfaf1f335d578ca6aee139ad`。
- `validation.jsonl` SHA256：`15eb6363da844699ef9c0eeea196f9580d76021495f3fb0f331a7389d496b5a8`。
- manifest SHA256：`866070bc90f322a10fa849c2b7049bf6509f7efcb6859b6f5da84064e3807841`。

筛选CPU worker1、各阶段60s目标时限；导出workers2；数值线程均1。环境、完整CLI与source均在各run snapshot。
生产active仍v8。下一步固定完整可读prompt和回应协议评分，再仅从600训练候选测新D选最终100训练slice；
200验证不进入这次选100。测试来自父100之外，本轮未生成；未调用模型、未测D或启动训练。
