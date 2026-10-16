# 2026-10-16：v6训练采样完成即补位

用户指出：32并发按整批回收，短回答必须等最长回答，导致空位不能补任务。
已同时替换训练collector的wave循环和底层整批`LLM.generate()`路径，当前版本
`terminal-node-regret-grpo-refill-v6`。本轮未提交任务、启动GPU或调用真实模型。

## 实现与不变的统计口径

- 全局最多32个未完成回答；每个回答独立ID。完成一个即释放一个名额，填已准备
  的候选；还有节点预算时再开新入口，不局限于4条入口链。
- 生成前均匀抽定一个原始候选位置，与其分数、长度、完成先后无关。它完成即可
  执行动作并准备下一节点；其余7个继续生成。保留原节点actions/Q/posterior
  小快照，因此推进后仍按原上下文评分，不保留废弃分支的整棵树。
- 同节点8个全部收齐才计算mean/std优势；长回答、失败回答、零优势组都保留。
  每批所有候选排空、预留的链完成后才更新/睡眠/同步权重；没有按完成速度丢弃
  样本、截止后抛弃长回答或跨版本模型混采。
- 原负regret、独立protocol惩罚、node/response/token权重、20实际节点组目标、
  剩余k预算预留、500K验证/1M保存、best/final规则均保留。版本变化是调度合同。
- 使用仓库既有vLLM wrapper的`add_requests/fetch_output`，每请求保留原生
  prompt/response IDs、实际behavior logprobs、seed和finish reason；无HTTP包装。
- 一个worker同时至多一个engine RPC；有完成立即返回，无完成最多16次engine
  step就返回以接收补位。driver `ray.wait(num_returns=1)` 回收任一worker，
  不等所有worker。各worker共享全局32名额，没有DP虚拟样本。
- 异常时先abort并flush未完成请求，才退出session；collector cursor不提交，
  沿用最近完整optimizer checkpoint恢复。v5 checkpoint/source不能静默续跑。

实现文件：

- [collector与评分快照](../../training/strategic_slices/terminal_training.py)
- [native stream桥接](../../training/social_mixed/native_stream.py)
- [worker增量引擎RPC](../../training/social_mixed/workers.py)
- [实际pipeline绑定](../../training/strategic_slices/terminal_training_pipeline.py)

## 已验证

[59项CPU回归全部通过](cpu_tests.txt)，包括此前50项和9项新增调度/引擎检查：

- 虚拟长短交错：最初32个中有一个长回答仍未完成时，已提交第5个入口。
  实际虚拟时间、总提交/完成数见[straggler check](straggler_check.json)。
- 选中回答先完成时，后续节点在其他兄弟回答完成前提交；原节点8回答都保留。
- 改变完成顺序，采样/奖励/最终批次边界/曝光与恢复状态一致；与同步mock
  返回完全相同的最终结果。并发上限不超过32，默认最终20–22节点组。
- 执行实际worker方法的CPU engine double：短回答先返回、长请求继续保留，
  能在其未结束时加入新请求；原生token/logprob与逐请求seed保留，wake每session一次。
- 两worker的Ray double：等待任一worker、短请求所在worker先回收并补位，
  不生成padding；基础设施/behavior证据错误时取消、清理且不提交cursor。
- 数据/默认配置的[preflight](preflight.json)通过，冻结数据身份不变。

长短交错测试是事件调度验证，不是真实吞吐benchmark；CPU mock的精确恢复也
不等于GPU浮点逐位复现。`--mock`使用同步adapter，真实GPU训练pipeline已明确
绑定NativeStream，不会静默退回整批generate。v5真实数据mock记录继续以原身份
保存在[此前验收](../terminal_node_grpo_readiness_20261016/README.md)。

## 仍需GPU smoke

按[当前训练文档](../../examples/strategic_slices/TERMINAL_TRAINING.md)先一次更新暂停，
再恢复一次。核对`scheduler_peak_inflight`、`scheduler_native_ticks`、collection
墙钟、生成回收等待、CPU Oracle耗时、显存和behavior概率偏差。需要在实际vLLM/
Ray环境验证增量引擎RPC、长短输出、取消、optimizer/offload/resume；不能把CPU
double测试写成GPU通过或宣称确定比例的提速。

GPU持续有工作仍取决于CPU能否及时恢复reference/计算Q、可用后继节点和剩余
批次预算；批次末尾排空时并发自然下降。新调度可同时保留比v5更多的活跃入口树，
上界受整批节点预算限制，smoke也须观察CPU内存。废弃兄弟仅保留小评分快照。
本轮只替换**训练采样**；低频validation/test仍沿用原同步生成。独立强信息
held-out不足、正式匹配SP臂未就绪等此前限制也没有因调度修改而解决。

新的[源码overlay](../local_data/terminal_node_grpo_refill_v6_source_20261016.tar.gz)
和[SHA/身份](source_bundle.json)供已有完整repo与SoC环境使用。不含数据、模型或
依赖，保留原selected-v4数据包；不要用之前的v5源码包覆盖v6。
