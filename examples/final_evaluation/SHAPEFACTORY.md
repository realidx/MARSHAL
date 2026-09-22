# Shape Factory：固定行动机会的跨结构团队迁移评测

四个独立agent均使用同一checkpoint。不进入训练或checkpoint自动选择。12个私有订单实例 × private/dashboard = 24局；18周期，每周期每人一次主要动作，共1728次基础调用，格式/截断最多重试一次，最多3456次。服务错误终止并标记失败，不把服务失败或缺失局伪造成普通零分。

## 配置与来源

原生项目 https://github.com/neuhai/CollabSim ，固定commit `08ed0ed1cefb2edf1ea389b20ba8355815a7c8d0`。MIT许可及未修改的Shape Factory经济转换代码、registry随仓库附带，source.json校验哈希；不需下载完整项目。原生controller没有直接使用：这里单独实现固定逻辑时钟、消息递送和观察过滤，因此明确称适配评测，不声称复现论文实时调度。

4人、circle/square/triangle三类型、专长2/1/1；每人资金200、空库存、2个非专长订单（可重复）；生产成本专长15／其他40，生产上限3件，成交价15–100，每履约项奖励60。保留message、produce_shape、propose_trade_offer、trade_response、cancel_trade_offer、fulfill_order、do_nothing。

固定基础专长[circle,circle,square,triangle]枚举3^4个需求矩阵：每类有正需求且不超过对应专长总产能，重复专长中至少一人需要其余两类；得到16候选。按Python固定枚举顺序取前12个，不依赖模型表现；第k个实例将角色映射到agent `(role+k)%4`，shape名按`k//4`循环置换。每个agent恰好6次处于重复专长角色，每种shape恰好4次作为重复专长。实例并非独立结构；private/dashboard是配对重复，统计有效单位为12个实例。

## 时间与信息协议

18周期对应t=0,10,...170秒；t=180结算到期生产但无额外行动。每周期先完成到期生产，再同时构建四份观察，随后按轮换顺序提交动作。推理耗时不推进时钟。消息/报价在下一周期观察可见，不触发额外LLM。每人每周期最多一次明确的格式/截断重试，不为策略不佳或原生状态拒绝额外重试。解析失败两次消耗机会，计入结果。

原生time-mode将生产动作延迟到到期才执行费用、库存、产能检查；本适配保持此语义，不提前扣款或虚构库存预留。因此多个排队生产在到期可能被拒绝。接受报价仍需库存/资金，不自动履约。报价不锁定资金或库存。订单索引随原生履约删除而改变。

private只显示伙伴specialty，dashboard显示伙伴经济行但删除tasks/in_production。双方都可看到原生public事件和公开报价记录；定向消息仅发送者/接收者可见。因此private不是“对伙伴一无所知”，dashboard也不是oracle。观察包含完整可见事件历史，不做秘密摘要、截断或solver菜单。prompt明确规则，不加人格、ToM探针或反思；与原生模板不同之处已通过适配规则说明，不声称prompt字节一致。

## 指标与验证

并列报告平均最终余额、完成订单比例，另报8项全部完成局数；保留个人余额、成交、生产类型、库存、消息、语义拒绝、格式失败、截断、逐周期状态和原始transport。所有普通失败局计入，基础调用固定，不提前因成功或无动作结束。private/dashboard报告逐实例差值，不当24个独立样本。

`shapefactory_v1/references.json`含全部12×2无LLM回放的原生事件：自给全部完成、人均240；专长生产交易全部完成、团队人均290；全部零拒绝。290为该经济配置的全队余额上界：生产非负成本，完成8项至少8件，每件最低15；不是每个自利玩家都愿意实施参考交易的保证。reference调度不能访问模型prompt，也不会替模型执行动作。

## 已有模型服务

复用CalBench routes.json（endpoints.focal/q0，或equivalent_replicas，均须是同一checkpoint）。不新增伙伴模型。

```bash
python -m unittest examples.final_evaluation.test_shapefactory
python -m examples.final_evaluation.shapefactory_local \
  --routes /absolute/path/routes.json \
  --output runs/shapefactory/model-label --parallel-games 2
```

routes须temperature=0，建议max_tokens=4096、timeout_seconds=600；使用同一输出/context协议比较checkpoint。运行器不裁剪prompt；服务拒绝超长请求属于基础设施失败，不能计作能力零分。固定评测可在服务端启用batch-invariant，运行器不擅自修改已有服务。

## 自行启动并清理本地vLLM（沿用CalBench launcher）

```bash
CUDA_VISIBLE_DEVICES=0 python -m examples.final_evaluation.launch_shapefactory_local \
  --runtime soc --model /absolute/path/hf-export --ports 18105 \
  --runner-python "$(command -v python)" --parallel-games 1 \
  --max-model-len 32768 --max-tokens 4096 \
  --output runs/shapefactory_soc/model-label
```

与原CalBench SoC入口相同，需现有兼容vLLM/CUDA环境，launcher会校验版本、保存模型文件哈希/运行环境并只清理自己启动的服务。Shape runner本身只需Python标准库。已有SoC调度环境可使用：

```bash
export SHAPEFACTORY_MODEL=/absolute/path/hf-export
export SHAPEFACTORY_LABEL=q0
export SHAPEFACTORY_RUNNER_PYTHON="$(command -v python)"
sbatch <本机已使用的GPU分区与资源参数> examples/final_evaluation/sbatch_shapefactory_soc.sh
```

未提交作业、未启动模型推理。每局保存manifest、cycles.jsonl、events.json、transport-agent-*.jsonl、final_state、result与完成标记；总体有protocol、results、summary、COMPLETE。复用服务时模型实际身份需由提供者保证；owned launcher另存权重hash。不得将同一checkpoint团队评价解释为固定伙伴条件下的单体提升。
