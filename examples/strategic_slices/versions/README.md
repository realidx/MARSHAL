# Pipeline版本记录

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
