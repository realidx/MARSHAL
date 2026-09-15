# 服务器运行命令：训练前社会判断审查

> 操作方式更新（2026-09-14，用户明确要求）：今后由主助手提供代码上传、采样或训练命令，用户在服务器执行；用户通知完成后，主助手下载结果并分析。不再委派 Luna 或其他子代理操作服务器，也不自行启动下一轮远程任务。Luna 已结束；停止子代理不等于关闭远程模型服务。本次 B/P 小课程采样结果见 `new/local_data/social_runs/bp_short_remote_probe_r1/analysis.md`，下文其他实验命令保留作历史记录，不能直接当作当前 B/P 课程入口。

> 当前目标已转为三组终局奖励对照（自由 reasoning、显式 B→P、显式 B→P 分支信用）。下文 v6 命令保留用于旧结果复现。新入口见本节；它目前只做冻结模型采样与记账验证，不更新参数。

## 新入口：三组冻结模型小测


当前 prompt 为 `social-native-tools-v3`：B/P 使用自然段，模型不计算 utility；三组理由最多 120 词，整体仍为 1024 token。先做下面的真实生成预检，查看 `calls.jsonl` 中实际文字再启动完整三组，不能只依据 `format_passed` 判断 B 内容有效。

```bash
cd /raid/chenjiahao/mas
/raid/chenjiahao/conda_envs/mas/bin/python -u -m training.b_sft.social_three_arm \
  --preflight --endpoint http://127.0.0.1:8000/v1 --model social-base \
  --tokenizer /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --output new/local_data/social_runs/social_native_tools_preflight_remote
```

预检正常为四次请求，失败最多沿用一次 retry 后停止；不占正式三组 rollout 预算。没有加入推理正确性奖励或重复惩罚。请先同步新版入口文件；远程旧文件不会自动更新。v3 已通过本地客户端连接远程 8001 的真实接口验证，源码尚未上传。8000 曾在验证 prompt logprobs 时 OOM，已在原 GPU 2 恢复；v3 最终实现使用 CPU /tokenize 校验，不再请求 prompt logprobs。

本地实现：`social_three_arm.py`。小测每组 24 个 rollout 槽位；正常情况下共 42 次生成请求，失败最多按一条 B/P 路径 retry 一次。全部输出上限为 1024 token，分支 P 扣除 B 的已用 token。不要在此小测结束后直接声称三组训练效果存在差异。

本地检查与脚本控制（输出目录必须不存在）：

```bash
python -m unittest training.b_sft.test_social_three_arm training.b_sft.test_social_coupled_credit training.b_sft.test_social_lm_eval
python -m training.b_sft.social_three_arm --scripted \
  --output new/local_data/social_runs/social_three_arm_scripted_check
```

本轮上传目前被自动审批拦截，获得新增文件上传授权后再执行以下命令。本地上传以下文件，不删除远程额外文件，不改变 vLLM 启动配置：

```bash
rsync -avz -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  training/b_sft/social_three_arm.py \
  training/b_sft/run_three_arm_parallel.sh \
  training/b_sft/social_coupled_credit.py \
  training/b_sft/social_presentation.py \
  training/b_sft/test_social_three_arm.py \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/training/b_sft/
```

三个已打开的 vLLM 服务分别绑定三张 GPU，且都提供相同的 `social-base` 模型时，在独立 tmux 窗口执行：

```bash
cd /raid/chenjiahao/mas
bash training/b_sft/run_three_arm_parallel.sh \
  new/local_data/social_runs/social_three_arm_remote_parallel_r1 \
  8000 8001 8002
```

端口依次对应 `free_outcome`、`bp_outcome`、`bp_branch`。脚本同时启动三个独立进程，每组内部顺序执行，不做组内并发。GPU 分配由既有 vLLM 服务决定，客户端脚本不会启动或重绑 GPU。模型、种子、题包和每组 24 个 rollout 槽位保持相同。每组写入自己的子目录和同名 `.log`；脚本等待三组结束，任何进程失败都会返回非零退出码。输出根目录必须不存在。

