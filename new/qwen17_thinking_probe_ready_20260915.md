# Qwen3-1.7B thinking 配对测试

仅推理测试。对照上一轮 `qwen17_probe_20260915-033340`，复用 28 道原 B/P、18 道 bridges、6 道简化 L0，每题 8 次；12 个真实 self-play 开局各 4 条轨迹。共 416 个正式 B/P 回答、4 个接口预检、48 条完整局尝试。所有题目与开局只来自 train/validation。

唯一有意改变的模型行为设置是开启 thinking；模型、题面、工具、奖励、seed、temperature/top_p/top_k、上下文、并发和输出预算不变。thinking 与最终答案共用 1024 输出 tokens；不追加答案预算，不增加重试或长度惩罚。

## 实现和验证

- 新 bundle：`examples/social_probe_20260915/remote_bundle_qwen17_thinking/`，旧 nonthinking bundle 不修改。
- 官方模板前固定 `enable_thinking=true`；本地 tokenizer 与服务器使用相同模板。不会附加原 nonthinking 的空 `<think>...</think>` 前缀。
- 服务器使用 `--enable-reasoning --reasoning-parser deepseek_r1` 配合原 `--tool-call-parser hermes`。vLLM 0.8.5 非流式路径先提取 reasoning，再仅从最终 content 提取工具。未闭合思考中的工具示例不会执行。
- 原始响应保留 `raw_message.reasoning_content`、`content` 和 `tool_calls`，不将 reasoning 合并成游戏消息或展示给其他玩家。分析入口已增加 reasoning_content 与任一解释字段，奖励不因此改变。
- 启动时检查本地模型 revision、配置/tokenizer hash 和权重分片存在，不联网下载模型、不安装依赖。两张卡各加载一个 TP=1 服务，所有测试阶段共用服务。
- 19 项离线回归检查通过；真实 tokenizer 检查 170 个题面/脚本决策输入与官方 `enable_thinking=True` 的 token IDs 一致；12 个脚本完整局回放通过。
- 服务器在模型加载前执行 `validate_thinking.py`：以现有实际 vLLM parser 处理完整 reasoning+tool、未结束 reasoning、无最终动作三个固定字符串，并检查非流式服务组合路径。该项需服务器执行，本地没有安装同一 vLLM/CUDA，未宣称已通过远程模型实测。

依据：[官方模型卡](https://huggingface.co/Qwen/Qwen3-1.7B)、[vLLM 0.8.5 非流式解析](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/entrypoints/openai/serving_chat.py)、[DeepSeek R1 reasoning parser](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/reasoning/deepseek_r1_reasoning_parser.py)。这次固定旧采样参数用于模式对照，不是在同时测试官方另推荐的一套采样参数。

## 本地上传

```bash
cd /Users/bruce/MARSHAL
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  examples/social_probe_20260915/remote_bundle_qwen17_thinking/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/examples/social_probe_20260915/remote_bundle_qwen17_thinking/
```

## 服务器启动

GPUs 6、7 应已由用户释放旧任务。Ctrl-C 退出 tail 不停止后台测试。

```bash
cd /raid/chenjiahao/mas
export CUDA_VISIBLE_DEVICES=6,7
export VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS
BP17T_JOB_DIR="/raid/chenjiahao/mas/runs/qwen17_thinking_$(date +%Y%m%d-%H%M%S)"
mkdir -p runs
printf '%s\n' "$BP17T_JOB_DIR" > runs/qwen17_thinking_latest.txt
nohup bash examples/social_probe_20260915/remote_bundle_qwen17_thinking/launch_qwen17_thinking.sh \
  "$BP17T_JOB_DIR" > "${BP17T_JOB_DIR}.nohup.log" 2>&1 < /dev/null &
tail -f "${BP17T_JOB_DIR}.nohup.log"
```

## 下载记录

以下在本地 Mac 执行，包括失败的部分结果；不下载权重。

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/qwen17_thinking
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/runs/qwen17_thinking_latest.txt \
  new/local_data/social_runs/qwen17_thinking/latest.txt
BP17T_REMOTE_DIR="$(cat new/local_data/social_runs/qwen17_thinking/latest.txt)"
rsync -avz -e 'ssh -p 2201 -i /Users/bruce/.ssh/id_rsa_dgx2' \
  --exclude 'triton-cache-*' --exclude '__pycache__' \
  "chenjiahao@36.102.215.18:${BP17T_REMOTE_DIR}/" \
  "new/local_data/social_runs/qwen17_thinking/$(basename "$BP17T_REMOTE_DIR")/"
```

检查 `EXIT_CODE`、`parser_check.json` 和 `probe/COMPLETE.json`，然后对照正确率、解释、截断、混合奖励组、self-play 正常终局率与有效 utility 分组。`COMPLETE` 不保证所有游戏到达终局，失败游戏的 utility 仍为 null。
