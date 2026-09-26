# 三人同模型 BENAC 完整局

16个固定初始局，每局只跑一次；三名玩家共享同一checkpoint，各自保持原生私人观察与历史。temperature=0，top_p=1，输出上限4096，一次原生重试。启动服务必须开启VLLM_BATCH_INVARIANT=1；客户端不能远程开启此设置。没有额外focal座位轮换。

4096预算重跑与此前1024预算结果分开保存，不合并比较；场景、奖励和行动规则不变。

## 核对结果

`team_benac_v1/overlap_audit.json`保存44份本地训练/验证文件的哈希和逐场景匹配。历史8个ID在扫描库中有结构匹配，8个OOD均无匹配。但micro_learning_24_v1和micro24_v1_partner_choice_v1均无这16局的结构匹配；不能对当前micro模型继续称前8局为ID。正式输出使用seen_in_audited_banks/unseen_in_audited_banks，表示扫描库并集，不表示每个checkpoint的训练分布。也分别报告binary/linear。

依赖结构匹配允许玩家/承诺重命名；没有根据被测模型成绩换题。场景继承原adversarial_v2，不改变规则、偏好世界或提示词。不能把16局称作16个独立结构，独立性仍取决于结构复用。

## 执行

在已开启batch-invariant的模型服务上，逐模型运行：

```bash
bash examples/final_evaluation/run_team_benac.sh \
  http://localhost:8000/v1 SERVED_MODEL VERIFIED_CHECKPOINT_HASH \
  runs/team_benac/MODEL_LABEL
```

脚本里的确认标记表示操作者已确认服务设置，不会自动配置服务。无需加载Q0伙伴或第二个模型。不得将不同checkpoint导向同一错误的served model别名。

结果以16局为单位，报告完整结束率、完成局团队总收益、三名玩家收益、全样本团队收益保守界限、非法和截断次数。未完成不填零；基础设施错误停止后续批次。原生调用轨迹全部保留。内部复用共享轨迹执行器，底层目录的shared-q0和role=q0是历史实现名称，实际三人都调用传入的唯一route；顶层protocol明确记录homogeneous_team和checkpoint身份。

```bash
python -m unittest examples.final_evaluation.test_team_benac
```

本地16/16脚本策略回放已通过，仅验证接口、路由、终局和汇总；没有运行GPU/LLM，也不代表任何模型测试成绩。温度0且单次运行不提供采样方差估计。
