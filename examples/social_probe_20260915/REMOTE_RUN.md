# 双卡 A100：用户执行的首轮小样本测试

2026-09-15 最新入口：graphs 并发 4/8 已实测，现在按 [BRIDGES_SELFPLAY_RUN.md](BRIDGES_SELFPLAY_RUN.md) 运行新 B 和 self-play，每卡并发 16。下方保留原全套诊断的命令；本轮不重跑旧 B/P。新增 `--stages`、`--sampling-seed`、`--capture-performance`；正式 B/P 现在逐次回答调度并分配不同 seed。原先的性能对照记录见 [PERFORMANCE_FIX.md](PERFORMANCE_FIX.md)。

本轮推理测试：原 B/P 28 题、新 B 18 题，每题 8 次，共 368 次正式回答；self-play 12 个固定开局，每局 4 条完整轨迹，共 48 场。另有每张卡 B/P 各一题、合计 4 次独立 preflight。没有训练更新，没有 held-out test。

路径来自 `training/b_sft/SOCIAL_SERVER_RUN.md` 与 `VLLM_SAME_CONDA.md`。两张卡的当前分配编号由用户填写，不复用旧实验的 GPU 编号。主助手只准备文件和命令，不登录服务器或启动远程任务。

## 1. Mac 上传

上传冻结的小包，无需上传整个仓库，也不安装依赖。rsync 不删除远程其他文件。

```bash
cd /Users/bruce/MARSHAL
ssh -i "$HOME/.ssh/id_rsa_dgx2" -p 2201 chenjiahao@36.102.215.18 \
  'mkdir -p /raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle'
rsync -avzP --exclude='__pycache__/' -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  examples/social_probe_20260915/remote_bundle/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle/
```

## 2. 服务器检查并启动

先登录，再进入 tmux，断开 SSH 后作业仍可继续。

```bash
ssh -t -i "$HOME/.ssh/id_rsa_dgx2" -p 2201 chenjiahao@36.102.215.18 \
  'tmux new -s social-probe-0915'
```

在 tmux 内执行以下块。GPU 提示处输入本次分配的两个编号，例如 `0,1`；不是自动选择空闲卡。`nvidia-smi` 的空闲状态本身不能替代分配信息。

```bash
cd /raid/chenjiahao/mas
/raid/chenjiahao/conda_envs/mas/bin/python \
  examples/social_probe_20260915/remote_bundle/run_remote.py --check
nvidia-smi
read -r -p '本次分配的两个 GPU 编号（逗号分隔）: ' PROBE_GPU_IDS
export CUDA_VISIBLE_DEVICES="$PROBE_GPU_IDS"
PROBE_RUN="/raid/chenjiahao/mas/runs/social_probe_20260915/$(date +%Y%m%d-%H%M%S)"
mkdir -p /raid/chenjiahao/mas/runs/social_probe_20260915
printf '%s\n' "$PROBE_RUN" > /raid/chenjiahao/mas/runs/social_probe_20260915/LAST_RUN.txt
set -o pipefail
bash examples/social_probe_20260915/remote_bundle/run_remote.sh \
  --output "$PROBE_RUN" 2>&1 | tee "$PROBE_RUN.console.log"
```

`--check` 仅检查哈希与 12 个脚本对局，不调用模型，也不占用 GPU。正式运行保存环境版本并验证 tokenizer 模板；若环境或模型路径失效，报错时保留日志，不自行安装或替换依赖。

默认配置：

| 项目 | 设置 |
|---|---|
| Python | `/raid/chenjiahao/conda_envs/mas/bin/python` |
| 模型 | `/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507` |
| GPU | 每卡一个模型副本，TP=1 |
| 并发 | 每卡 4 个请求；self-play 最多 8 场同时推进 |
| 显存预算 | 每卡 0.80，按整卡容量计算 |
| 上下文／输出 | 16384／1024 tokens；禁止截断输入 |
| vLLM | 旧环境的 V0、XFORMERS、eager、Hermes 原生工具 |
| 端口 | localhost 18091、18092；已占用则报错 |
| B/P | temperature 0.8、top_p=1、top_k=-1；二元奖励留待本地评分；无答案 retry |
| Self-play | temperature 0.7；其余采样参数沿用模型服务默认，保存 generation_config；全局 seed 42 |
| Self-play 失败处理 | 沿用最多一次协议重试，失败每次 -0.1，与终局 utility 分开记；网络失败另列 |

调用结束或正常中断时，清理本入口创建的两个服务进程组；不停止已有服务。`Ctrl-b d` 脱离 tmux，`tmux attach -t social-probe-0915` 返回。

`PROBE_PYTHON` 可覆盖 Python；`--model`、`--ports`、`--workers-per-gpu`、`--gpu-memory` 可覆盖对应设置。若出现显存不足或 parser 失败，保留本轮目录和第一条 traceback 后交给助手分析，不在同一输出目录覆盖重跑。

## 3. 检查结束状态

```bash
PROBE_RUN="$(cat /raid/chenjiahao/mas/runs/social_probe_20260915/LAST_RUN.txt)"
cat "$PROBE_RUN/COMPLETE.json"
```

`COMPLETE.json` 只表示已采集全部计划尝试；其中 `all_games_terminal` 单独说明是否 48 场均结束，不代表动作正确或收益有训练价值。HTTP／上下文异常会留下日志和部分结果，可能生成 `INCOMPLETE.json`，不把缺失回报当作零。

本轮统一重新采样全部 46 道 B/P；旧结果保留用于比较，不混入新 group。完整样本含 train／validation 标记。B/P ground truth 不在上传包中；self-play 的隐藏世界仅供环境重置，模型输入来自 `safe_observation`。

## 4. Mac 下载

在本地新终端执行；第一次只会下载本轮输出。省略可重建的 Triton 缓存，其余日志、样本、冻结包与环境记录一并保留。

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/social_probe_20260915
rsync -avzP --exclude='triton-cache-*/' --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/social_probe_20260915/ \
  new/local_data/social_runs/social_probe_20260915/
```

完成后告诉助手本地目录或运行时间戳。主要分析文件为 `bp/samples.jsonl`、`bridges/samples.jsonl`、`selfplay/group-*.json`、`selfplay/summary.json`、`server_manifest.json` 和两个服务日志。