只运行一组时可直接使用 Python 入口的 `--arm free_outcome`、`--arm bp_outcome` 或 `--arm bp_branch`，配合该组 `--endpoint` 和独立 `--output`。省略 `--arm` 仍按旧方式顺序运行三组。

保留 `run_config.json`、`cases.json`、三组 `calls/rollouts/signals.jsonl` 和 `summary.json`。若基础设施失败，不把缺失收益当作 0；排查服务返回的实际 token ID/usage 一致性后使用新输出目录重跑。当前接口复用旧 SUBMIT_ACTION schema，通过原生 /chat/completions 的 message.tool_calls 接收动作；不解析 ACTION 标签、裸 JSON 或正文函数名。分支只在 B 自然段边界暂停。

---

本页命令已更新为 **v4 开发数据**，旧 v2 结果保留作历史诊断，不能与新分数直接比较。B 查询来自初始公开候选目录，模型必须逐项回答；公开已知偏好不能替代查询。教师的偏好集合依赖题面声明的有限窗口伙伴规则；只靠原生动作顺序排除类型的点关闭 B 监督，不能把这种排除教成一般理性结论。P 的终局收益独立计算；非终局 Q 明确是参考策略续局价值。

当前 prompt 版本为 `social-english-action-ids-v6`：B/P 的题目指令全部使用英文，要求先在普通正文中给出判断依据，再在同一回复中调用工具。P 将完整动作对象直接作为 SUBMIT_ACTION 的参数提交，例如 {"response":"ACCEPT"}；不再提交 action_index。每次调用保存 `reasoning_text` 和 `explanation_status`（present / missing / unavailable）。正文存在不代表理由正确；工具答案与说明是否存在分别统计。此修改在请求构造时生效，旧数据包保留；本轮使用 v4 样例和数据。v6 保持 B 偏好判断与 P 收益目标分开；自身偏好单列为带明确 player ID 的 own_preferences，goal 仅描述满足条件；状态、历史、合法动作和工具提交统一使用 action_0 等名称。程序严格匹配显示的合法动作后映射回原生动作，模型不再转换二进制向量。pending offer 明确标记为尚未生效。保留伙伴计划选择和平局规则，移除训练运行元数据。规则继续明确未满足的 goal 贡献 0、每位玩家分别对所有 goal 计分、当前 proposer 回合与后续回合的区别，以及 OFFER/MENU 类型。已有 `social_smoke_v4_r1` 使用的是 v3 prompt，不能当作本次修改的模型验证。

当前先跑通题面、生成、评分、B→P、失败处理和续局逻辑，不启动 PPO。B/P 每次输出上限均为 1024（含正文与工具参数），retry 仍为 1024，每阶段最多重试一次。截断、格式失败、服务错误分别记录；每次截断独立计 truncation_score=-1，其他模型回复为 0，服务错误不计；截断不叠加格式罚分。reward 为可用 task/format/truncation 分数之和，系数均为 1；合法答案缺少教师时 reward 屏蔽，服务错误也屏蔽。retry 不覆盖第一次的分数，也不把第一次的罚分加到 retry 的分数上。版本化约定保存在 run_config.json.scoring_contract；不判断 loop，不设置独立重复惩罚。合法但答错不重试。首次失败记录保留，不以重试成功覆盖。数据分布及 solver 监督是否符合训练能力目标，在正式训练前复查。

新版分别采样 P 规划题与 B 证据题，并保留全部候选、来源、排除依据、动作价值和掩码。当前仍是开发诊断数据；没有接入旧 B-only SFT，也没有实现新的 PPO 训练。旧包不能被新版运行器静默加载执行。

2026-09-11。沿用服务器 `/raid/chenjiahao/mas`、conda 环境 `/raid/chenjiahao/conda_envs/mas`、本地 SSH 密钥 `~/.ssh/id_rsa_dgx2` 和端口 2201。

