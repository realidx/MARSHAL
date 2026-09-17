> 当前迁移环境已改为 CalBench；C2C 仅保留历史开发代码。参见 [CALBENCH.md](CALBENCH.md)。CalBench 采用全员同模型团队；结构开发用 `--suite structures`。

# 最终评估链路的开发接入

当前优先 A（完整局，包括固定 LM 与 oracle 对手）和 C（C2C）；B 的 R/G/GB 诊断暂缓。当前只验证链路，不比较训练后模型，不运行正式测试。

## C2C：全本地默认，保留显式 API 配置

- 固定上游 commit `2f7eb4a163d21e139a3ea8b9f7d625b470594f00`，不修改上游游戏规则或提示。
- 新 runner 只接受 `stage=development, formal_test=false` 的计划，输出开发结果。
- 默认一张 A100-40G 提供 focal，另一张提供 Q0；四名玩家均来自本地 Qwen3-4B-Instruct-2507。三个 Q0 玩家共享推理服务，保留独立 agent/私有观察/事件历史。
- 原环境有额外的谈判摘要提取模型；同样显式路由到本地冻结 Q0。不是新增 judge，不调用外部分析模型。
- `c2c_local.json` 配置 focal/q0/summary 各自的 OpenAI-compatible chat-completions base_url、served model 与 API key 环境变量名。默认 `local_only=true`，非 loopback 地址被拒绝；使用外部 API 必须显式设置 false。不自动回退到 OpenRouter 等服务，不把 API key 写入日志。
- 保留原生 temperature（一般 .7，摘要 0），明确默认输出预算 1024；记录 seed、请求、响应、usage、finish_reason 和调用状态。JSON 解析保持上游对单元素 list 的兼容。
- 默认上下文 32768、每端点 max_num_seqs=4、TP=1、bf16、显存比例 .65。参数是待远端验证的起点，不声称已经通过显存/上下文验证。没有静默截断输入。
- 同一 board 的四次座位轮换保持 board_seed 和 shuffle_seed 不变，通过逆置换将 focal 放到对应 commander。避免轮换座位时顺便重新分配隐藏目标。
- 到达 50 轮上限但无赢家，单列 horizon_reached_without_winner，不当作自然胜负终局。所有模型请求错误/截断单列；摘要错误即使被原环境容忍，也留在 transport 日志和状态统计中。
- 不使用旧适配器中“提升 6% 就值得扩展”等筛选门槛。开发结果不用于按输赢筛选正式测试。

### 在 chenjiahao 服务器准备

已有环境：`/raid/chenjiahao/conda_envs/mas/bin/python`；模型 `/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507`；已有仓库 `/raid/chenjiahao/mas`。先同步本目录代码到独立 checkout/bundle，并确认上游 C2C 已存在且版本正确。不要调用旧的 SoC sbatch C2C 脚本。

准备上游固定 checkout（可处理已存在但没有 `.git` 的复制目录：先保留备份，再安装独立 checkout；不自动 pip 安装升级）：

```bash
/raid/chenjiahao/conda_envs/mas/bin/python -m examples.final_evaluation.setup_c2c
```

在已同步的新 checkout 根目录：

```bash
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
/raid/chenjiahao/conda_envs/mas/bin/python -m examples.final_evaluation.c2c_local prepare-dev \
  --boards 1 --seed-base 2026091700 --output runs/c2c-dev-plan.json
```

这生成一个开发初始局 × 四座位，不是正式的 8×4 测试。确认分配的两卡空闲后，设置 `CUDA_VISIBLE_DEVICES`（历史使用 6、7，不能据此假定仍可占用）。保持该变量为实际分配的两个 GPU 编号，再启动：

```bash
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export PATH="$CUDA_HOME/bin:$PATH"
export TRITON_PTXAS_PATH="$CUDA_HOME/bin/ptxas"
/raid/chenjiahao/conda_envs/mas/bin/python -u -m examples.final_evaluation.launch_c2c_local \
  --plan runs/c2c-dev-plan.json --output "runs/c2c-dev-$(date +%Y%m%d-%H%M%S)"
```

launcher 检查端口，启动两个自己拥有的服务，结束时只回收其进程组。不清理其他作业。仅当需要验证最短请求闭环时可显式 `--max-turns 1`，但这种运行不能算完整局已跑通。

若已有服务或采用 API，跳过 launcher，直接传路由配置：

```bash
/raid/chenjiahao/conda_envs/mas/bin/python -m examples.final_evaluation.c2c_local run-dev \
  --plan runs/c2c-dev-plan.json --routes examples/final_evaluation/c2c_local.json \
  --output runs/c2c-dev-existing-services
```

`EXIT_CODE=0` / `RUN_FINISHED.json` 只表示运行器结束；必须查看 `games/development_results.json`、各局 `transport.jsonl`、`error.json` 和原生 `game_states/` 判断是否正常结束、有没有模型协议/基础设施/上下文错误。

## A：oracle 对局的设计约束

固定 LM 对手条件保留 `[M,Q0,Q0]`。用户已确认：新增 oracle 使用与 LM 相同可见信息的 selected-policy teacher，绝不读取其他玩家的真实隐藏偏好；不是全知 oracle。

- 若使用相同信息 teacher，它依赖明确的行为似然与 off-path 约定；LM 的零概率行为如何处理必须先定义，不可自动跳过或假装 posterior 正常。
- teacher 的信息来源限定为公开历史、自己的偏好和自己获得的私有调查结果。评分端的真实偏好世界不能进入 teacher 的行动接口。
- 现有三人完整训练局常为每人 2 承诺、3 目标、6 或 12 个提案机会；精确全树 teacher 并未在此规模完整验证。不能把超时后的 greedy/MCTS 兜底标成 exact oracle。
- 不以模型表现选题，不为 oracle 能解而静默改变 A 的规模分布。若精确范围有限，oracle 子条件应单独说明范围。
- binary/linear 保留，mixed 完成规则排除；ID/OOD 分开，结构留出检查同时覆盖 B/P 与 self-play 训练来源。

## 本地验证

```bash
python -m pytest tests/agentic/test_final_c2c.py -q
```

已通过：端点默认全本地；外部 API 需显式开启；摘要路由也本地；四座位 seed/分配检查；原生 C2C 初始化中目标分配不随 focal seat 改变。尚未据此声称远端 GPU 对局已通过。

C2C development games now default to `--parallel-games 4` (available on both
`launch_c2c_local` and `c2c_local run-dev`). Workers use spawned processes to
isolate native RNG state and transport hooks; model servers are shared. Each
game retains its own history, seeds and logs. Completion progress is printed
and results are written after each finished game. Set `--parallel-games 1` for
serial execution. An already running process retains its old scheduling;
use a new output directory for a parallel rerun. Parallel batching can change
numerical model outputs even with fixed sampling seeds.

The all-Q0 launcher now explicitly declares its two endpoints equivalent and
assigns games evenly to replicas; all roles within each game use its assigned
replica. This is only appropriate when both endpoints serve the same checkpoint.
Standalone API routes retain role-based routing unless `equivalent_replicas` is
explicitly supplied. The launcher enables prefix caching, extends CUDA graph
capture to the configured context limit, and disables duplicate prompt logging
in vLLM. Transport logs still retain requests/responses and now record wall time.
These changes require a fresh launch; speedup has not yet been benchmarked.


2007041
2007042