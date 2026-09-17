# 调查决策与结构覆盖 v2

训练入口 `training.social_mixed.core.DATA` 已切换到本包。旧 v1 数据文件保留；继续旧实验需使用其原始代码快照，新包不能接续旧数据 manifest 的 checkpoint。

- 训练题保持 442 道，self-play 配置保持 144/48。不改变工具名、标识符、teacher 策略或奖励。
- 每次 P4 训练更新同时包含 query_only 与 ordinary_only 对照，保留完整对照组，包括已有答案利用和 deadline 题。
- 开发题从 248 增至 301，补 linear/mixed；固定验证采样覆盖包内全部 kernel/mode/information_role 单元。
- 65 道结构隔离测试题，来自已有 test 来源的预选结构，覆盖 binary/linear/mixed。测试不进入训练或日常验证加载器。提供 requests_test.jsonl 供单独评估；请求只含模型输入，不含 teacher 答案。
- 将玩家、每个玩家的承诺、目标的重命名置换后进行精确归并；重复目标保留。背景、偏好世界、完成规则、时序均不能制造新的几何家族。训练/开发/测试分别 31/15/11 个家族，含 self-play，跨集合交集为空。
- candidate_freeze.json 在重求解之前固定来源选择；7 个失败记录在 manifest 与 expansion_progress.jsonl，不以模型结果筛题。来源文件和候选清单有哈希。现有 test 来源的历史使用情况仍需实验记录核对，不能仅凭本次划分声称此前从未评测。

## 监测

`task_signal/<kernel>/<mode>/<role>/<case>` 输出 groups、nonzero_advantage_groups、utility_mixed_groups、correct_samples、samples。B 分 full_support/reduced_support；P 分 query_only/ordinary_only/both。常数零奖励组明确记为无有效任务梯度。

`behavior/...` 同时输出全样本正确率、格式失败率、截断率、INVESTIGATE 调用率。调查调用率下降不能单独视为改善；需同时检查调查正例、deadline/机会成本反例及答案利用。

## 尚未证明

尚未运行远端 rollout 或训练；数据和采样修改不能证明模型行为已改善。调查正例在开发集主要由 linear 变体补入，测试集中有 binary 正例，mixed 正例仍缺失。不能据此声称跨全部规则完成了调查能力覆盖。新增评分变体也不是新增独立几何；结构泛化证据最多按 11 个测试家族解释。独立统计应按家族聚类，不能将所有背景或 rollout 当独立样本。

Teacher 噪声、策略选择敏感性和 OFFER 信息获取本次未修改。

## CPU 检查

```sh
python -m unittest training.social_mixed.test_distribution_contract training.social_mixed.test_core training.social_mixed.test_structure_coverage training.social_mixed.test_source_version
```

生成器 `python -m training.social_mixed.prepare_coverage_v2` 拒绝覆盖既有包。以后扩展请使用新版本，保持测试冻结。
