# Micro24 v2：可区分的B与匹配无B对照

本版是新的候选实验，不覆盖 micro_learning_24_v1，也不启动GPU训练。
目标是在同样O/P学习过程中检验加入这批B更新的增量作用，不是等计算预算比较，也不能代表所有B训练设计。

## 数据

- P8：原24题版的task、冻结request、teacher、评分器原样保留。
- O8：保留 e3126、fdfe1、3a799、1f64e 四题；新增 c119e、5e9d1、c446e、55815 四题。来自原train库，不移动validation。
- B8：不足证据2、排除可能2、多值倾向2、明确揭露2。保留解释后一次tool call。
- B的 c6be、a61c、f893 是旧update接口，**原本就提供正确的previous belief及历史**；本版明确保留这种教学辅助，不能称全体为无辅助raw B。三题新答案均不同于previous belief，不能直接照抄。
- 全部复用真实历史请求，不添加新数值belief，不重写teacher或reward。旧请求本身含公开背景分布；它不是新添加的数值posterior。
- 不能宣称8道B均已证明可学：方向/排除题只有少量正确样本，部分没有上升趋势，属于需要检验的候选。逐题历史曝光、成功率和限制见 REVIEW.md。

O关系以实际评分接受集合为准；已逐一枚举选入O的所有合法动作并调用训练评分器核验。全部O接受集合交集为空，同时保留 must_change 和 same_optimal_set 关系。后者包含不同背景分布的稳健行动，不保证所有关系都是仅改变一条证据的干预。不能把相邻题共同出现等同于闭环训练。

## 两个独立入口

```bash
bash examples/social_mixed/start_micro24_v2_training.sh h100-96
bash examples/social_mixed/start_micro24_v2_no_b_training.sh h100-96
```

沿用原启动器的模型路径、GPU及提交环境设置。两臂必须使用相同Q0 actor/reference和seed，各自新建训练阶段，禁止相互resume；数据身份包含no-B标志。

|设置|D24-v2|OP16-v2（去B）|
|---|---:|---:|
|每更新O/P/B题组|4/4/4|4/4/0|
|每题采样|8|8|
|每更新回答|96|64|
|更新次数|40|40|
|每道题曝光|20|20|
|保存/静态验证|每10步|每10步|
|保留checkpoint|4|4|

每步B含四种操作各1题，两套交替；O/P使用同一题序和逐题seed。无B不补采O/P。只使用现有静态O/B/P验证，不增加CalBench或self-play训练内验证。

### 归一化与学习率

底层loss按回答数取均值。D24每行权重1；OP16的task/protocol/KL每行权重均为2/3，因此共享回答的系数分别为1/96与(2/3)/64，相等。没有将无B的O/P梯度提高1.5倍。无B也不产生B上下文的KL；此对照删除整个B训练分支，不是单独剥离B任务reward。

两臂按更新使用**冻结的旧micro24实际学习率序列**：来源878813 step0–9及878930 step10–39，原cosine token horizon=3932160。这样保留参考实验的实际LR幅度，而不会因少生成B或回答变长而改变学习率。表写入schedule.jsonl并纳入hash。没有把cosine强行加速到40步末的最低LR。仅v2启用；原13/24仍使用原token进度。

40步token上限是安全上限：D24=3932160，OP16=2621440（按每回答最多1024）；实际tokens独立记录，不做等token结论。优化器/奖励/生成参数沿用原micro入口。

## 校验和边界

```bash
python -m examples.social_mixed.micro_learning_24_v2.build
SOCIAL_MICRO_VARIANT=24v2 python -m unittest training.social_mixed.test_micro_training -q
SOCIAL_MICRO_VARIANT=24v2_no_b python -m unittest training.social_mixed.test_micro_training -q
```

build需本地历史tar用于可追溯重建；GPU机只需冻结数据、manifest和训练代码。CPU测试验证请求/seed匹配、曝光、LR匹配、共享task/protocol/KL目标的梯度系数，以及collector对真实历史正确回答的评分。

这些不是GPU试跑或新Q0可学习性证明。原生teacher没有在本次全部重新求解；B核查包括已有标签质量记录、teacher边际分布与gold一致、历史调用重评分、prompt人工审查。训练验证的batch波动限制仍在。

特别说明：无B对照不会增加一个模型，不自动提交任务；B能否带来外部收益仍待实测。最终结论需看相同评测协议下的无辅助行动，而非仅B标签准确率。
