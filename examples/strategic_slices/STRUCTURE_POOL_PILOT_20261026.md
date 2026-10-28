# 三人结构覆盖候选生成 v1

本版将62/78结构诊断转成一个独立、先冻结再求解的小批候选试验。用户已同意沿这个方向推进；
没有替换原100、原33配对研究或生产v8，没有激活新prompt、reward、GRPO或训练。正式100的生成比例仍未定。

## 生成规则与动机

保留三人、2RR、3/4目标、行动数[1,1,2]、两处隐藏偏好分属不同玩家、每人调查1/报价1。
调查仍消耗回合；报价提出立即扣额度；每方每报价最多新增1项承诺，承诺可累计。
只在ACCEPT/REJECT自身预期最终效用相同时，最大化其他玩家预期最终效用总和。
全部偏好依然独立均匀抽取want/neutral/avoid；不指定全want受益者，也不因抽到不理想偏好而重抽。

12个几何/计分层，每层一对，共24个原始候选：

| 维度 | 小批覆盖 | 用途 |
|---|---|---|
| 目标数 | 3、4 | 保留现有规模 |
| 双行动玩家与目标的关系 | split：两项行动分别连接不同目标，且不同时被单个目标要求；bundled：至少一个目标同时要求两项行动 | 检查不同合同内容与共享承诺，不仅重复新增行动数 |
| 计分模式 | 全binary、混合、全linear，各占1/3 | 同时保留阈值互补与线性对照；**这是试验覆盖比例，改变了原逐目标独立50/50分布，并非正式题库默认值** |
| 配对隐藏位置 | uniform：不同玩家的全部两格组合均匀抽；shared_goal：同一目标的两位必需行动贡献者，各隐藏该目标偏好 | 检验隐藏偏好落在合作回应链上的效果 |

目标从全部合规要求集合中均匀抽取：每目标2/3项行动、涉及至少2玩家；要求集合不重复；四项行动全部被使用。
先按结构选择目标和隐藏位置，再由独立随机流抽偏好；同一对共享目标、计分、完整底层偏好抽样和行动顺序。
两臂仅改变哪些格子隐藏。未隐藏格子的偏好相同；隐藏格子仍展开全部三种值，形成9个等概率world。
这不是强制两个玩家具有相关偏好，独立先验不变。

shared_goal只是可检验的结构假设，**不保证**最优合同会随答案改变或S为正。
uniform也不是保证零S的标签。全部候选、零S、失败和不可测值保留，禁止按Q/S回填或换种子。
两臂信息结构不同，需要分别求reference；配对差异不能冒充“固定同一对手策略，只消去答案”的因果效应。

固定种子为202610260000+pair_id，使用五个独立SeedSequence随机流。
全部24个候选在求解前冻结；先预定前六个：G3、split的三种计分各一对，不能依据生成内容或求解结果改顺序。
这是运行和方向检查，样本量不足以认定生成方法提高了S。

## 代码与实际数据

- [生成/运行入口](../../new/structure_pool_20261026.py)
- [冻结方法及480项source hash](versions/structure_pool_v1_20261026/SNAPSHOT.json)
- [24个候选](../../new/structure_pool_v1_20261026/raw_v1/parents.jsonl)
- [生成与验证manifest](../../new/structure_pool_v1_20261026/raw_v1/manifest.json)
- [生成pipeline_snapshot](../../new/structure_pool_v1_20261026/raw_v1/pipeline_snapshot.json)
- [本地六例实际pipeline_snapshot](../../new/structure_pool_v1_20261026/local_pilot_v1/pipeline_snapshot.json)

题库SHA256：`b47f0568febbfc49aac7cf2e6977997338f95eb7376b990a452faa92ee589ba3`。
24个canonical身份均不同；配对重建一致；每题9world、独立均匀先验验证通过。
公共历史数480795–522424，未超过既有A2H2数量级。没有通过缩短终局、删信息或改变合法行动降低复杂度。

## 执行与验收

原生terminal求解器、数值认证、主own Q/S沿用three-player-complexity-study-v1。
主S仍是允许信息的逐条遗漏、完整后续策略到terminal的own效用损失；零counterfactual为不可测，社会平局诊断单列。
新D和训练信号没有测量。

本地六例：workers2、内存限制0（macOS不施加RLIMIT_AS）、建树180秒、候选120秒、认证180秒、Q/S300秒、硬限900秒。
其余沿旧默认：max_nodes600000、inertia_then_joint（75%/25%）、512 sweeps、400 joint evaluations、8 repair passes、epsilon1e-8。
环境在数值库导入前设置五项线程变量为1；实际底层线程池数量未单独测量。CPU验证不等于GPU/训练效果验证。
每次运行记录完整CLI、resolved config、source/input身份；没有沿用旧pool成员身份，新候选original_index=null。

