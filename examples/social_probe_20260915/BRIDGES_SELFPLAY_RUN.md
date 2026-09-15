# 新 B 独立重复与 self-play 完整局：双卡各 16 并发

本次沿用已选的 train / validation 小样本，不取 held-out test，不启动训练：

| 阶段 | 固定样本 | 重复数 | 合计 |
|---|---:|---:|---:|
| 新 B bridges，L0–L4 | 18 题（14 train、4 validation） | 8 次独立请求 | 144 回答 |
| self-play | 12 开局（8 train、4 validation） | 4 场完整游戏 | 48 场 |

另有两张卡各 B/P 两个接口 preflight，共 4 次，不计入正式分组。不会重跑旧 B/P 的 224 次正式采样。

每卡 16 个在途请求，两卡合计最多 32；self-play 最多同时推进 32 场，局内依然按动作顺序执行。模型、规则、已审阅 v4 prompt、1024 输出预算不变。每卡一个模型副本，TP=1，CUDA graphs，GPU 6/7。

## Mac 上传

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  examples/social_probe_20260915/remote_bundle/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle/
```

## 服务器启动（在 tmux 中）

之前的性能测试正常退出后会清理自己的两个服务。若旧任务仍在原 tmux 前台运行，在原窗口 Ctrl-C；不要依据历史 PID 批量停止进程。本轮端口 18091/18092 已占用时启动器会报错。

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
PROBE_RUN="/raid/chenjiahao/mas/runs/social_probe_20260915/bridges-selfplay-g16-$(date +%Y%m%d-%H%M%S)"
set -o pipefail
bash examples/social_probe_20260915/remote_bundle/run_remote.sh \
  --execution graphs --workers-per-gpu 16 \
  --stages bridges selfplay --sampling-seed 20260915 \
  --capture-performance \
  --output "$PROBE_RUN" 2>&1 | tee "$PROBE_RUN.console.log"
```

这是正式诊断模式，不加 `--performance-only`。不会复用性能包中每题相同的 seed，也不受性能模式 32 请求／360 秒阶段截止约束。HTTP 单请求 timeout 仍为 180 秒，服务启动就绪期限为 600 秒。

新 B 的每个 `(task_id, sample_index)` 用不同的可复现 seed，记录在原始样本；seed 与 worker 分配、完成顺序无关。调度按单次回答排队，18 题也可以填满 32 个 client slots。仍按原题的 8 次回答计算组内奖励，不混题、不补采至成功，不加答案 retry。self-play 沿用 seed 42，按开局和重复序号派生不同游戏 seed，再按决策和协议尝试派生调用 seed。

两个阶段共用本次加载的模型服务，阶段之间不重新加载权重。自动在每个阶段开头采集最多约 60 秒的 CPU/GPU/vLLM 指标；`bridges-performance.log` 和 `selfplay-performance.log` 记录对应采集目录。阶段若较短，会停止采集器并保留原始 JSONL，可能没有完整 summary；这不是游戏失败。

## 完成与下载

同一终端可执行：

```bash
cat "$PROBE_RUN/COMPLETE.json"
```

预期 `formal_responses_by_stage={"bridges":144}`、`selfplay_attempts=48`。`all_games_terminal` 单独说明所有游戏是否到终局；COMPLETE 表示请求的诊断尝试已采集，不代表模型答对。已识别的基础设施失败会保留 INCOMPLETE 和部分结果，不作为零奖励进入训练。异常退出没有 COMPLETE 时，先保留日志，不自动重跑。

Mac 下载：

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='triton-cache-*/' --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/social_probe_20260915/ \
  new/local_data/social_runs/social_probe_20260915/
```

主要分析：`bridges/samples.jsonl`、`bridges/summary.json`、`selfplay/summary.json`、完整游戏与逐次调用记录、`stage_results.json`、服务日志及性能记录。新 B 看分层正确率、完整八次组奖励差异和 reasoning；self-play 看完整局、合法动作、私有信息、各位置终局收益差异、协议扣分与基础设施失败。

新 B 144 次与先前混合性能包 32 次的题目组成不同；self-play 还包含局内等待与状态处理。不会把总体吞吐差值全部解释为并发 8 → 16 的收益，也不会将其作为严格同负载性能对照。
