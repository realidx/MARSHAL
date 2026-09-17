# chenjiahao 远程 rollout 命令

沿用已记录的环境：`chenjiahao@36.102.215.18:2201`，`/raid/chenjiahao/conda_envs/mas/bin/python`，`/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507`，GPU 6、7。独立bundle已生成，不要求更新远程训练checkout，不切换分支，不安装依赖。

依据：`examples/social_mixed/run_distribution_probe.sh`、`a100_evaluate.py`、`training/social_mixed/evaluate.py`及2026-09-15/16远程rollout记录。最新distribution probe使用temperature=1、top_p=1、top_k=-1、repetition_penalty=1；本次已对齐，不使用此前通用示例的0.7/0.8。

## 1. 本地上传

在Mac运行：

```bash
cd /Users/bruce/MARSHAL
rsync -avz --exclude '__pycache__' -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  new/bp_composition_diagnostic_v1/remote_bundle/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle_bp_composition_v1/
```

未加`--delete`，不会删除远程其他文件。首次上传或再次运行前，bundle的散列检查会检测不匹配文件。

## 2. 登录并运行

本地登录：

```bash
ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2 chenjiahao@36.102.215.18
```

然后在服务器执行（使用已分配给本任务的GPU；如改卡号，修改CUDA_VISIBLE_DEVICES）：

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
BP_COMPOSITION_BUNDLE=/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle_bp_composition_v1
BP_COMPOSITION_JOB="/raid/chenjiahao/mas/runs/bp_composition_v1_$(date +%Y%m%d-%H%M%S)_$$"
mkdir -p /raid/chenjiahao/mas/runs
printf '%s\n' "$BP_COMPOSITION_JOB" > /raid/chenjiahao/mas/runs/bp_composition_v1_latest.txt
nohup bash "$BP_COMPOSITION_BUNDLE/new/bp_composition_diagnostic_v1/launch_remote.sh" \
  "$BP_COMPOSITION_JOB" > "${BP_COMPOSITION_JOB}.nohup.log" 2>&1 < /dev/null &
tail -f "${BP_COMPOSITION_JOB}.nohup.log"
```

Ctrl-C退出tail不停止后台rollout。无需手动激活conda或预先启动vLLM。

启动脚本依次执行：独立bundle散列校验、题包校验、7项CPU回归、实际模型tokenizer的4096上下文预算检查，然后启动两台vLLM并完成96次正式调用。CPU回归中的HTTP调用是mock，不额外消耗GPU采样。

两张卡加载同一个4B模型，是两个推理副本；本次没有独立opponent，也不运行self-play。

服务配置沿用之前的双A100路径：V0、XFORMERS、CUDA11.8、BF16、TP=1、4096上下文、1024输出、每服务最多16序列、客户端总并发32、显存比例0.65、Hermes原生工具解析、关闭frontend multiprocessing、不强制eager。端口用18093/18094，避开旧默认18091/18092；端口被占会退出，不复用未知服务。

只清理本次启动并记录PID的服务和GPU监测进程，不执行ray stop、pkill或停止其他任务。

## 3. 查看进度与完成状态

重新登录后：

```bash
BP_COMPOSITION_JOB="$(cat /raid/chenjiahao/mas/runs/bp_composition_v1_latest.txt)"
tail -f "${BP_COMPOSITION_JOB}.nohup.log"
```

正常结束需要同时满足：

- `$BP_COMPOSITION_JOB/EXIT_CODE`内容为`0`。
- `$BP_COMPOSITION_JOB/run/evaluation/COMPLETE.json`存在。

准确率和合法率在`run/evaluation/summary.json`；逐条回答在`responses.jsonl`。另有`scored.jsonl`、`run_config.json`、`server-0.log`、`server-1.log`、`servers.json`、`gpu.csv`、`prompt_tokens.json`及启动耗时。COMPLETE表示收集与评分完整，不表示模型答对。

如果失败，先保留整个目录和nohup日志。`EXIT_CODE`、`run/LAUNCH_FAILED.json`、两台server日志或`evaluation/INCOMPLETE.json`会区分启动错误与请求失败；不会自动修改题目、预算或重试答案。

## 4. 下载结果（本地Mac）

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/bp_composition_v1
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/bp_composition_v1_latest.txt \
  new/local_data/social_runs/bp_composition_v1/latest.txt
BP_COMPOSITION_REMOTE="$(cat new/local_data/social_runs/bp_composition_v1/latest.txt)"
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  --exclude 'triton-*' --exclude '__pycache__' \
  "chenjiahao@36.102.215.18:${BP_COMPOSITION_REMOTE}/" \
  "new/local_data/social_runs/bp_composition_v1/$(basename "$BP_COMPOSITION_REMOTE")/"
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  "chenjiahao@36.102.215.18:${BP_COMPOSITION_REMOTE}.nohup.log" \
  new/local_data/social_runs/bp_composition_v1/
```

尚未在本次远程GPU上执行；本地已完成CPU回归、shell语法和隔离bundle导入/校验。之前成功的环境配置是复用依据，不是本次GPU运行成功的保证。
