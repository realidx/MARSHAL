# v8：按逐段审阅简化题面，保留实际信息与评分合同

日期：2026-10-18。父版本 `terminal-node-regret-grpo-named-v7`；新pipeline `terminal-node-regret-grpo-readable-v8`，prompt `terminal-readable-named-v2`。

用户要求逐段检查v7，并明确“保留自己的调查答案，去掉额外来源提示”。本版只调整题面呈现和版本身份。原v7快照/完整预览不覆盖，另保留其renderer，CPU检查可重现原4份完整request。

| 修改 | v7 | v8 |
|---|---|---|
| BINARY/LINEAR与效用公式 | 分散在规则与DECISION OBJECTIVE | 集中GAME RULES，含线性1/2例子，后接目标要求表 |
| 目标列名 | 玩家名 | “玩家的required commitments”；说明不是偏好 |
| COMMITMENT OPTIONS | 独立列表和上限说明 | 压成目标表后一行，新增上限并入规则 |
| 已知偏好 | 混合来源列，public/own/investigation标签叠加 | 公开事实/当前私有事实分表；不添加来源或谁知道什么的标签 |
| 调查信息 | 直接答案+来源提示 | 自己的真实答案保留，重复公开事实去重；调查者/目标在历史，删送达提示 |
| support | 枚举全部允许偏好行 | 在全100父游戏通过独立性核验后删除，用固定事实+独立背景概率等价表达；有联合限制则报错 |
| 背景概率 | 产品权重/归一化 | 直观百分比；等概率写1/3，保留原分布 |
| 当前状态 | CURRENT BINDING STATE | COMMITMENTS ALREADY IN FORCE，与pending offer分清 |
| 控制窗口 | YOUR CONTROL WINDOW，certified/native术语 | DECISIONS IN THIS EXERCISE，普通语言解释次数/接管/整局终局计分 |
| 重复目标块 | DECISION OBJECTIVE | 删除独立块，目标合并到YOUR TASK/GAME RULES |
| system/tools | 9月system/具名行动 | 完全相同，376个实际context逐项比较 |
| 历史兼容 | v7 renderer | 保留为named_prompt_v7；版本路由支持v7/旧JSON；独立审核区分两种named题面 |
| 版本与最终测试 | v7 /terminal-final-test-v4-named | v8 /terminal-final-test-v5-readable；禁止旧checkpoint混续 |
| 冻结工具 | parent/目录处理只覆盖首版流程 | 可指定新目录；parent默认原active版本，拒绝覆盖旧记录 |

**不变项：**Qwen3-4B-Instruct-2507，seed42；同一selected-v4的100训练题、96验证题、200测试题；data联合身份 `6080bc30f1a70b995bb9d7bfcdc3ed633bd0ff64bfd759691cf758f4533c4379`；同一初态完整终局reference与窗口k=1/2/3；Q−maxQ连续reward、失败minQ−maxQ和独立−.2、节点内sample-std advantage；节点/回答等权、token均值；20节点组×8采样，均匀预选原始样本推进；并发32完成即补位；context16384/response1024，train temp1、eval greedy；6M训练tokens；500K验证/1M恢复保存；clip.2、KL.01、LR1e-6→1e-7；原缓存和best/final-test规则。全部CLI默认/profile/YAML/source/hash见SNAPSHOT。

**核验：**[全100父游戏概率核验](prior_equivalence.json)含1344个world，概率最大差异0；[376个实际上下文迁移](native_interface_migration.json)含2045动作、53个私有调查context，事实集合/system/tools完全一致，错配0；[CPU测试](cpu_tests.txt)覆盖旧v7完整重放、新偏好信息/先验限制和全部相关采样/训练/评测/版本门禁。

**状态/限制：**CPU已检查，尚未GPU采样/训练、未提交任务；不要求独立GPU smoke。旧D保留旧prompt身份，未重测或重选；本次没有探索改造、解释奖励、GRPO变体或SP训练臂补齐。新窗口文字仍反映原接管合同，不代表已经向模型提供完整参考策略概率。不能将CPU检查写成解释持续性、训练效果或收敛证据。

完整问答与设计说明：[PROMPT_REVIEW_20261018.md](../../PROMPT_REVIEW_20261018.md)。完整当前输入：[PROMPT_PREVIEW](PROMPT_PREVIEW.md)。
