# O100 短交互 / B 学习结构变体候选

本目录替代 b_learning_candidate_v1 的“基础题桥接”方案。当前为显式 opt-in 候选，尚未修改正在运行的任务或默认启动脚本。

## 数据集

`tasks.jsonl` 共 600 项：

- **O 200 个起点：100 短交互 + 100 静态题。** 保留原来的 66 个已验收短交互起点，从已有 train 来源补充 34 个不同起点，替换原静态池中的 34 个位置。没有增加 O 总量，没有使用 validation。新增根不代表新增独立游戏族。
- **B 200 题：原 180 + 新 20。** 不使用上一版的基础题或 imposed-PASS 桥接。7 个原型都来自三次曝光中正确数和条件正确率不下降、至少两次有正负 advantage 的题。每个原型生成 2–3 个实质先验条件变体，保留原来的公共约束、目标结构、行为历史和 B 接口。重新求解 teacher、重放历史、重算 posterior/gold，不复制标签。当前首版变化集中于真实背景分布，并未声称扩大了目标拓扑的多样性。
- **P 200 题：内容逐项与原库完全一致。** 无历史定性 belief、原评分和 masked 规则不变。

B 仍先简短解释再提交，使用原始 paired_requests；不同时加入额外语义提示。B 按之前的权重方案保留复习：7 道严格改善题 2；13 道较弱证据题 1.5；始终全对 0.25；其他及新题 1。新题未声称已经可学习。

`audit.json` 记录新 B 的原型/先验/新标签、被替换静态 O 的 ID、100 个短交互起点的 8 条随机工具回放结果，以及排除原因。固定先验变体不是给模型数值 posterior，模型输出仍是定性标签。

## 训练采集接口

```python
from training.social_mixed.interaction_training import InteractionCollector
collector = InteractionCollector(tasks, generate, seed=42)
rows, units, games, metrics = collector.collect('decomposed')
# generate([request]) -> [output]，output 保留 completion、prompt_ids、
# response_ids、behavior_log_probs、finish_reason 等原生成器字段。
```

- D 每次 O/B/P 各 4 组，每组 8 个样本；O 固定 2 组静态、2 组短交互。
- O-only 每次 4 组，同样一半短交互。按实际输出 tokens 比较训练剂量。
- 短交互固定 teacher 伙伴，模型实际动作推进原生状态，最多 2–3 次 ego 决策；提前自然结束允许。以终局个人效用为 trajectory reward。
- 一条轨迹中各决策共享组内终局 advantage；每条轨迹的总损失权重相同，不因多一步回答获得更大份额。语义/协议/KL 三类权重都按轨迹分摊。
- 无效或截断导致未完成的轨迹没有伪造终局收益，退出语义归一化；只对失败回答给 −0.2 协议 advantage。之前的合法回答在该失败轨迹中没有语义 advantage。
- B 按冻结权重覆盖轮转；P 复用原 coverage_sampling.choose_view 和原 compact 元数据/父题难度，保留原 P 的资格过滤与覆盖排序。
- 保存 `collector.state` 恢复计数；校验 bank hash，旧训练状态不可直接恢复。采集函数整批成功后才推进计数。

输出采用现有 sequence loss 的 task/protocol/KL 权重字段。当前 collect_group 串行请求用于正确性验收，未完成跨轨迹并发优化。旧 ReasoningCollector 强制每个 canonical 三视图齐全，不能直接读取此库；必须使用新入口。

正式训练入口已接通：`run.py → SocialPipeline → PipelineCollector → InteractionCollector → make_batch/train_social`。静态 O/B/P validation、每 20 次更新验证与保存、最多保留一个 checkpoint 沿用现有配置。GPU 上的实测尚未执行，本次没有提交训练。

从已提交并同步到训练机的干净 checkout 启动 D：

```bash
bash examples/social_mixed/start_interaction_training.sh h100-96 decomposed
# O 对照：将 decomposed 改为 outcome
```

入口设置 SOCIAL_INTERACTION_BANK=1，记录真实数据 hash，提交前检查新库全部静态请求及 800 条随机多步路径的 tokenizer 长度。未采到的路径仍由运行时 4096 上限检查保护，不裁剪历史。现有 source verifier 要求干净 Git checkout；未提交的本地工作不能直接通过提交检查。

同一新阶段恢复（使用对应完整 checkpoint）：

```bash
SOCIAL_INTERACTION_BANK=1 SOCIAL_RECIPE=reasoning SOCIAL_KEEP_CHECKPOINTS=1 bash examples/social_mixed/submit_soc.sh h100-96 decomposed /path/to/checkpoint
```

恢复需保持模型、预算及 bank hash，旧 recipe checkpoint 被明确拒绝。

## 对照和限制

B/O 部分替换后不再每个起点都有同 canonical 的 B/O/P 三视图。O-only 与 D 可以共享本库完全相同的 O 池；但若研究问题要求“对完全相同信息集只做能力拆分”，仍需另设严格配对子集，不能把全部 600 项称作严格配对实验。

100 个起点完成 800 条随机合法工具回放，测试 native 转移、工具接口和自然终局；这不等于真实模型的学习信号验收。B 标签自评分测试主要验证接口一致性，不等于独立证明 teacher 正确。

```bash
python -m examples.social_mixed.interaction_bank_v1.build
python -m unittest examples.social_mixed.interaction_bank_v1.test_candidate -v
```

构建复用已验收且 input/teacher 完全相同的 O 回放缓存；改变输入或 teacher 后重新回放。

## O / C 同步入口（2026-09-25）

使用 `start_interaction_training.sh <GPU profile> outcome` 启动 O，使用
`start_interaction_training.sh <GPU profile> conditioned` 启动 C。两者独立启动，
共享 D 当前题库和 `interaction-v2-name-contract` 姓名映射修复。

|臂|每次更新的候选题组（每组8条回答／轨迹）|任务损失权重|
|---|---|---|
|O|短交互O 2 + 静态O 2|O=1|
|C|短交互O 4 + 静态O 4 + P 4|O=2/3，P=1/3|
|D（未改）|短交互O 2 + 静态O 2 + B 4 + P 4|各1/3|

C 用额外 O 替代 D 的 B 槽位，仍为96条候选回答／轨迹；O保留32条。
多步轨迹会产生多次调用，不能将轨迹数当调用数或相同token剂量。
沿用每20次更新静态O/B/P验证与checkpoint保存、只保留最新一个checkpoint；
不加入CalBench或self-play验证。总预算仍按实际生成tokens停止。
本次本地collector回归通过；未提交训练，未执行GPU验收。
