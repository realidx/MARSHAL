# 24题密集曝光对照

独立于13题版本，O/P/B各8题。P保留13题版本的8道历史P（历史混合接口，不是当前纯定性P）；O来自旧D学习日志；B为7道旧D题和1道旧B formation题，不引入previous-belief辅助。保留历史实际prompt、解释后提交与原teacher评分。

O/B候选要求至少4次曝光、至少2次非零任务advantage，最后两次正确率至少50%，较前两次提高至少12.5个百分点。全部已知prompt/gold契约冲突的B排除。B仅7道满足此标准，因此另加aa5cada26d5bda6a337c：仅3次历史曝光，明确标为较弱证据，不能称稳定掌握。P沿用原版本筛选标准。全部来自train，不使用CalBench或validation选题。

40次更新，每步每类4题，共12组×8=96条回答；两个半集交替，每题恰好20次曝光、160回答。每题等权，三类因组数相同而各占1/3。半集由ID确定，不依据模型表现动态追采。候选历史学习证据和原始正负样例分别在tasks.jsonl、examples.jsonl；schedule.jsonl可审计40步计划。

启动（训练机）：

```bash
bash examples/social_mixed/start_micro24_training.sh h200-141
```

共享微型实验collector，通过SOCIAL_MICRO_VARIANT=24选择冻结数据包，数据哈希阻止跨包恢复。40更新上限、每10步静态验证与保存、保留4个checkpoint；不改变现有正式O/C/D入口。启动前真实tokenizer检查；本地不提交GPU任务。

与13题版的区别不仅是曝光减半：题量、任务配比、题目内容也改变，不能当作纯曝光次数消融。每步回答104→96，token与cosine进度也不保证相等，应记录实际剂量。筛选基于历史表现，属于探索性学习复现实验，不保证40步学会或外部泛化提高。

## 后续对照（独立版本）

[Micro24 v2](../micro_learning_24_v2/README.md) 保留P8、替换O4和B6，增加去B的OP16匹配入口；原v1数据、调度和入口保持不变。v2逐题历史证据和局限见其 REVIEW.md，不能把新题选择视为已证明提升。
