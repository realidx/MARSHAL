# 在 SoC Slurm 上运行冻结 CalBench 迁移测试

状态：本地适配及模拟启动测试通过；没有登录 SoC，没有在 SoC GPU 上验证。以开发作业结果为准。

## 与 chenjiahao 的区别

- 沿用 SoC `marshal-vllm09` Conda 环境和 vLLM 0.28.0/V1；继承该环境 CUDA toolkit，不设置 CUDA 11.8 或旧 ptxas。
- 不固定 GPU 编号；完全使用 Slurm 的 CUDA_VISIBLE_DEVICES。h100-96 两卡各一个 TP1 模型副本，2局并行；h200-141 一卡一个副本，1局运行。
- 保留已有 SoC eager 运行选择；不传 V0、XFORMERS 或旧版 frontend/CUDA graph 参数。
- 本评估不需要训练用 Ray、Megatron、权重同步、optimizer 或 reference worker。计算节点启动 loopback HTTP 推理服务，独立 CalBench venv 调用，既保留现有 API 接口，也隔离游戏依赖。
- 日历、原生 prompt、动作规则和评分保持不变；默认4096生成预算，32k上下文，4轮交流。包含思考包装解析修复。可显式选择768，记录实际条件。
- 使用不同 vLLM/硬件不保证逐token相同。执行身份记录版本、模型哈希及脚本哈希；跨集群结果需注明运行栈。

## 1. 准备独立 checkout

先在 Mac 按自己的 Git 流程提交并 push 本次文件；确认已包含 calbench_frozen_v1、calbench_formal.py、calbench_local.py、launch_calbench_local.py、两个 SoC shell 脚本、requirements 和 source manifest。不要把本地 runs 结果提交。

SoC 登录节点，在已有仓库中执行（按实际分支替换 origin/new）：

```bash
git fetch origin
CALBENCH_COMMIT=$(git rev-parse origin/new)
CALBENCH_WORKTREE="${PWD}-calbench-${CALBENCH_COMMIT:0:12}-$(date +%Y%m%d-%H%M%S)"
git worktree add --detach "$CALBENCH_WORKTREE" "$CALBENCH_COMMIT"
cd "$CALBENCH_WORKTREE"
source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
```

排队和执行期间保持此目录不变。不会修改已有训练目录或正在运行的训练进程。

## 2. 游戏源码与独立依赖（登录节点，仅一次）

```bash
python -m venv .venv-calbench
.venv-calbench/bin/python -m pip install -r examples/final_evaluation/calbench_requirements.txt
.venv-calbench/bin/python -m examples.final_evaluation.setup_calbench
.venv-calbench/bin/python -m examples.final_evaluation.calbench_formal \
  --verify examples/final_evaluation/calbench_frozen_v1
.venv-calbench/bin/python -m examples.final_evaluation.calbench_development_cases
```

最后一步是无模型原生回放，不占GPU。不要在登录节点启动vLLM。不要把requirements装进训练Conda环境。

若匿名站下载不可用或上游已变更：使用 Mac 侧生成的同一固定源码包 `runs/calbench-pinned-source.zip`，经 stujump 上传到 `/home/e/e1300530/calbench-pinned-source.zip`，然后：

```bash
.venv-calbench/bin/python -m examples.final_evaluation.setup_calbench \
  --archive /home/e/e1300530/calbench-pinned-source.zip
```

安装器逐文件核验原始固定源码哈希，不放宽版本检查。源码zip和venv不随Git传播。

## 3. 模型位置

默认目录 `/home/e/e1300530/models`：

- q0 → Qwen3-4B-Instruct-2507
- marshal → MARSHAL-Generalist-Qwen3-4B
- socialr1 → SocialR1-4B

可设置 `CALBENCH_MODEL_ROOT` 为其他模型父目录。在登录节点按既有 Hugging Face 下载方式准备模型，保留 download_revision.json；也可传已有模型绝对路径。不要将原生 Megatron 训练 checkpoint 目录直接当成 HF 模型：本入口需要 config.json、完整可加载权重和tokenizer。尚未适配原生 checkpoint 导出。

## 4. 先跑开发检查

```bash
bash examples/final_evaluation/submit_calbench_soc.sh h100-96 q0 structures 4096
```

单H200替代命令（选一条）：

```bash
bash examples/final_evaluation/submit_calbench_soc.sh h200-141 q0 structures 4096
```

查看 `sbatch` 输出的 job ID：

```bash
squeue -u "$USER"
tail -f slurm-calbench-q0-JOBID.out
```

作业完成后：

```bash
CALBENCH_RUN=$(cat runs/calbench_soc/q0-structures.latest)
cat "$CALBENCH_RUN/EXIT_CODE"
cat "$CALBENCH_RUN/games/RUN_FINISHED.json"
```

期望 EXIT_CODE=0、healthy_transport=true；会议是否成功不决定接口是否跑通。失败查看 Slurm 日志、server-0.log/server-1.log、LAUNCH_FAILED.json；作业在launcher之前失败时可能没有EXIT_CODE。不要根据开发题成绩调整正式场景。

## 5. 正式测试

开发检查通过后，按需分别提交：

```bash
bash examples/final_evaluation/submit_calbench_soc.sh h100-96 marshal formal 4096
bash examples/final_evaluation/submit_calbench_soc.sh h100-96 socialr1 formal 4096
```

每个作业独立申请两张GPU；同时提交意味着可能占用四张GPU。若仅使用两张，等第一项完成后提交第二项。改h200-141即可单卡运行。

当前用户选择：只重跑MARSHAL/Social-R1，Q0保留chenjiahao的768预算结果。上面的SoC Q0 structures只是基础设施检查，不是Q0正式重跑。若以后明确需要SoC同栈Q0正式对照，可用 `... q0 formal 768` 或预先声明4096条件；不要混淆预算。

训练后HF模型示例：

```bash
CALBENCH_LABEL=mixed bash examples/final_evaluation/submit_calbench_soc.sh \
  h100-96 /absolute/path/to/exported-hf-model formal 4096
```

所有正式作业使用同一冻结12局，独立输出目录，不覆盖旧结果；基础设施故障停止后续批次，不将其计作模型零分。基于Slurm job ID选择端口；若与已有服务冲突则报错，不杀其他进程。

## 6. 下载

在SoC仓库中打包实际run目录（将占位路径换成latest文件给出的目录），包括对应Slurm日志：

```bash
tar -czf calbench-soc-results.tar.gz runs/calbench_soc/MODEL-formal-JOBID slurm-calbench-MODEL-JOBID.out
```

Mac：

```bash
scp -J e1300530@stujump.comp.nus.edu.sg \
  e1300530@xlogin.comp.nus.edu.sg:/absolute/repository/path/calbench-soc-results.tar.gz \
  /Users/bruce/MARSHAL/runs/remote-results/
```

运行入口复用仓库的Slurm资源名称与Conda约定；新vLLM CLI参数依据官方v0.28.0源码核对：https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/entrypoints/openai/cli_args.py 。本地测试不替代SoC实际部署验证。
