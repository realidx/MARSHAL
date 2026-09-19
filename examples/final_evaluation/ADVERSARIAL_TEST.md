# 对抗测试：固定伙伴下的 BENAC 完整局评估

状态：v2 场景、调度和本地验证已接通；尚未运行 GPU 模型。训练剂量/checkpoint 仍由正式提交清单记录。
历史代码入口 `benac_a*` 保留兼容，论文统一称“对抗测试”。这里的对抗是 general-sum 策略交互，不意味着零和、恶意伙伴或攻击鲁棒性。

## 可直接用于外部审查的设计摘要

**问题**：只替换一个玩家时，训练是否改善该玩家在固定伙伴策略下的表现？这种改善能否延伸到未见目标—承诺依赖结构？

- 比较 Q0、B/P-only、SP-only，配置为 `[M,Q0,Q0]`。所有条件复用同一个冻结 Q0 checkpoint、提示和推理设置。伙伴策略固定，但其回应和错误可能随历史改变，不声称伙伴动作序列固定。
- 16 个新初始局：8 ID、8 OOD。按 binary/linear × 2/4 轮 × balanced/avoid-heavy 先验分层，每个组合一对 ID/OOD，匹配玩家数、目标数、承诺数、轮数和公开生成规则。各局三人、每人两个承诺、三个目标；不包含 mixed 目标完成规则。
- ID 使用训练中已见依赖结构的新偏好世界；OOD 在忽略命名、效用模式和时序后，与本轮所有 B/P/SP 训练及验证来源非同构。另排除旧 A 的 OOD 结构，避免重复使用已分析的确认性证据。记录实际独立结构数，不把 ID/OOD 对称分层称为单因素因果控制。
- 每个初始局轮换三个被测座位。每个场景—座位运行三个预定 sampling seeds：每模型 144 局，若全 Q0 的 focal 标记仅用于评分，则 Q0 只跑 48 条轨迹、导出 144 条评分记录，总计 336 条实际轨迹；复用检查未通过则仍为 432 局。三个模型使用匹配种子；相同种子不保证分叉历史后的生成噪声相同。场景是冻结实例，sampling seeds 只检查行为稳定性。
- 解码沿用旧 A：temperature=1、top_p=1、每次输出 1024 tokens、一次重试。所有模型使用相同工具与上下文预算；运行前核实实际模型模板和 thinking 配置，保留请求、响应、finish_reason、token 使用和模型文件哈希。
- 主要收益量为被测玩家自身原生终局 utility。并列报告终局完成率、全样本收益上下界、总 utility、三名玩家各自 utility、无效行动和截断。binary/linear、ID/OOD 分开。不得以社会福利代替自身收益，也不得将本任务描述为零和。
- 未完成局不填正常零收益。完成局均值与配对双完成差值均明确标为条件统计；报告双方完成/仅一方完成/双方未完成计数。用每个实例合法自身效用上下界给出缺失结果的保守界限；界限不能区分时不强行排名。基础设施错误单列，原样重跑相同任务，不换实例。
- 对所有失败尝试分别统计格式、状态/动作有效性、截断，并区分 focal/Q0。记录最终中止玩家；这是直接中止归属，不是导致失败的完整因果归因。Q0 失败仍属于完整系统结果，不能删掉后仅报“无对手错误子集”。
- 比较以匹配 case—seat—seed 的记录为基础，先在同一场景内汇总座位和重复；不能把 144 局当成 144 个独立结构。报告逐场景差值、结构家族汇总与覆盖数；不依赖小样本显著性作结论。
- 主结果使用预先固定训练剂量的最后 checkpoint；内部 validation 用于监测。validation 最佳 checkpoint 若另报，须单列评分公式、候选范围和并列处理，不与主结果混合；不根据旧/新 A 或 CalBench 选择。记录实际训练 completion tokens、updates 和训练数据版本；预算不匹配时不宣称相同计算预算下的效率优势。

## Teacher 范围

本轮主测试不加入 teacher 对手。相同可见信息 selected-policy teacher 的完整局范围与 off-path 行为约定尚未验证。未来可以独立补充已认证小局条件，但不能冒充全知 oracle 或与 Q0 条件混成单一排名。

