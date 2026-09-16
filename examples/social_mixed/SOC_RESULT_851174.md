# Mixed 851174 结果记录

日期：2026-09-16  
硬件：xgpi7，2 × H100-96  
配置：mixed，vLLM 0.28，Hermes parser；本任务运行时仍为 `enforce_eager=false`，V1 engine。

## 训练

- 完成 40 个 optimizer update：`step 0`–`step 39`。
- 收集 1,356 个 games，其中 1,290 个 terminal，terminal rate 为 95.13%。
- 40 行 metrics 均为有限值，没有 NaN/Inf；checkpoint 保存到 `checkpoint-39`。
- actor loss 从 `2.98e7`（早期异常大值）降到 `5.82`；KL 从 `7.28e9` 降到 `1.35e3`；grad norm 从 `1.04e11` 降到 `4.48e3`。
- 后期数值明显比早期稳定，但早期异常大值和后期仍偏大的 KL/grad norm 说明不能仅凭 loss 下降认定训练已经健康收敛。

## 验证

每个 checkpoint 使用固定的小规模 validation（4 个 games）。下面的 B/P 数值是代码记录的 mean reward，不是独立的大规模 exact-match accuracy。

| validation | B/all | P/all | terminal games | calls | length-truncated |
|---|---:|---:|---:|---:|---:|
| step 10 | 28.6% | 31.8% | 4/4 | 85 | 7 |
| step 20 | 21.4% | 18.2% | 4/4 | 78 | 1 |
| step 30 | 14.3% | 13.6% | 4/4 | 77 | 5 |
| step 40 | 28.6% | 13.6% | 4/4 | 78 | 3 |

验证完整性正常：16/16 个 validation games 完成，没有 validation 阶段崩溃。但指标没有显示明确的单调提升：B 在 step 40 回升，P 从 31.8% 降至 13.6% 后未恢复。每次仅 4 个 games，因此这只能作为 smoke validation，不能作为正式效果或泛化结论；本轮也没有 step-0 baseline。

## 结束原因与结论

step-40 validation 已完成，随后下一轮 rollout 在 vLLM V1 的 CUDA Graph 路径触发 `CUDA error: an illegal memory access was encountered`，任务退出。该错误不是 optimizer、checkpoint 或 validation 指标失败。

因此 851174 的结论是：训练和验证流程成功跑过 40 步，数值后期趋稳，但没有足够证据证明能力提升；任务未完成完整训练，不能作为正式 mixed 结果。后续重跑采用 `enforce_eager=true`，相关配置修复见 commit `83d9b86`。

原始产物：

- `/home/e/e1300530/social-train-release-v2-W7aJh3/runs/social_mixed/mixed-seed42-851174/metrics.jsonl`
- `/home/e/e1300530/social-train-release-v2-W7aJh3/runs/social_mixed/mixed-seed42-851174/validation/`
- `/home/e/e1300530/social-train-release-v2-W7aJh3/runs/social_mixed/mixed-seed42-851174/train.log`
