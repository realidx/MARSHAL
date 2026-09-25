# 原micro24的匹配O/C/D对照

回到取得9/24成功、headline约0.630的micro24-v1题库；不使用v2替换题，不扩到60题。
`tasks.jsonl`、`examples.jsonl`与原v1逐字节相同。P仍是旧接口（含历史、部分数值联合belief），B仍是该库的单一full-set/undetermined标签。实验回答这些既有分支的增量作用，不证明统一B→P表示或一般B能力的价值。

|分支|题数|每步组数|回答数|每行task/protocol/KL权重|
|---|---:|---|---:|---:|
|O|O8|O4|32|1/3|
|C|O8+P8|O4+P4|64|2/3|
|D|O8+P8+B8|O4+P4+B4|96|1|

所有分支40次更新、每题8回答/曝光、每题20次曝光；删去的分支不补采。共享题请求、采样seed和顺序一致。损失按回答均值，因此每个共享回答的系数均为1/96。删去分支也删去其协议和KL损失；不是只剥离语义reward。不是等token/等计算预算比较。

学习率沿用原v1实际训练轨迹并按step冻结（878813步骤0–9 +878930步骤10–39，旧token horizon3932160），三臂相同，避免删除分支后token进度改变LR。原13/24入口不变；新身份包含臂名，禁止交叉resume。

每10步静态验证和保存checkpoint，默认保留4个，可通过SOCIAL_KEEP_CHECKPOINTS显式设置。未采用先前讨论的100步/20步保存方案。没有训练内CalBench/self-play验证。三臂从相同Q0 actor/reference独立开始。

```bash
bash examples/social_mixed/start_micro24_v1_o_training.sh h100-96
bash examples/social_mixed/start_micro24_v1_c_training.sh h100-96
# 可选：同环境补跑D；旧D只作为历史参照
bash examples/social_mixed/start_micro24_v1_d_training.sh h100-96
```

沿用start_training.sh的SOCIAL_MODEL与远端提交设置。CPU回归验证共享请求、曝光、学习率、权重、身份隔离和历史正确答案评分；真实tokenizer预检在启动时执行。尚未GPU试跑或提交任务。即使seed相同，不同推理批次也不保证采样输出逐字一致。