## 与历史测试的关系

旧 `benac_a_v1`：16 初始局 × 3 座位 × 1 rollout = 48 局/模型；ID 3 种几何，OOD 8 种。已用于问题诊断和数据改进，归为开发证据。

2026-09-19 对 `data_reasoning_v5_candidate` 的 B/P/SP train/validation 重新检查，旧 8 个 OOD 依赖结构仍均无匹配。但这不恢复旧结果作为未使用确认性测试的身份。

场景已针对 data_reasoning_v5_candidate 的实际文件散列冻结；训练数据变化后必须重新审查，不能沿用 OOD 声明。模型选择规则与剂量另记入提交清单。只按上述结构标准选取，不按模型表现、最终 utility 或 teacher 能否求解选取。SoC 提交脚本默认运行 v2；设置 BENAC_A_PROTOCOL=v1 可显式使用历史入口。v2 正式运行使用三次采样。

## 实现约束补充

- 真实训练臂保持 B/P-only 与 SP-only，不用 B/P-only 代表 Mixed。训练剂量数值需在正式提交清单中落实；当前未填写具体 token 数，因此尚不可声称主运行清单已冻结。
- OOD 图保留玩家、承诺、目标的节点类型以及玩家—拥有→承诺关系。现有 geometry_id 允许玩家与各玩家内部动作重命名，保留所有权。生成时还须有跨玩家依赖，并保存至少两条合法续局、不同 focal utility 的见证；仅非同构不够。
- 缺失收益用最后合法承诺前缀收紧。`adversarial_checks.prefix_bounds` 枚举所有与既有绑定相容的状态，允许 avoid 目标带来的后续损失。它忽略剩余时序/提案可达性，是保守相容状态界限，不是精确可达界限、置信区间或 LLM 续局预测。
- 配对差界限为 [L_model−H_Q0, H_model−L_Q0]；已完成局 L=H=实际收益。
- Q0 复用前须核验模型文件、模板、端点配置、初态、请求和随机数流相同。现有 Episode seed 不含 focal_seat，但路由仍须核对；不能仅凭模型名字相同判定可复用。共享轨迹的三个评分记录不独立。
- 上述界限函数已实现并测试；新 v2 生成器、合法续局见证、Q0 共享轨迹调度均已接入并通过 CPU 测试。旧 v1 行为与历史分数未改写。

## 已接通的运行入口

冻结目录：`examples/final_evaluation/adversarial_v2`。包含 16 个 reset、候选排除记录、96 条原生终局见证和源文件散列。生成发现旧的每目标每玩家最多一个承诺的采样空间不足以提供八个排除旧测试后的独立结构，因此 OOD 使用原生规则允许的 2/3/4 承诺依赖，可包含同一玩家的两个承诺；人数、承诺总数、目标数和时序不变。这项依赖结构分布变化必须在论文披露。

Q0 参数是同一个实际模型目录时，launcher 核对文件散列并将两个角色统一路由到 q0 服务，正式运行48条共享轨迹。其他模型运行144条轨迹。smoke 只用一条已有开发 reset，不提前跑正式题。启动仍使用两卡，现有 SoC 环境不变。

用户在 SoC 仓库根目录执行（先同步代码和冻结目录）：

```bash
# 独立开发局验通
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 q0 q0-v2 smoke
# 正式运行
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 q0 q0-v2 formal
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 /absolute/BP/HF/checkpoint bp-v2 formal
bash examples/final_evaluation/submit_benac_a_soc.sh h100-96 /absolute/SP/HF/checkpoint sp-v2 formal
```

产物沿用 runs/benac_a_soc/，每个作业 games/ 下保存 protocol.json、games.jsonl、summary.json、逐轨迹 calls.jsonl 和 results.json。Q0 共享记录含共同 trajectory_id。基础设施异常停止接纳后续批次，已记录结果保留；不自动换题。

```bash
python -m unittest examples.final_evaluation.test_adversarial_v2 -v
python -c 'from examples.final_evaluation.adversarial_suite import load; m,r=load(); print(m["version"],len(r))'
```

CPU 验证不是 vLLM/SoC 的实际链路结果；尚需上面的 smoke 运行。
