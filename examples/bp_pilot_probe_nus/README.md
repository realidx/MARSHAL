# SoC 冻结 B/P 题库基线

复用此前成功的 `/home/e/e1300530/tmp/marshal-vllm09/bin/python` 和 Qwen3-4B-Instruct-2507 模型；不安装环境、不更新权重。只需提交并推送本目录，服务器无需 teacher/solver 依赖。

- Train：256 题，每题 8 次独立首次回答，共 2048 条。
- Validation：64 题，每题 4 次，共 256 条。
- Test：不导出、不请求。另有独立的 2 条接口预检，不混入正式 group。
- 原生工具、temperature .8、top_p 1、top_k -1、repetition_penalty 1、输出上限 1024，无 retry。
- 一张 Slurm `h100-47` GPU、4 个 HTTP workers；默认 context 5120、GPU memory .40。8 小时为排队任务时限，非耗时保证。

服务器仓库根目录：

```bash
cd /home/e/e1300530/MARSHAL
git pull --ff-only
BP_PYTHON=/home/e/e1300530/tmp/marshal-vllm09/bin/python \
  bash examples/bp_pilot_probe_nus/run_probe.sh --check
sbatch examples/bp_pilot_probe_nus/sbatch_probe.sh
```

路径有变化可在提交前设置 `BP_PYTHON`、`BP_MODEL`。其他覆盖变量与旧 probe 一致：`BP_PORT`（默认 18081）、`BP_WORKERS`（1–4）、`BP_GPU_MEMORY`、`BP_CONTEXT`、`BP_RUN_ROOT`。launcher 使用分配的 GPU，只停止自己启动的服务；不操作已有服务。

输出：`runs/bp_pilot_probe_nus/<jobid>.<suffix>/`。下载整个目录，包含 `bundle/`、`server_manifest.json`、`preflight/`、`train/`、`validation/` 和日志；`COMPLETE.json` 表示正式请求全部传输完成，不表示答案正确。错误、截断和协议失败照常保留，只有基础设施错误阻止该轮被标记为完成。

推送后的离线检查（无 GPU）：

```bash
python3 -m unittest discover -s examples/bp_pilot_probe_nus -p 'test_*.py'
```

下载后在本地仓库评分：

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.score_bp_pilot_probe \
  --run runs/bp_pilot_probe_nus/任务目录
```

评分校验冻结请求、采样器和原始教师数据哈希。结果写入新的 `local_scoring/`，不改变标签；中途结果可分析，但只将完整的 8/4 次回答计入 group 成功数直方图。

本目录由 `python -m training.b_sft.prepare_bp_pilot_probe` 从已审查题库导出。Teacher 标签不进入 bundle 或发送给模型的请求。使用 HTTP 原生工具路径复查题目和奖励；训练环境中的 vLLM/ROLL parser 及 GPU 更新仍由训练启动检查核验。
