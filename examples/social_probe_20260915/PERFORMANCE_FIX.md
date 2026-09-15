# 双 A100 性能处理：CPU 定位与短对照

不需要等待旧完整诊断。主助手只准备代码，以下远程命令由用户运行。

CPU 资源协调不必作为短对照的前置条件：可以在当前争用条件下直接试 eager／graphs，判断哪个配置在当前服务器上更实用。两轮都要记录 CPU 负载；负载变化时不把全部速度差归因于配置。没有明显加速也不能据此证明 graphs 在 CPU 资源充足时无效。

## 1. 上传已准备的小包（Mac）

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  examples/social_probe_20260915/remote_bundle/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle/
```

## 2. 先定位 CPU（服务器，约 10 秒，无 GPU 请求）

```bash
cd /raid/chenjiahao/mas
CPU_DIAG="/raid/chenjiahao/mas/runs/social_probe_20260915/cpu-$(date +%Y%m%d-%H%M%S)"
/raid/chenjiahao/conda_envs/mas/bin/python \
  examples/social_probe_20260915/remote_bundle/diagnose_cpu.py --output "$CPU_DIAG"
```

把打印的排名发给助手，或者按文末命令下载 `cpu.json`。工具读取所有可见账号的进程 CPU 时间差，100% 对应一个逻辑核，可超过 100%；没有使用 `ps` 的进程生涯平均。记录 PID、父 PID、账号、线程数、CPU affinity、实际 cgroup 路径。本账号排名靠前进程还记录可读的程序路径和工作目录，不读取命令参数或环境变量，不停止任何进程。存活时间短于采集窗口、权限隐藏的进程可能遗漏。

处理取决于实际排名：确认本人的旧任务已不用才通过其原始启动入口停止；若是其他人的有效任务，需服务器管理员／资源分配保障可用 CPU 时间或限制那些任务的 CPU 范围。单纯 taskset 不提供独占资源，不盲目 `ray stop`、`pkill python` 或给所有任务加线程限制。

旧 probe 如仍在 tmux 前台运行，在其原窗口 Ctrl-C，让启动器清理自己创建的服务；不要照抄历史 PID 执行 kill。性能模式仍使用端口 18091/18092，旧服务还占用时会直接报错。

## 3. 运行短基线（允许在当前 CPU 条件下先试）

GPU 6、7 是本轮用户已分配的两张卡；以下沿用该分配。仍然每卡一个 4B 模型副本，不改为 TP=2。

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
PERF_RUN="/raid/chenjiahao/mas/runs/social_probe_20260915/perf-eager4-$(date +%Y%m%d-%H%M%S)"
set -o pipefail
bash examples/social_probe_20260915/remote_bundle/run_remote.sh \
  --performance-only --execution eager --workers-per-gpu 4 \
  --output "$PERF_RUN" 2>&1 | tee "$PERF_RUN.console.log"
```

服务器启动就绪后，只有固定 16 题各 2 次，共 32 个请求；保留原请求的原生工具、1024 输出预算、temperature、top_p、top_k，使用固定题目 seed。覆盖旧 B 8 题、旧 P 4 题、新 B 4 题。不是新的评估集，不将固定 seed 重复结果放进训练 reward group。不运行正式 preflight、368 次诊断或 self-play。

采样子进程硬截止为 360 秒，超时保留已经写出的回答，停止采样并由启动器清理本轮服务。模型启动另有默认 600 秒就绪期限，清理也需要时间，因此 6 分钟不是整个命令的总期限。失败或超时不会自动重跑。

结果为 `PERFORMANCE.json`，不会生成正式评估的 `COMPLETE.json`。吞吐包含首批请求和收尾，排除模型启动；未完成时只统计已保存 token，是下界，不能当完整稳态吞吐比较。

若需要同一时段 GPU／CPU 指标，在打印 `Performance only: 32 requests` 后另开终端运行已有采集器（填本次打印的 PROBE_RUN_DIR）：

```bash
/raid/chenjiahao/conda_envs/mas/bin/python \
  /raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle/capture_performance.py \
  --run-dir /raid/chenjiahao/mas/runs/social_probe_20260915/perf-eager4-实际时间戳 --seconds 30
```

## 4. 依次改变配置，逐次看结果

第一轮完成并清理服务后，复制同一启动块：第二轮改输出目录前缀为 `perf-graphs4`，参数为 `--execution graphs --workers-per-gpu 4`；第二轮正常且有收益后，第三轮前缀为 `perf-graphs8`，参数为 `--execution graphs --workers-per-gpu 8`。不要同时启动，也不要直接运行三轮自动循环。

`graphs` 仅移除 `--enforce-eager`，其余服务选项保持一致；需检查日志确认实际 graph capture。vLLM 的 eager 选项及 graph/eager 混合执行行为参见 [v0.8.5 官方参数文档](https://docs.vllm.ai/en/v0.8.5/serving/engine_args.html)。旧环境是否支持稳定 capture 需要验证，不预先升级驱动或更换依赖。若捕获失败，保留第一条 traceback，回到 eager 基线分析。

对比实际输出 tokens/s、单请求耗时、失败／截断数量和同时段 CPU 压力。CPU 负载可比、全部请求完成时，短对照更能支持配置因果判断；当前高负载下也可以判断实际可用性。32 请求足以发现数量级变化，不能替代长时间稳态吞吐测试。不要以 GPU 利用率必须达到 100% 为验收标准。

## 5. 下载（Mac）

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='triton-cache-*/' --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/social_probe_20260915/ \
  new/local_data/social_runs/social_probe_20260915/
```
