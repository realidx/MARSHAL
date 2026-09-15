# Qwen3-1.7B：复用既有小规模测试

本轮只做推理测试，不启动训练，不切换训练框架。使用 Qwen/Qwen3-1.7B，固定 revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`。它是 Qwen3-1.7B 发布模型，不是名称带 Base 的另一个 checkpoint。

## 测试内容

| 阶段 | 条件数 | 每条件次数 | 总数 |
| --- | ---: | ---: | ---: |
| 原 B/P 抽样 | 28 | 8 | 224 个回答 |
| B bridges 抽样 | 18 | 8 | 144 个回答 |
| 最新简化 L0 | 6 | 8 | 48 个回答 |
| 原 self-play 开局 | 12 | 4 | 48 个完整局尝试 |

正式 B/P 类回答共 416 个，此外两台服务各 2 次接口预检，共 4 个回答。全部来自 train/validation；标签留在本地，self-play 隐藏世界仅进入环境。B/P 独立 seed 按 task_id、sample_index 和 base 20260916 派生；self-play 继续 seed 42。不同阶段分别分析，不能把重复或相关教学状态当独立策略场景。

## 推理配置

- 两张 GPU 各一个 TP=1 vLLM HTTP 服务，CUDA graphs，每服务最多 16 活跃序列；客户端总并发 32。所有阶段复用一次服务初始化。
- 复用之前成功的 V0/XFORMERS/CUDA 11.8 路径；不进入 ROLL、Ray actor、DeepSpeed 初始化，不安装依赖。
- 保持 BF16、16384 context、1024 输出预算、原生工具、原题面中的解释要求。
- 显式 nonthinking：在官方工具模板前固定 `enable_thinking=false`；本地计数和服务端使用同一个模板。模型仍可在普通 content 中输出解释。
- B/P 保留请求中的 temperature=.8、top_p=1、top_k=-1 等参数；self-play 保留 temperature=.7、top_p=.8、top_k=20。使用旧实测的 generation_config 固定服务默认值，避免继承 1.7B 新默认值。
- 保持 B/P 二元任务奖励、不 retry、不增加长度惩罚；self-play 继续原有私有调查、真实开局、终局 utility 和单独记录的协议扣分/重试规则。

官方依据：[Qwen3-1.7B 模型说明](https://huggingface.co/Qwen/Qwen3-1.7B)、[vLLM 0.8.5 的 generation-config 参数](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/engine/arg_utils.py)。不把这次 4B → 1.7B 的表现差异全部归因于参数量：发布 checkpoint 与模型模板也有差异。

## 已完成验证

- 17 项离线测试通过，含旧 bundle 回归、错误模型拒绝、分阶段采样计数和 seed 检查。
- 冻结的 self-play runtime：12/12 脚本完整局 terminal，回放核验通过。
- 使用官方真实 tokenizer，对 52 个题面和 12 局的 118 个决策状态（共 170 个输入）验证有效模板与官方 `enable_thinking=False` 生成的 token IDs 完全一致；最大 prompt 为 1810 tokens。模型自己的后续状态仍在每次调用前独立检查 context。
- shell 语法通过。尚未远程加载权重或测试 GPU，不能据此保证远程运行不报错。

## 命令

本地上传独立 bundle，无需同步整个仓库：

```bash
cd /Users/bruce/MARSHAL
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  examples/social_probe_20260915/remote_bundle_qwen17/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle_qwen17/
```

服务器上运行；GPUs 6、7 应已由用户释放旧失败任务：

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
BP17_JOB_DIR="/raid/chenjiahao/mas/runs/qwen17_probe_$(date +%Y%m%d-%H%M%S)"
mkdir -p runs
printf '%s\n' "$BP17_JOB_DIR" > runs/qwen17_probe_latest.txt
nohup bash examples/social_probe_20260915/remote_bundle_qwen17/launch_qwen17.sh \
  "$BP17_JOB_DIR" > "${BP17_JOB_DIR}.nohup.log" 2>&1 < /dev/null &
tail -f "${BP17_JOB_DIR}.nohup.log"
```

脚本先做不加载模型的 bundle 检查，再通过现有 huggingface_hub 下载固定模型到 `models/Qwen3-1.7B`，最后启动两台服务并顺序执行全部测试。下载可复用已有缓存。Ctrl-C 退出 tail 不停止后台测试。不自动结束其他任务或服务。

完成标志：`$BP17_JOB_DIR/EXIT_CODE` 为 0，且 `probe/COMPLETE.json` 存在。目录内保留 launcher、两台 server 日志、startup 秒数、逐题/逐局原始结果、分阶段性能采样。`COMPLETE` 只说明采样收集完成，不表示标签正确或奖励足够。

本地下载（包括失败的部分结果）：

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/qwen17_probe
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/qwen17_probe_latest.txt \
  new/local_data/social_runs/qwen17_probe/latest.txt
BP17_REMOTE_DIR="$(cat new/local_data/social_runs/qwen17_probe/latest.txt)"
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  --exclude 'triton-cache-*' --exclude '__pycache__' \
  "chenjiahao@36.102.215.18:${BP17_REMOTE_DIR}/" \
  "new/local_data/social_runs/qwen17_probe/$(basename "$BP17_REMOTE_DIR")/"
```

## 结果分析及混训讨论

先检查基础设施失败、工具完成率、截断率、B/P 分层正确率和奖励混合组比例；self-play 单独检查同开局同玩家位置的 utility 方差，区分策略收益和纯协议扣分差异。用题面与独立核验反查标签。记录服务初始化时间、阶段耗时、输出 tokens/s、GPU 和 vLLM 队列；单独 HTTP 的吞吐不等于 ROLL 训练采样吞吐，也不能证明旧慢采样根因已解决。

混训可行，但需要两套 rollout/奖励分组接入同一策略。B/P 按同一道题分组；self-play 按同一开局和玩家位置分组，不把二元分数与终局收益直接合并标准化。明确混合比例是更新次数、样本数、生成 token 数还是损失权重；一局含多个玩家和决策，题数/局数比例不是梯度比例。loss 还需控制长轨迹权重，仅训练模型生成的 token。

初次实现可优先考虑按比例交替 B/P 与 self-play 更新，统一一套模型/优化器，完整局内保持采样策略固定；比分散在同一更新中更容易检查数据和回报归属。具体比例待测试后讨论，不在本轮预先锁定或实施。教学残局始终只用于 B/P，self-play 不因此改用教学状态。