```bash
/opt/anaconda3/bin/python -u -m new.structure_pool_20261026 run \
  --jobs new/structure_pool_v1_20261026/raw_v1/parents.jsonl \
  --output new/structure_pool_v1_20261026/local_pilot_v1 \
  --indices 0,1,2,3,4,5 --workers 2 --memory-gb 0 \
  --solve-seconds 120 --audit-seconds 180 --metric-seconds 300 --case-seconds 900
```

相同配置恢复需在原命令附加`--resume`。失败已经有result，不会因resume自动重试；重试必须新建output并留档。
远端可使用同一入口、24条候选全部`--indices all`，自行设置workers与memory-gb，并使用新的output。
不根据机器规格推测可承受并发。旧版本完整source约束仍强制校验，不能复制单个入口文件后假定依赖齐全。

## 首次六例结果

首次六例已全部尝试，五例原生terminal数值认证并测量，index4在线性对照求解时抛出预算异常，仍为未测。
原始失败记录保留在local_pilot_v1；另开local_retry4_v1，将候选预算120→600秒、硬限900→1800秒，其余算法与参数不变。
local_reload_v1独立重建并重新检查首次五个已保存reference；与单worker重试重叠时共2个CPU worker。

| pair / 计分 | 隐藏位置 | 可测CF context | 私人答案正S状态 | 历史正S状态 | reference路径私人正S |
|---|---|---:|---:|---:|---:|
| 0 / binary | uniform，index0 | 991 | 0 | 0 | 0 |
| 0 / binary | shared_goal，index1 | 474 | 1 | 0 | 1 |
| 1 / mixed | uniform，index2 | 7493 | 3 | 0 | 0 |
| 1 / mixed | shared_goal，index3 | 484 | 0 | 0 | 0 |
| 2 / linear | uniform，index4 | 首次未测 | 首次未测 | 首次未测 | 首次未测 |
| 2 / linear | shared_goal，index5 | 3979 | 2 | 0 | 2 |

此表是首次运行原貌；重试成功则单列，不能覆盖失败身份。
index4的600秒预算重试仍为`candidate_unavailable`：惯性BR出现循环，joint候选未满足原生局部最优检查。
某些joint优化器残差很小，仍有1/6或更大的实际局部获益；不能把数值优化器成功当作均衡认证。
本次重试约119秒就返回，没有耗完600秒；因此不宣称仅更换更快服务器或增加wall time就一定解决。
它仍保留为缺标签候选，未按0信号、无效游戏或低价值题替换。
已测的6个正S见证均在proposal，且当前行动regret也为正；不是只有response社会平局标签。
三份正S父游戏均没有公开全want玩家，表明新样例不依赖强制这种角色；不证明哪种生成层普遍有效。
例如index1节点360023：保留自己调查得到的P0/G2=want时，最优预期自身终局收益2；遗漏后选定报价收益1，S=1。
该例在reference有正质量，其他公开/基础信息仍保留。单个例子不证明调查动作本身严格优于直接报价。
主指标的局部重放核对已由原测量实现完成；新池尚未额外做独立LP或跨reference鲁棒性认证。

**目前不能宣称新隐藏位置规则改善了信号稀疏。** binary与mixed配对方向相反；两臂可测context分母也不同，
不能只拿状态总数作强弱结论。保留零S结果符合不按高S重抽的设计目标，也说明几何/隐藏落点不能保证S。
零S不能直接等同“调查动作不必要”：index0存在调查Q严格高于非调查的入口，但测到的当前答案遗漏S均为0；
公开行动/后续分支效果与私人答案价值仍须区分，本轮未重做该入口的答案屏蔽渠道试验。
剩余18个候选尚未尝试；G4与bundled目前只有生成/先验/计数验证，不能宣称已完成求解或效果检验。
Q/S仍相对于各自获认证reference，D未测，正式100与训练均不据此替换。
旧生产v8的own-only动作评分与response社会平局协议之间的缺口，也没有由本生成器修复。

## 本轮关闭记录

首次五个已认证reference，**5/5保存后独立重载通过**，没有重新搜索或替换reference。
见[复核完成记录](../../new/structure_pool_v1_20261026/local_reload_v1/COMPLETE.json)。
index4的[独立重试](../../new/structure_pool_v1_20261026/local_retry4_v1/COMPLETE.json)仍缺标签。
已运行六题中，五题可测、三题正S，共6个私人答案正S状态，均有当前proposal收益损失；其余18题未运行。
480项source与冻结题库hash核对通过，`git diff --check`通过。
最终证据与本报告身份见[EVIDENCE.json](versions/structure_pool_v1_20261026/EVIDENCE.json)。

本轮完成的是候选生成及预定小批可运行性验证；没有证明新分布提高S覆盖或模型学习效果。
在补全候选审计、确定最终生成分布和新prompt并测D前，不将本批直接升级为正式100或开始新训练。
