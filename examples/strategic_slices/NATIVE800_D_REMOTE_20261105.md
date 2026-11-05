# 新800 slices：远端测D

2026-11-05，版本`native800-terminal-D-v1`，prompt=`native800-readable-prompt-v4`，score=`native800-response-lexicographic-regret-v1`。
**仅实现和打包。按用户要求未做CPU测试、mock、GPU smoke或真实模型验证；首次实际运行由用户在远端执行。**
本入口测D，不训练、不重新求解Oracle、不自动选最终100。旧run_terminal_d及生产active v8保留原身份。

## 已固定的执行合同

- 600 train候选＋200 validation，共800入口；来自65两人/35三人父池，train/validation按父游戏分开。完整题库hash见注册快照。
- 每个入口8次独立采样，共6400条轨迹。从入口Oracle条件posterior抽真实world，不从父游戏先验重新抽；同一入口的8次request具有相同可见题面。
- 当前玩家从入口一直控制到原生终局，包含其后所有proposal和response；其他玩家按同一冻结数值认证reference行动。没有旧k=1/2/3截断。
- 每个decision重建全部公共事实、公开历史和本人累计真实调查答案；不传Oracle Q/S/后验/动作分数，也不累积assistant解释到下一次上下文。
- 默认temperature=.8、top_p=1、top_k=-1、repetition_penalty=1、max_tokens=4096、context=16384、seed=42；保留原D采样参数。
- 默认32并发、完成即补位，每条轨迹同一时刻一个请求；一批父游戏只加载一份reference。父游戏间顺序运行，父内不足32条待运行轨迹时可能未满并发，不宣称跨父全局满载。
- 不自动重试模型请求。HTTP／tokenizer／环境异常使运行停止，留FAILED记录，不记为模型零分。非法工具或截断保留原状态，该轨迹停止且terminal D不可用。
- own terminal D=`max(entry Q) - mean(actual terminal own utility)`，不截零；8条有任一未完成则主D=null，保留completed-only估计及缺失结果上下界。8样本bootstrap仅描述性，不是高精度难度证明。
- 入口每次回答调用已审阅scorer-v1：proposal/非平局回应看own，回应自身平局才看others-sum。入口own regret、protocol regret、正确率分列；不把social和own D混成一个排名。
- 后续决策仅做原生合法性／状态重放记录，不新计算后续Q/S；本入口不是训练collector，也不声称提供整条轨迹逐节点Oracle reward。
- 每条已结束轨迹原子保存为gzip JSON，可独立恢复；未完成轨迹恢复时从入口用相同seed重跑。每次attempt有独立transport日志和完整pipeline_snapshot。

## 传输

已生成的本地包：`new/native800_d_remote_20261105/native800-D-v1.tar.gz`，旁边`.json`记录包hash。
包内包括运行源码、800入口、100个reference、对应原生job、prompt-v4实际完整示例和新注册快照；不包括模型权重、整个历史日志或完整标签profile。入口所需Q已在JSONL中。
不要只git pull代码就假定本地生成题库也传到了远端。将包传到server后，解压到独立目录：

```bash
mkdir -p ~/native800-D-v1
tar -xzf /path/to/native800-D-v1.tar.gz -C ~/native800-D-v1
cd ~/native800-D-v1
```

如需重打包，在原仓库根目录运行，输出必须是新文件：

```bash
python -m examples.strategic_slices.prepare_native800_d_bundle \
  --output new/native800_d_remote_20261105/native800-D-v1-copy.tar.gz
```

## 直接在已分配GPU的server运行

先激活现有可用的vLLM环境；需要numpy、scipy、transformers、torch、vllm及支持Qwen具名工具的Hermes parser。
沿用已有正常工作的GPU/CUDA环境配置，此入口不安装包、不下载模型。将模型路径替换为用于测D的本地base模型目录；本机tokenizer必须与所服务权重一致。

```bash
cd ~/native800-D-v1
export SLICES_D_PYTHON="$(command -v python)"
bash examples/strategic_slices/run_native800_d.sh \
  --model /path/to/Qwen3-4B-Instruct-2507 \
  --output runs/native800-D-v1
```

不使用Slurm也可直接运行；启动器要求只暴露一张已分配GPU。不要在无GPU的login节点执行。启动器会自行启动并最终关闭本次vLLM。
默认GPU显存比例0.4继承旧D配置，可显式覆盖：

```bash
bash examples/strategic_slices/run_native800_d.sh \
  --model /path/to/Qwen3-4B-Instruct-2507 \
  --output runs/native800-D-v1 \
  --workers 32 --gpu-memory-utilization 0.8 --port 18083
```

完整CLI覆盖会写入实际snapshot；恢复必须使用相同覆盖。GPU资源差异不代表新的统计定义，但不能静默混入同一运行身份。

## Slurm

先激活工作环境，再从解压目录提交；partition/account/GPU型号由server决定，通过sbatch参数指定。脚本不写死个人conda路径。

```bash
cd ~/native800-D-v1
export SLICES_D_PYTHON="$(command -v python)"
sbatch --partition=YOUR_GPU_PARTITION \
  examples/strategic_slices/sbatch_native800_d.sh \
  --model /path/to/Qwen3-4B-Instruct-2507 \
  --output runs/native800-D-v1
```

脚本默认1 GPU／8 CPU／64GB内存／6小时，这是资源请求模板，不是性能测量，可用sbatch选项覆盖。

## 使用已经运行的vLLM

服务必须支持相同Qwen原生chat template、Hermes具名工具和采样参数，且本地模型目录是该服务的同一份权重/tokenizer。
客户端不会关闭外部服务；此模式支持SSH端口转发后的localhost服务，不含认证代理配置。

```bash
bash examples/strategic_slices/run_native800_d.sh \
  --model /path/to/Qwen3-4B-Instruct-2507 \
  --endpoint http://127.0.0.1:18083/v1 \
  --served-model YOUR_EXISTING_SERVED_MODEL_ID \
  --output runs/native800-D-v1
```

## 恢复与结果

```bash
bash examples/strategic_slices/run_native800_d.sh \
  --model /path/to/Qwen3-4B-Instruct-2507 \
  --output runs/native800-D-v1 --resume
```

必须与首次运行使用相同model/config/CLI覆盖/endpoint/source。已原子保存的terminal和明确invalid/truncated轨迹都原样复用；不会选择性重采答错题。仅没有完成文件的轨迹重跑。
如果在建立`evaluation/protocol.json`之前启动就失败，没有任何评测结果可恢复，换一个新的output目录再启动。

重点查看：

- `runs/native800-D-v1/evaluation/summary.json`：完成状态、train/validation与用途/父游戏分层统计。
- `evaluation/slices.jsonl`：逐题D、缺失界、入口own/protocol分数与采样差异。
- `evaluation/train_signal_candidates.jsonl`：仅训练split中已完成且入口采样有protocol contrast的诊断清单，**不是最终100**。
- `evaluation/replicas/*.json.gz`：逐轨迹完整request/output、原生行动路径、入口评分和终局收益。
- `evaluation/pipeline_snapshot.json`、每个`attempt-*/pipeline_snapshot.json`：完整实际配置、source/input/model身份、环境及CLI；缺失信息标NOT_RECORDED。
- `attempt-*/server.log`、`transport.jsonl.gz`和FAILED记录：失败诊断。`evaluation/COMPLETE.json`代表全800流程结束；仍需检查主D是否有null。

本地没有按此说明启动任何模型、测试或任务。远端首跑有实现尚未验证的风险；日志回传后再分析D和最终选题。
