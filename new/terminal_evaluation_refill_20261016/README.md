# 2026-10-16：验证和测试完成即补位

落实效率项5：训练后的validation和正常预算结束后的final-test也接入原生补位。
独立GPU smoke按用户约束不作为前置条件，本轮没有启动GPU、提交任务或调用模型。
当前配置/启动方式见[训练文档](../../examples/strategic_slices/TERMINAL_TRAINING.md)。

## 改动

- Slice cohort跨parent共用有界任务池，不等一个parent的最长episode再开下一个。
  每个episode同时一个待生成回答，完成后继续该链，空位接下一固定评测实例。
- 完整游戏把不同parent、team与focal-reference、固定replicas合在一个池，
  移除parent和mode边界的等待。默认至多32个活跃episode/回答，按需构造任务，
  完成即释放树引用，不一次性构造所有test repeats。缓存仍按既定内存预算管理。
- Slice和完整游戏两个cohort依次执行；各自池内完成即补位。实际pipeline复用
  NativeStream及原生prompt/response IDs、logprobs、seed，不通过HTTP线程包装。
- 固定题目、split、validation limit、repeats、seed/world reset、greedy和
  输出上限均沿用原定义。每条链的reference RNG独立；不按速度筛选题或丢弃长回答。
  完成后按原题目/parent/角色/replica顺序恢复报告，保留原parent macro与区间统计。
- 验证整段成功率选best、final-only自动test、500K验证/1M保存和训练6M预算
  不变。验证/test response tokens另计。新增execution成本不参与checkpoint排序。
- 测试中断/基础设施失败会取消和flush，既有训练checkpoint保留，不写COMPLETE。
  完成全部cohort才落最终报告和完成标记；同身份完成结果复用，不重复测试。
  执行身份更新为`terminal-final-test-v3-eval-refill`并记录scheduler。
- 同步评测路径保留作独立CPU对照及无native engine调用兼容；正式pipeline的
  validation和final-test明确绑定新路径。独立HTTP评测CLI本轮未改调度。

代码：

- [有界懒加载调度器](../../training/strategic_slices/evaluation_refill.py)
- [Slice验证/测试](../../training/strategic_slices/terminal_training_evaluate.py)
- [完整游戏跨模式评测](../../training/strategic_slices/evaluate.py)
- [Pipeline绑定及执行成本](../../training/strategic_slices/terminal_training_pipeline.py)
- [Final-test完整性/中断/结果复用](../../training/strategic_slices/terminal_training_final_test.py)

## CPU验收

[72项相关回归全部通过](cpu_tests.txt)，其中8项新增评测检查：

- validation/test、多个父游戏、k1/2/3、重复实例及不同完成顺序，**整个科学报告
  与旧同步实现一致**。执行计时/并发等诊断存放在独立`execution`字段。
- 失败/截断路径、4096自定义输出上限与旧报告一致；所有实际回答计费。
- 用实际NativeStream和实际worker方法连接Validator（Ray、tokenizer和GPU engine
  使用CPU替身），也得到与同步对照一致的报告。
- 最长初始回答没结束时，后续parent和focal-reference任务已经提交。
- 懒加载活跃数不超过并发；重复completion会报错取消，不重复统计样本。
- final-test实际使用native factory，不静默回到同步generate；完成结果幂等，
  中断/失败不写完成标记且保留checkpoint；中断后可重新测试。

[32并发、8 repeats虚拟检查](virtual_time_check.json)：96条slice和128条完整
游戏（合成小型native fixture，非真实test集结果）与旧报告一致。两个池均达到
32个inflight；初始长回答虚拟时间1000才完成，新的slice/full实例分别在1/4
开始，所有回答最终排空。虚拟时间不是GPU秒数，不报告吞吐提速比例。

[真实冻结validation小样本](frozen_validation_check.json)：4 slices、3 parents、
11条完整游戏，原始报告完全相同；合成模型回答共86 tokens，split仅validation。
本项用同步stream adapter验证真实数据/report接口；逐completion行为另由上面
的虚拟长短交错及实际native方法CPU替身验证，不把mock当作真实greedy模型表现。

[Preflight](preflight.json)包含新的评测scheduler身份，冻结数据未修改。
复现命令：

```bash
python -m unittest training.strategic_slices.test_evaluation_refill
python -m examples.strategic_slices.check_terminal_evaluation_refill --output /tmp/terminal-eval-refill.json
python -m training.strategic_slices.train_terminal --check-only
```

## 执行成本与限制

报告`execution.slices/full_games`包含jobs、decision_calls、generated_response_tokens、
peak_inflight、seconds、native_ticks与prompt_tokenizations。验证指标日志使用
`eval_execution/...`；final-test报告单独保存执行成本。并发指已提交未完成回答，
不等于物理GPU一直满载。Reference恢复、Q查询、cohort尾部依赖仍可能造成空闲。
活跃episode可能持有缓存之外的树，缓存预算不是进程RSS上限。

不要求另开GPU smoke；正式任务的前几步沿用原有诊断观察实际运行。GPU吞吐、
16K显存、硬件依赖及GPU恢复仍未验证，CPU报告等价不代表GPU逐位浮点等价。
SP臂、强信息held-out不足、旧test暴露等此前限制保持原状。

新的[源码overlay](../local_data/terminal_evaluation_refill_source_20261016.tar.gz)及
[SHA/身份](source_bundle.json)用于已有完整repo与环境，不含数据、权重或依赖。
旧source不能混续；正式新开时使用当前repo或本包，保留原selected-v4数据。