沿用现有 `mas` conda 和已启动的 `social-base` 服务。当前启动命令针对 vLLM 0.8.5.post1+cu118；依赖安装与恢复记录见 [VLLM_SAME_CONDA.md](VLLM_SAME_CONDA.md)。已有可用服务时无需重新安装环境。

本次是 vLLM 推理服务 + CPU 环境/教师/评分脚本。配置均在命令行，运行器自动保存 `run_config.json`，没有额外 YAML/config 文件要填写。旧的 run_shared.sh、torchrun、DeepSpeed JSON、learning rate、batch、epochs、eval/checkpoint interval 均不用于此入口。


本轮先运行 `new/local_data/social_smoke_v4` 的 14 题：6 题在获得信息后继续规划，终局接受/拒绝各 2 题、MENU 两种选择各 1 题、无证据对照 2 题。首次共 28 次模型调用，计入每阶段最多一次 retry 后最多 56 次，不展开续局。新 P 主样本有 17 个信息后规划点，终局接受/拒绝各 6 个。B 的独立证据样本保留其自身分布。

prompt 现在明确解释二进制承诺向量，使用明确的 proposer/responder、按 goal ID 标注的偏好以及 setup/learner/partner 事件。B 必须提交 `{"judgments": [...]}`。失败 B 的原始指令和工具文本只保留在日志；P 收到不可用状态。不会用教师标签补答案。

## 1. 本地 Mac 上传

同步下面三个目录即可；training/b_sft 整体上传以避免漏掉间接依赖，BENAC src 包含规则、教师依赖和 HTTP 客户端。上传新版包及其完整轨迹和 social_smoke_v4；无需上传旧数据或本地 dry-run 结果。rsync 不删除远程额外文件。

```bash
cd /Users/bruce/MARSHAL

ssh -i "$HOME/.ssh/id_rsa_dgx2" -p 2201 chenjiahao@36.102.215.18 \
  'mkdir -p /raid/chenjiahao/mas/training/b_sft /raid/chenjiahao/mas/third_party/negotiation_benchmark/src /raid/chenjiahao/mas/new/local_data/social_generalization_v4'

rsync -avzP --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='debug/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  training/b_sft/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/training/b_sft/

rsync -avzP --exclude='__pycache__/' \
  -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  third_party/negotiation_benchmark/src/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/third_party/negotiation_benchmark/src/

rsync -avzP -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  new/local_data/social_generalization_v4/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/new/local_data/social_generalization_v4/
```


另外上传小批验证包（Mac 执行）：

```bash
rsync -avzP -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  new/local_data/social_smoke_v4/ \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/new/local_data/social_smoke_v4/
```

## 2. 登录、tmux 和依赖检查

```bash
ssh -i "$HOME/.ssh/id_rsa_dgx2" -p 2201 chenjiahao@36.102.215.18

tmux new -s social-review

cd /raid/chenjiahao/mas
conda activate /raid/chenjiahao/conda_envs/mas
mkdir -p outputs/logs

python -c 'import sys, numpy, vllm; print(sys.version); print("numpy", numpy.__version__); print("vllm", vllm.__version__)'

python - <<'PY'
from pathlib import Path
from training.b_sft.social_lm_eval import load_pack
summary, points = load_pack(Path('new/local_data/social_generalization_v4'))
print('Checksum/protocol OK:', len(points), 'points;', summary['independent_topologies'], 'structures')
PY

nvidia-smi --query-gpu=index,memory.total,memory.used,memory.free --format=csv
```

预计默认规划样本检查输出 `68 points; 10 structures`；B 证据样本为 55 点。若 mas 中没有 vLLM，仅推理服务窗口改用你之前安装 vLLM 的环境；测试脚本窗口仍可用 mas。不要为此自动升级整个训练环境。实际版本和可用显存以本次检查输出为准。

## 3. tmux 第一个窗口启动模型服务

下面的 GPU 1 是示例，必须改成你当前分配到的单张 GPU。单卡运行，无八卡分布式通信。0.35 是整张卡显存的预算比例，不是剩余空闲显存的 40%；共享机器上需结合上一步实际空闲显存调整。

