# v7p：标准训练 P 接口复测

本版只修复 P 的接口不一致，不重新选题。32 题、B/O 请求、teacher、评分及 gold/model belief 干预保留 v7 原版。原 v7 文件与结果不覆盖。

P 直接调用 `training.social_mixed.history_free_requests.request`，复用目标/状态表格、游戏规则、belief 字段解释、任务目标及原生行动工具。伙伴已知偏好转为单元素 belief；目标偏好使用 gold 或模型预测。自身偏好和当前绑定状态保留，不提供历史或数值 posterior。P_model 沿用训练的“正确 belief”措辞，以保证两种干预仅改变提供的 belief 内容；它不是声称模型预测客观正确。

B/O 仍为原 v7 诊断接口，本版不声称三种接口均与训练逐字一致。保留训练渲染器的既有说明，不添加最后回合不要调查等解题提示。原样复用渲染器也意味着本次改变不止一个字段定义，不能将效果单独归因于 favored 解释。

运行（两个 checkpoint 分别执行，使用相同服务配置）：

```bash
python -m new.diagnostic_v7p.experiment \
  --base-url http://localhost:8000/v1 \
  --model MODEL_NAME --checkpoint-hash CHECKPOINT_SHA256 \
  --output runs/diagnostic_v7p/MODEL_NAME \
  --max-tokens 4096 --concurrency 4 --repeats 1 --seed 42
```

启用与原测试相同的 batch-invariant 服务设置。共 128 次调用；本地未提交模型评测。请求示例见 `example_P_gold.json`。

核验：`python -m unittest new.diagnostic_v7p.test_interface`，覆盖所有32题的gold及两个替换belief，核验直接复用训练渲染器、工具一致、当前状态不变、无历史，以及原题完整保留。此检查不代替实际模型评测，不保证D提升。
