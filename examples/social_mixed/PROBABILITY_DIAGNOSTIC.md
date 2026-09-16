# mixed-851174 概率诊断

在新提交的干净 Git worktree 中运行：

```bash
bash examples/social_mixed/diagnose_probabilities.sh h100-96
```

首选复现原作业的双H100-96/TP2；若只有单H200，参数改h200-141，但这不能排除TP2特有故障。

只提交一个 mixed 诊断作业，沿用训练环境、初始化、模型和eager配置。不跑完整游戏、不保存训练checkpoint。固定三条真实B/P/SP回答，输出同token的HF reference、Megatron、vLLM概率。检查batch/单条、同步前后、sleep/wake前后。初始出现严重差异时停止；否则做一次抛弃式合成梯度更新，再查reference稳定性和同步。这个更新只测接口，不作科研结果。

HF reference以原HF checkpoint为基准，vLLM同步前也独立加载HF；不是另加载第四个模型。vLLM用prompt_logprobs进行teacher forcing，不重新生成答案。不能完全替代decode路径诊断。概率一致仅说明本次固定样本上的数值行为，非完整模型等价证明。

本地检查实际make_batch因果移位、mask、trim、排序还原和weighted_objective；尚未执行远程CUDA诊断。mean>.1或max>5为避免错误更新的粗错误门槛，不是后端一致性的认证标准。

下载该job整个运行目录（无需模型）：主要文件probability_diagnostic/report.json、tokens.jsonl、train.log、phases.jsonl、resolved_config.json、experiment.json、EXIT_CODE。tokens.jsonl包含每个token文本、三方概率和KL贡献；report逐阶段落盘，失败也保留此前记录。

判断：初始HF与原vLLM相近、Megatron不同，优先查转换/训练前向；初始相近而同步后不同，查同步；仅sleep/wake后不同，查状态恢复；仅batch不同，查padding/分发/结果顺序。即使三方都接近也需核对训练loss重算与原始异常样本。
