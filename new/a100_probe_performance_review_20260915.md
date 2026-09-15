# 双 A100 部分采样与性能复核（2026-09-15）

输入：`new/local_data/social_runs/social_probe_20260915/20260914-121953/`。这是已下载快照，不等待远程任务完成，不据此认定远程任务已经退出。

## 结论

主机 CPU 严重争用已有直接证据，是当前低吞吐的首要排查对象。当前 eager 配置还明确关闭了异步输出处理。两者对吞吐各自造成多大影响仍需短对照实验，不能直接认定 A100 硬件慢，也不能保证仅去掉 eager 就能恢复。

## 性能证据

来自 `performance-20260914T163348Z/` 的 59 个样本，约 60 秒：

| 指标 | 结果 |
|---|---|
| GPU 6 / 7 平均利用率 | 13.81% / 18.44% |
| GPU 6 / 7 平均功耗 | 74.12 W / 78.62 W |
| 18091 / 18092 输出吞吐 | 41.79 / 53.62 tokens/s，各为整个引擎合计 |
| 两个引擎 running | 每次观测均为 4 |
| 两个引擎 waiting / preemption 增量 | 均为 0 |
| 整机 CPU user / system | 98.289% / 1.515% |
| 整机 CPU idle / iowait | 0.000332% / 0% |
| 逻辑 CPU | 256；其中 255 个在窗口内 idle 增量为 0 |
| load1 平均值 | 381.22 |
| CPU PSI some avg10 的采样均值 | 24.00% |

CPU 百分比按首尾 `/proc/stat` 差分的前八列计算，避免重复计算 guest 时间。PSI 表示存在任务等待 CPU 的时间占比，不是 GPU 等待占比，也不是吞吐损失百分比。参见 [Linux PSI 文档](https://docs.kernel.org/accounting/psi.html)。

两个服务器日志均明确记录：`Since, enforce-eager is enabled, async output processor cannot be used`。启动采用 vLLM 0.8.5.post1+cu118、V0、XFormers、`--enforce-eager`、`--disable-frontend-multiprocessing`；每张卡独立运行一个模型实例，每引擎并发 4。

因此，不能将 waiting=0 解读为客户端没有发送请求：观测时各引擎始终有 4 个在途请求，已经达到本轮并发上限。尚无 KV 换出或抢占证据。采集时没有内存不足、I/O 等待或活动热降频／功率限制的明显证据。

同账号进程快照包含两组 Ray worker，各 128 个 `ray::IDLE`，父 raylet PID 为 1055113 和 1361619。本轮 HTTP 启动器不依赖 Ray。这些进程值得核查，但名称及 `ps %CPU` 的历史平均不能证明其造成当前 CPU 饱和；采集的进程列表也没有覆盖其他账号。不得盲目执行 `ray stop` 或批量杀进程。采集器自身的 CPU affinity 与根 cgroup 信息不能代替 vLLM 进程的实际资源约束。

性能采集 UTC 时间与服务器日志打印时间不同，未确认日志时区；不把这两份文件拼成精确连续时间线，也不推算整个作业实际完成时长。

## 已落盘回答

不含 4 条 preflight，正式 `bp/samples.jsonl` 有 71 条，涉及旧 B 的 12 道题：

- 保存记录均为 HTTP completed，无保存的 infrastructure failure；这不意味着游戏动作完成。
- 58 条 finish_reason=length，占 81.69%，按现有二元奖励记 0。
- 13 条完成工具提交，现有评分器判定 3 条正确、10 条错误；总计 3/71。
- 请求耗时中位数 77.75 秒，总输出 68,264 tokens。
- 6 道题各有完整 8 次：4 组全零，2 组混合奖励（2/8 与 1/8）；另 6 组未满，不当作完整 GRPO 组统计。
- 完成但错误的回答包括错误全集、过度排除，以及集合正确但 favored 错误。
- 尚无 P、新 B bridges、self-play 结果，不能宣称其难度、奖励方差、推理质量已验证。

评分使用本地冻结的 `selection_v1/bp_tasks.local.jsonl` 和 `training.b_sft.social_bp_training.reward`。这是按现有标签复算，不是新的独立 solver 标签审查。逐条结果与汇总已保存到本次下载目录的 `local_analysis/bp_scored_partial.jsonl`、`local_analysis/summary.json`。部分完成样本也可能受完成速度选择影响，不代表总体准确率。

## 下一步

1. 不继续等待这轮完整诊断。先用短时间、全账号、按线程的 CPU 采样确认当前争用来源，并核查本轮 vLLM 的 affinity／所属 cgroup；没有证据时不停止其他任务。
2. 优先取得实际 CPU 时间保障：确认本人遗留任务才清理，或通过服务器资源分配保证 CPU。单纯 taskset 绑定到仍被别人占满的核并不等于资源预留。
3. CPU 条件稳定后，固定同一小批请求、相同 1024 输出预算与采样参数，以 eager 为基线，仅改变 CUDA graphs 开关，再单独比较并发 4 与 8。记录实际输出 tokens/s、请求耗时和 CPU 压力；每次仅少量请求，不重新启动整个诊断集。当前旧栈能否稳定运行 graphs 需要实测，不假设可用。
4. 性能可接受后优先运行尚无模型证据的新 B 和 self-play，同时保留已采旧 B。训练原则不变，不通过删减推理预算、添加答案重试或修改奖励来掩盖吞吐问题。