```bash
export CUDA_VISIBLE_DEVICES=1

set -o pipefail
VLLM_USE_V1=0 \
VLLM_ATTENTION_BACKEND=XFORMERS \
TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas \
TRITON_CACHE_DIR=/raid/chenjiahao/mas/.cache/triton_vllm085_cu118 \
python -u -m vllm.entrypoints.openai.api_server \
  --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --served-model-name social-base \
  --host 127.0.0.1 --port 8000 \
  --tensor-parallel-size 1 \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.35 \
  --enforce-eager --disable-frontend-multiprocessing \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  2>&1 | tee outputs/logs/social_vllm.log
```

本命令针对 vLLM 0.8.5.post1+cu118。V0 环境变量直接绑定本次进程，不依赖另一个 tmux 窗口的 export；关闭 frontend multiprocessing 以让 V0 初始化错误直接显示。这不保证解决未知的 CUDA/依赖错误，但避免只看到 engine 子进程启动失败的包装异常。若日志仍进入 vllm/v1/engine，请先核对实际包版本和完整启动命令。

`hermes` 沿用仓库 Qwen3 命令，也与 [vLLM 的 Qwen 工具调用说明](https://docs.vllm.ai/en/stable/features/tool_calling/)一致。Instruct-2507 这里不配置 Thinking 模型的 reasoning parser。`max-model-len` 包含输入与输出；若服务报告上下文不足，应增加预算并重跑同一配置比较，不截断题目。

服务已在 8000 正确运行时可复用，不要再启动第二个占用相同端口的服务；客户端 `--model` 必须与 `/v1/models` 返回的名称一致。

## 4. 第二个 tmux 窗口运行测试

按 **Ctrl-b，再按 c** 新建窗口，第一个窗口的服务继续运行。

```bash
cd /raid/chenjiahao/mas
conda activate /raid/chenjiahao/conda_envs/mas
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2

curl --fail http://127.0.0.1:8000/v1/models
```

应返回包含 `social-base` 的模型列表。先运行一个结构的固定点，检查固定查询、普通文本说明、工具输出和评分链路。首轮不展开续局。

```bash
set -o pipefail
python -u -m training.b_sft.social_lm_eval \
  --data-dir new/local_data/social_smoke_v4 --cohort both \
  --output-dir outputs/social_smoke_v4_r1 \
  --workers 6 \
  --base-urls http://127.0.0.1:8000/v1 http://127.0.0.1:8001/v1 \
    http://127.0.0.1:8002/v1 http://127.0.0.1:8003/v1 \
    http://127.0.0.1:8004/v1 http://127.0.0.1:8005/v1 \
  --model social-base --b-max-tokens 1024 --p-max-tokens 1024 \
  --temperature 0 --timeout 180 --p-rollouts 2048 --p-seconds 30 \
  2>&1 | tee outputs/logs/social_smoke_v4_r1.log
```

上例复用六个已启动的服务。只有一个服务时改为 `--workers 1 --base-url http://127.0.0.1:8000/v1`，删除整段 `--base-urls`。先查看格式、逐项 reasoning 与 `post_evidence_planning`，不能只看总体准确率。

确认接口正常后，运行 68 个规划样本：

```bash
set -o pipefail
python -u -m training.b_sft.social_lm_eval \
  --data-dir new/local_data/social_generalization_v4 \
  --output-dir outputs/social_review_reasoning_planning_0911 \
  --base-url http://127.0.0.1:8000/v1 \
  --model social-base \
  --b-max-tokens 1024 \
  --p-max-tokens 1024 \
  --temperature 0 \
  --timeout 180 \
  --p-rollouts 2048 \
  --p-seconds 20 \
  2>&1 | tee outputs/logs/social_review_reasoning_planning_0911.log
```

规划样本共 136 次模型请求。B 证据样本须单独运行下面的命令，共 110 次请求；两组有重叠，不能相加当作独立题量。每题仍执行实际 B→P，P 收到格式正确的模型 B（错误判断也保留）；格式无效时只传不可用状态。若另行使用 `--continue-game --roots-only`，会增加实际续局调用；这不是 B→P 因果实验。

```bash
set -o pipefail
python -u -m training.b_sft.social_lm_eval \
  --data-dir new/local_data/social_generalization_v4 \
  --cohort belief \
  --output-dir outputs/social_review_reasoning_belief_0911 \
  --base-url http://127.0.0.1:8000/v1 \
  --model social-base \
  --b-max-tokens 1024 --p-max-tokens 1024 \
  --temperature 0 --timeout 180 \
  --p-rollouts 2048 --p-seconds 20 \
  2>&1 | tee outputs/logs/social_review_reasoning_belief_0911.log
```

优先看 B 的 `B_required_exact_rate`、`B_support_macro_exact_rate`、`B_protocol_errors`；P 看 `planning_discriminating`，再对照 `by_value_basis` 的简单终局结果。推理文字是否存在只由 `B/P_reasoning_present_rate` 报告，不等同于推理正确。

## 5. 参数如何调整

| 参数 | 本轮值 | 含义 |
|---|---:|---|
| CUDA_VISIBLE_DEVICES | 自行指定一张 | 推理服务使用的 GPU |
| gpu-memory-utilization | 0.35 | 按整张 GPU 容量计算的预算，需适应共享显存 |
| max-model-len | 16384 | 每次请求的输入与输出总 token 上限 |
| max-num-seqs | 1 | 每个服务同时处理的序列上限；多卡模式每个端点分配一个 worker |
| b-max-tokens / p-max-tokens | 1024 / 1024 | 各自输出预算，包含普通文本与工具调用；不是强制推理长度 |
| temperature | 0 | 首轮固定解码；base/训练后模型使用相同设置 |
| p-rollouts / p-seconds | 2048 / 20 | 教师对候选动作的后续比较预算；超出则评分留空 |
| timeout | 180 | 单次模型请求最多等待的秒数 |
| source | evidence-430206 | 指定结构；删除该参数则检查全部结构 |
| continue-game + roots-only | 首轮不启用 | 固定题全部检查，仅从结构起点展开续局 |

没有手动 config 文件；每次运行自动写 `run_config.json`，包含这些参数、数据及实现的哈希。输出目录必须是新的；重新跑时将输出名改为 `_r2`，不要复用已有目录。

## 6. 途中查看、断线重连与下载

另一个终端可查看：

```bash
tail -f /raid/chenjiahao/mas/outputs/logs/social_smoke_v4_r1.log
```

`calls.jsonl` 每次模型请求完成后保存，`events.jsonl` 每次实际动作完成后保存；`summary.json` 每完成一个固定点及该点请求的续局后更新。`REVIEW.md` 在正常结束时生成，逐点 JSON 提前写在 `review/`。

按 **Ctrl-b，再按 d** 离开 tmux。SSH 断开后重新登录，再执行：

```bash
tmux attach -t social-review
```

下载在 **Mac** 执行；下载整个结果目录，保留 config、原始调用、评分和轨迹：

```bash
cd /Users/bruce/MARSHAL
mkdir -p new/local_data/social_runs/social_smoke_v4_r1

rsync -avzP -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/outputs/social_smoke_v4_r1/ \
  new/local_data/social_runs/social_smoke_v4_r1/
```

全量结果将两端目录名换成 `social_review_reasoning_planning_0911` 或 `social_review_reasoning_belief_0911`。优先看 REVIEW.md / summary.json；具体问题看 review/<id>.json 和 calls.jsonl。旧 83 点静态包不适用这个在线入口。

## 并行加速：多个 GPU 副本

运行器新增 `--workers`、`--base-urls` 和 `--cohort both`。独立进程分别回放环境、调用模型及评分；每个进程固定使用一个端点，只有主进程写共享日志。同一题始终先 B 后 P，续局按原来的回合顺序执行；不同题及其续局可并行。相同端点分配多个 worker 时，需要提高该服务的 `--max-num-seqs` 并检查显存。

`both` 对 110 个唯一决策点首次调用 220 次模型，含 retry 最多 440 次，重叠的 13 个点仅运行一次。`summary.json.by_cohort.belief` 和 `.planning` 分别保留 55 / 68 点的指标，不把合并总体当作某一个分组的分数。选择 `--limit` 时分组统计仅涵盖实际选中的点。

以下示例为全部重启：先停止本任务现有的 social-base 服务，再将 GPU 0–7 映射到端口 8000–8007。假设这八张卡均已分配给你；按实际分配修改 `gpu_ids`。原 GPU 1 / 端口 8000 的实例也必须先停止，以免同一张卡重复加载。使用当前已验证的单卡环境参数，不启用多卡 tensor parallel。

先按本页上传命令重新同步 `training/b_sft/`；此次无需重新上传数据。以下在服务器的 mas 环境运行：

```bash
cd /raid/chenjiahao/mas
conda activate /raid/chenjiahao/conda_envs/mas
mkdir -p outputs/logs

gpu_ids=(2 3 4 5 6 7)
port=8000
for gpu_id in "${gpu_ids[@]}"; do
  nohup env CUDA_VISIBLE_DEVICES="$gpu_id" \
    VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS \
    TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas \
    TRITON_CACHE_DIR="/raid/chenjiahao/mas/.cache/triton_vllm085_gpu_${gpu_id}" \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    python -u -m vllm.entrypoints.openai.api_server \
      --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
      --served-model-name social-base \
      --host 127.0.0.1 --port "$port" \
      --tensor-parallel-size 1 --dtype bfloat16 \
      --max-model-len 16384 --max-num-seqs 1 \
      --gpu-memory-utilization 0.35 \
      --enforce-eager --disable-frontend-multiprocessing \
      --enable-auto-tool-choice --tool-call-parser hermes \
      > "outputs/logs/social_vllm_${port}.log" 2>&1 &
  echo "$!" > "outputs/logs/social_vllm_${port}.pid"
  port=$((port + 1))
done
```

等待各服务启动后检查；每个端口都应返回 `social-base`：

```bash
for port in 8000 8001 8002 8003 8004 8005 8006 8007; do
  curl --fail --max-time 5 "http://127.0.0.1:${port}/v1/models"
done
```

开始新的合并测试，输出目录必须不存在：

```bash
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
set -o pipefail
python -u -m training.b_sft.social_lm_eval \
  --data-dir new/local_data/social_generalization_v4 \
  --cohort both --workers 6 \
  --base-urls \
    http://127.0.0.1:8000/v1 http://127.0.0.1:8001/v1 \
    http://127.0.0.1:8002/v1 http://127.0.0.1:8003/v1 \
    http://127.0.0.1:8004/v1 http://127.0.0.1:8005/v1 \
  --model social-base \
  --output-dir outputs/social_reasoning_parallel6_r1 \
  --b-max-tokens 1024 --p-max-tokens 1024 \
  --temperature 0 --timeout 180 \
  --p-rollouts 2048 --p-seconds 20 \
  2>&1 | tee outputs/logs/social_reasoning_parallel8_r1.log
```

可先加入 `--limit 8` 并换一个 smoke 输出目录。只有四张卡时，使用四个端点和 `--workers 4`。已有旧测试结果不会自动恢复或复用，勿覆盖旧目录。以后添加 `--continue-game --roots-only` 时，不同起点及其续局也会并行；一个起点内部的兼容世界仍按顺序处理，长续局可能产生尾部等待。

若每个完整决策点约 100 秒，110 个点使用八个 worker 的理想估计约 23 分钟；实际取决于 GPU 负载、CPU 教师耗时及任务长度。更多 GPU 提升总吞吐，不保证单次生成变快。进度日志分别显示 B 调用、P 调用和教师评分的耗时；并行时也应检查教师不可用率。



gpu_ids=(4 5 6 7)
for i in "${!gpu_ids[@]}"; do
  gpu_id="${gpu_ids[$i]}"
  port=$((8000 + i))

  nohup env \
    CUDA_VISIBLE_DEVICES="$gpu_id" \
    VLLM_USE_V1=0 \
    VLLM_ATTENTION_BACKEND=XFORMERS \
    TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas \
    TRITON_CACHE_DIR="/raid/chenjiahao/mas/.cache/triton_vllm085_gpu_${gpu_id}" \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    /raid/chenjiahao/conda_envs/mas/bin/python -u \
      -m vllm.entrypoints.openai.api_server \
      --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
      --served-model-name social-base \
      --host 127.0.0.1 --port "$port" \
      --tensor-parallel-size 1 --dtype bfloat16 \
      --max-model-len 16384 --max-num-seqs 1 \
      --gpu-memory-utilization 0.80 \
      --enforce-eager --disable-frontend-multiprocessing \
      --enable-auto-tool-choice --tool-call-parser hermes \
      > "outputs/logs/social_vllm_${port}.log" 2>&1 &

  echo "$!" > "outputs/logs/social_vllm_${port}.pid"
done

for port in 8000 8001 8002 8003; do
  echo "Port: $port"
  curl --fail --max-time 5 "http://127.0.0.1:${port}/v1/models"
  echo
done
## 当前 B-only 评估（bounded oracle v3 curriculum）

先同步 `training/b_sft/`、`third_party/negotiation_benchmark/src/` 和
`new/local_data/social_runs/b_curriculum_eval_v1/` 到服务器对应目录；尤其需要同步
`methods/vllm_client.py`，其现在保留连续对话中的原生工具调用字段。
四个已启动的 social-base 服务各分配一个 worker，无需另设 workers。

```bash
cd /raid/chenjiahao/mas
/raid/chenjiahao/conda_envs/mas/bin/python -u -m training.b_sft.run_social_b_eval \
  --data-dir new/local_data/social_runs/b_curriculum_eval_v1 \
  --output-dir new/local_data/social_runs/b_eval_native_r1 \
  --mode both --split all --temperature 0.7 --timeout 180 \
  --model social-base \
  --base-urls http://127.0.0.1:8000/v1 http://127.0.0.1:8001/v1 \
              http://127.0.0.1:8002/v1 http://127.0.0.1:8003/v1
```

输出目录必须不存在。`--split all` 是首轮开发集诊断，不是未见测试集上的论文结果。
`--limit N` 会分别限制每种模式的完整任务数，连续历史不截断。
每个 checkpoint 的首次与唯一 retry 共用 1024 token；未知 usage 的服务失败不自动重发。
首次/最终指标和全部失败分别保存；无模型参数更新。

## B-only GRPO首轮参数更新

当前代码已同步，隔离环境`.venv-b-grpo`已准备，不替换mas中的vLLM。
已核对评估端口8000–8003使用物理GPU4、5、6、7。
在服务器tmux执行：

```bash
cd /raid/chenjiahao/mas
.venv-b-grpo/bin/python training/b_sft/stop_b_eval_servers.py
bash training/b_sft/run_b_grpo.sh
```

第一条仅停止PID记录验证匹配的本任务评估服务；第二条检查显存后启动。
10步骤、每步4题×8采样、学习率1e-6、KL0.01、生成1024，无训练retry。
为兼容现有CUDA11.8环境，本轮ROLL rollout使用HF generate，保留原生模板与Hermes工具解析。
日志/manifest/原生奖励记录/checkpoint在`outputs/social_b_grpo_r1/`。
若自己的四张卡改变，先显式设置`export SOCIAL_GRPO_GPUS=新的四个物理编号`；不要选择别人的卡。
GPU端到端尚未验证；CPU预检不能替代实际backward和checkpoint验证。


### B GRPO 最新入口：原 mas 环境 + vLLM（2026-09-12）

替代上述`.venv-b-grpo`/HF采样命令。准备脚本`setup_b_grpo_env.sh`已改为原mas补充固定的缺失ROLL依赖，不更换torch/vLLM/Ray/CUDA/NumPy，并提取独立的cu11 NCCL库。当前服务器已完成准备；四卡NCCL标量通信通过。训练由用户启动：

```bash
cd /raid/chenjiahao/mas
bash training/b_sft/run_b_grpo.sh
```

物理GPU4–7；结果`outputs/social_b_grpo_vllm_r1`，完整主进程日志`driver.log`。launcher先做端口、GPU、依赖与四卡通信检查再创建结果目录。保留之前失败目录，无需删除。未来在相同环境重新准备可运行`bash training/b_sft/setup_b_grpo_env.sh`；不再使用或修复`.venv-b-grpo`。

最终检查：原mas下四卡NCCL通过；单卡vLLM原生调用、可逆权重RPC和常驻offload/load循环通过且退出码0。采样GPU独占，enable_sleep_mode=false，避免已实测发现的CUDAPluggableAllocator退出错误；不升级驱动或推理核心依赖。训练尚未启动。

Ray2.58日志监听器兼容修复已同步，并通过真实日志文件转发CPU测试；启动器支持核验并复用本次失败留下的指定地址Ray head。MULTI_TENANT下退出不再调用全局ray stop --force。不需要重装或降级Ray。

已修复linear scheduler被错误传入min_lr的问题；启动预检在模型加载前执行训练共用scheduler构造与完整CPU调度。保持linear及现有warmup设置，不降级依赖；训练仍由用户启动。

当前B使用DynamicSamplingScheduler，generate_opt_level已修正为1，显式保持is_num_return_sequences_expand=false。训练8条与验证1条的实际请求展开检查已加入模型加载前CPU预检，不更换后端或训练框架。


2026-09-12 首次10-step结果已下载审查：本地 `new/local_data/social_runs/b_grpo_vllm_r1/`，详见 DATA_SUPERVISION_REVIEW.md §31。320训练请求317合法，参数抽查证实更新；验证仅覆盖初始和第5次更新后（16/56→21/56），尚无最终模型评估。远程 `outputs/social_b_grpo_vllm_r1/checkpoints/checkpoint-9` 汇总复制不完整，禁止直接当作完整checkpoint使用；`actor_train-0/checkpoint-9` 的两片HF权重可读取，两个 actor_train 目录各自保存对应rank状态，应保留这些源文件。未启动新任务或修复复制。CPU检查细节已下载 parameter_audit.json、native_token_audit.json、checkpoint_audit.json。


2026-09-12 六卡正式B入口（详见分析§32）：配置 grpo.yaml，输出 outputs/social_b_grpo_b_r2，物理GPU0,1,4,5训练ZeRO2/GPU Adam，GPU6 vLLM、GPU7 reference，各角色常驻。默认60步×32条；只初始及最终验证，最后同步保存checkpoint-59并发布COMPLETE.json，不另跑GPU smoke。新Ray端口26380，不重启其他服务。CPU配置及保存逻辑检查、原环境FusedAdam编译导入已完成，尚未运行六卡模型更新，性能/峰值未实测。

旧最终checkpoint已恢复到 outputs/social_b_grpo_vllm_r1/checkpoints/checkpoint-9-recovered，原目录和源文件保留。正式代码仍由用户上传：本地打包 new/local_data/social_runs/b_grpo_b_r2_ready/b_grpo_b_r2_code.tar.gz；远程在 /raid/chenjiahao/mas 解包后执行 bash training/b_sft/run_b_grpo.sh。助手本轮只在 /tmp 下放置检查副本，没有覆盖正式训练源码或启动训练。


2026-09-12 B r2最终结果已下载至 new/local_data/social_runs/b_grpo_b_r2_final/；60步完成，总5小时7分51秒，最终checkpoint-59完成清单及实际文件复核通过，权重CPU抽查确认更新。固定validation全题24/56→21/56，尚无提升证据，输出全集38→54/68，详见分析§34；不能把本次训练reward上涨写成B泛化改善。无新训练或GPU评估。
