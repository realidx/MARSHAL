# 在原 mas 环境安装 CUDA 11.8 版 vLLM

本文是原 `mas` 环境的安装/恢复记录，以下“安装前版本”和候选组合属于当时的快照。已有可用 vLLM 服务时，使用 [当前运行命令](SOCIAL_SERVER_RUN.md)，无需重复安装。

2026-09-11。用户要求同一 conda，不另建环境。当前实际 driver API=11040，库路径 `/usr/lib/x86_64-linux-gnu/libcuda.so.470.256.02`。仅更换 PATH / CUDA_HOME 不能获得 CUDA 12 驱动能力。

候选组合：vLLM 0.8.5.post1+cu118、torch 2.6.0+cu118、torchvision 0.21.0+cu118、torchaudio 2.6.0+cu118、CUDA 11.8 构建的 xformers 0.0.29.post2。保留 Transformers 4.57.3、DeepSpeed 0.16.3。

这会升级当前 torch 2.5.1，并可能调整 Triton 等依赖。已按旧 torch 编译的 FlashAttention / DeepSpeed 自定义算子不能保证二进制兼容，后续训练前需重新检查或重编译；pip check 本身不能证明 CUDA 算子可运行。尚未在服务器执行安装或 GPU 测试，不宣称 470 驱动可以运行所有该 wheel 的内核。

依据：[官方 CUDA 11.8 wheel](https://github.com/vllm-project/vllm/releases/expanded_assets/v0.8.5.post1)、[对应 torch 依赖](https://github.com/vllm-project/vllm/blob/v0.8.5.post1/requirements/cuda.txt)、[NVIDIA 有限的 CUDA 11.x 小版本兼容](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。

Mac 上传新增的安装清单：

```bash
cd /Users/bruce/MARSHAL
rsync -avzP -e "ssh -i $HOME/.ssh/id_rsa_dgx2 -p 2201" \
  training/b_sft/configs/vllm085_cu118_py311.txt \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/training/b_sft/configs/
```

服务器记录当前依赖并预览安装。依赖记录不是完整环境备份。不要同时在此环境进行训练更新或另一项 pip 安装。

```bash
conda activate /raid/chenjiahao/conda_envs/mas
cd /raid/chenjiahao/mas
mkdir -p outputs/env_records
python -m pip list --format=json > outputs/env_records/before_vllm085.json
python -m pip check > outputs/env_records/before_vllm085_check.txt

python -m pip install --dry-run \
  --report outputs/env_records/vllm085_plan.json \
  -r training/b_sft/configs/vllm085_cu118_py311.txt
```

若解析成功，安装同一份清单；若出现冲突，先保留错误，不用 --no-deps 绕过。

```bash
python -m pip install -r training/b_sft/configs/vllm085_cu118_py311.txt
python -m pip check
python - <<'PY'
import torch, transformers, vllm
import vllm._C
import xformers
print('torch:', torch.__version__, 'CUDA:', torch.version.cuda)
print('transformers:', transformers.__version__)
print('vllm:', vllm.__version__)
print('xformers:', xformers.__version__)
assert torch.version.cuda == '11.8'
PY
```

启动服务时保留已验证的 11.8 ptxas，另用独立 Triton 缓存；GPU 0 是示例，必须换成自己分配到的 GPU。

```bash
export CUDA_VISIBLE_DEVICES=0
export TRITON_PTXAS_PATH=/home/chenjiahao/cuda-11.8/bin/ptxas
export TRITON_CACHE_DIR=/raid/chenjiahao/mas/.cache/triton_vllm085_cu118
export VLLM_USE_V1=0
export VLLM_ATTENTION_BACKEND=XFORMERS

python -u -m vllm.entrypoints.openai.api_server \
  --model /raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507 \
  --served-model-name social-base --host 127.0.0.1 --port 8000 \
  --tensor-parallel-size 1 --dtype bfloat16 \
  --max-model-len 16384 --max-num-seqs 1 \
  --gpu-memory-utilization 0.35 --enforce-eager --disable-frontend-multiprocessing \
  --enable-auto-tool-choice --tool-call-parser hermes
```

使用 V0 / XFORMERS / eager 作为首轮兼容性配置，减少引入新执行路径；这不是 GPU 兼容保证。0.35 仍按整张 40 GB 卡计算，需结合当前空闲显存。截图中各卡 GPU 利用率均为 100%，即使还有显存，仍会争用计算资源。不要修改或终止其他人的进程。

服务成功启动后，沿用 SOCIAL_SERVER_RUN.md 的 HTTP 测试命令，先用 `--limit 1` 和新的输出目录确认一次 B/P 调用能执行，再运行指定结构。若启动失败，保留第一个具体 traceback，不连续更换 CUDA 路径或安装不同版本。
