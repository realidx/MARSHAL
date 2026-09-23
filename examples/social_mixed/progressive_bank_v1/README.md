# 从极简原生场景开始的B/O/P候选库

本库是重新定义小型原生场景并重新求解的构造原型，不是给旧题重新分档。不增加辅助题、不给推理中间答案、B不提供正确previous belief、P无历史且只给定性belief。未替换paired_bank_v2，所有任务training_ready=false。

## 已生成

320个决策母题、960个B/O/P视图。train148个、validation172个。只来自两种小型目标几何（目标独立/共享承诺）、binary/linear及自偏好变化等有限组合，不是320种独立结构。

|B证据层|train|validation|
|---|---:|---:|
|真实私有调查结果，直接读取|28|26|
|单次行为后唯一偏好|12|12|
|单次行为后保留不确定性|8|8|
|存在后续决策的行为场景|100|126|

额外标记62个前后窗口：6个update、56个maintain。判断前后分别训练，不喂给模型正确旧belief，不宣称闭环。

P独立标注：known_terminal / uncertain_terminal / known_multistep / uncertain_multistep；不以B证据读取简单来冒充P规划简单。各类数量见summary.json。

## 认证

64个原生求解配置中52个通过，12个发生同步策略迭代循环，全部排除并记录errors.jsonl。不是为凑数强行指定策略。

- 按公开偏好与生成规则重建世界集合，核对没有秘密缩小类型集合。
- 原生合法状态推进、状态转移及终局收益审计；同一原生状态重算B posterior和O动作值。
- 全部B/O标准答案通过实际评分器；所有P请求确认无历史段落或数值joint_distribution。
- P在其定性belief允许的全部支持世界上使用保守的充分条件：positive保证所有混合权重下可接受，negative有一个在所有世界严格占优的动作，其他masked；没有把masked变成负例。判断仍以固定continuation为条件，不能宣称一般的纯planner认证。
- 286个母题的P同时有positive/negative，可用于共同O/D候选核心。common_train.jsonl有136个母题、common_validation.jsonl有150个；每母题三视图同进同出，避免对照混入不同母题。

## 划分与重要限制

整个目标几何留出：separate为train，shared为validation；同一几何的所有prior/history/revelation变体不跨split。因此validation包含结构迁移，不能把其难度简单等同train。原型独立于旧bank，合并前仍须跨旧数据做同源/结构去重检查，不能宣称已经通过全仓泄漏审计。

单次行为唯一识别层的train gold目前全部为want，**这是待补的标签覆盖缺口**，不能直接拿去正式训练，否则存在标签捷径。这里的“不够丰富”仅指新构造原型，不能理解成现有总库没有复杂题。复杂层直接复用paired_bank_v2；合并候选及覆盖核查见../combined_curriculum_v1/README.md，不能宣布旧难题已经可学习。

没有Q0实测，不能证明分层真正在学习上由易到难；目前通过的是原生构造与评分验证。尤其基础B与对应P的难度应分别测量。维护窗口多于更新，不应按关系数量自动设置训练比例。

## 复算与查看

- 生成：`python -m training.social_mixed.build_progressive_bank`
- 测试：`python -m unittest training.social_mixed.test_progressive_bank -q`
- examples.json：四层B真实渲染示例和gold。
- root_audits.jsonl：求解和原生审计。
- manifest.json：当前候选文件与生成器摘要；候选不具备正式训练加载器所需的全部bank认证材料。
