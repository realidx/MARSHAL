# 双 A100 graphs / 并发 4 复核

结果目录：`new/local_data/social_runs/social_probe_20260915/perf-graphs4-20260914-130137/`。

## 结论

graphs 配置已成功运行，可以继续测试每卡并发 8。32 个请求全部正常返回，无 HTTP 失败或采样超时；模型提交工具的比例与语义正确率另行统计，不能把 HTTP 完成当作任务完成。CPU 资源协调不作为继续短测的前置条件。

## 启动与性能

- GPU 6、7，每卡一个 Qwen3-4B-Instruct-2507，TP=1，每卡并发 4。
- 两个日志都显示 `enforce_eager=False`、`use_async_output_proc=True`。
- 两张卡均成功捕获 batch shapes `[4,2,1]`，capture 各约 6 秒，额外占用各约 0.24 GiB。没有 ERROR 或 Traceback；退出时有未显式销毁 NCCL process group 的警告，不是本轮采样失败，未来持续复用服务仍应规范关闭。
- 32/32 HTTP 完成，0 基础设施失败，0 超时。
- 采样墙钟 104.395 秒，不含模型启动；累计输出 29,991 tokens，双卡合计 287.283 tokens/s。
- 单请求耗时中位数 25.492 秒。
- 服务器日志中 running=4 时，每卡 generation throughput 观测中位数约 165.9 / 148.5 tokens/s；该指标与整个作业墙钟吞吐口径不同，不直接相加作为另一项全程实测。
- max context 16384、输出 1024、原生工具和原请求采样配置均保留；16 个性能请求与冻结数据相比，request 字段仅增加了 seed。模型配置、generation_config 和 tokenizer_config 哈希与旧 eager 一致。

本次下载也更新了旧 eager 目录：现在 `bp/samples.jsonl` 有 224 条，旧报告的 71 条是之前的下载快照，不能继续当作最新计数。新旧共有的 8 道旧 B，eager 64 条请求耗时中位数 78.642 秒，graphs 16 条为 27.711 秒；仅看这些题里输出恰为 1024 tokens 的回答，eager 52 条中位数 93.307 秒，graphs 14 条为 27.861 秒。这支持约三倍量级的明显速度改善，但新旧 seed、次数、时间窗口和任务调度不同，不是严格控制变量的加速比。

本轮没有附带同期 CPU/GPU 性能采集，不能确认 graphs 运行时其他账号的 CPU 负载与之前完全相同。此开关同时改变 graph 执行与异步输出处理，不能把全部收益只归因于 kernel launch 开销，也不能据此断言 CPU 资源今后无影响。

## 回答与评分

按本地冻结标签及 `training.b_sft.social_bp_training.reward` 复算：

| 子集 | 回答数 | 工具提交 | 正确 | 长度截断 |
|---|---:|---:|---:|---:|
| 旧 B（8 题） | 16 | 2 | 0 | 14 |
| 旧 P（4 题，均为 complete） | 8 | 6 | 5 | 2 |
| 新 B（4 题，均为 L0） | 8 | 0 | 0 | 8 |
| 合计 | 32 | 8 | 5 | 24 |

8 个非截断回答均完成原生工具提交；评分器未发现独立的格式失败。24 次截断仍按现有二元任务奖励记 0，不归因于基础设施。

抽查发现：

- 旧 B `8388673040dd7708ecfb` 的两次工具答案均错。模型把隐藏偏好误说成已知 neutral，随后又返回全集，并没有正确处理行为证据。
- P `6d6f8bfdbd54504328ea` 有正确 OFFER，但 reasoning 曾把未完成的 avoid 算成 +1，后续又出现相互矛盾的计分说法。正确动作不等于正确推理。
- P `4e2cac0f2eba7ad622ba` 的一次错误 OFFER 漏掉自身 Maple 承诺，却在解释中声称需要三方 Maple 的目标已经完成，属于 ALL_OF 检查错误。
- 新 B L0 的解释已经出现状态误读、反复推演、引入未支持的“可能不信任对方”等理由；8 次均未在 1024 内提交。它们是模型行为诊断，不自动证明题面或标签存在问题。

本轮每题两次使用固定相同 seed；部分输出相同，部分受执行过程影响而不同。不是独立 reward group，不估计 GRPO 奖励方差，不宣称新 B 难度平滑性已经验证。这里只覆盖新 B L0 与 P complete，没有 self-play。

逐条评分：本次目录 `local_analysis/scored.jsonl`；汇总及输入哈希：`local_analysis/summary.json`。旧 eager 更新后的 224 条评分另存其目录 `local_analysis/bp_scored_download224.jsonl`，保留旧 71 条分析文件作历史快照。当前评分是标签复算，不是新一轮独立 solver 审查。

## 下一步

保持同一性能请求、模型、预算和 graphs，将 `--workers-per-gpu` 改为 8，输出到新的 `perf-graphs8-*` 目录。仍然仅 32 次，不扩大全套采样。对比完整作业输出 tokens/s、单请求耗时、错误和显存／抢占记录；request_sha256 应保持 `e51f93b98fcac38f4358df3b71743e75bcb66e8d5552e274a3826a315be734df`。

若并发 8 没有明确吞吐收益，不继续盲目增大；转入真正的非 test 诊断采样，特别是新 B 的独立重复和 self-play 完整游戏。保留 1024 输出预算，不为性能测试改 prompt、奖励或加入答案 retry。
