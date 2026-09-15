# 新 L0 首测：双 A100，各 16 并发

独立包 `remote_bundle_l0/` 已生成。正式运行仅允许 `--stages bridges`；其请求已替换为 `b_l0_isolated_v1/requests.jsonl` 的 6 道 assisted 题。每题 8 个独立可复现 seed，共 48 次；另有原 B/P 接口预检 4 次，不计入正式评分。没有 formation 对照、旧 B/P 正式评测、self-play 或训练。

本地已完成 bundle 校验、冻结 runtime 离线回放和 14 项启动器测试。远程 GPU 6/7、每卡 TP=1、graphs、每卡 16 并发，沿用已验证环境。

## Mac 上传

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  examples/social_probe_20260915/remote_bundle_l0/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle_l0/
```

## 服务器启动（tmux 中）

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
L0_RUN_ROOT=/raid/chenjiahao/mas/runs/social_l0_probe_20260915
mkdir -p "$L0_RUN_ROOT"
PROBE_RUN="$L0_RUN_ROOT/g16-$(date +%Y%m%d-%H%M%S)"
set -o pipefail
bash examples/social_probe_20260915/remote_bundle_l0/run_remote.sh \
  --execution graphs --workers-per-gpu 16 \
  --stages bridges --sampling-seed 20260915 \
  --capture-performance \
  --output "$PROBE_RUN" 2>&1 | tee "$PROBE_RUN.console.log"
```

结束后同一终端：

```bash
cat "$PROBE_RUN/COMPLETE.json"
```

预期 `formal_responses_by_stage={"bridges":48}`、`selfplay_attempts=0`。COMPLETE 仅表示采集完成，不意味着模型回答正确。结果保存在 `bridges/samples.jsonl`，本地用新包标签评分。不要加 `--performance-only`，它会被此独立包拒绝。

## Mac 下载

```bash
cd /Users/bruce/MARSHAL
rsync -avzP --exclude='triton-cache-*/' --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/social_l0_probe_20260915/ \
  new/local_data/social_runs/social_l0_probe_20260915/
```

同一下载命令也保留异常退出时的部分结果与控制台日志，无需等待 COMPLETE 才能下载分析。
