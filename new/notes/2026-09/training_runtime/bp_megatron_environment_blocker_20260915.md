# Megatron 迁移的环境阻塞

用户运行 Megatron v1 后，环境检查报告未安装 megatron.core、transformer_engine.pytorch、flash_attn；MCA 和 ROLL 的后续导入因此连带失败。尚未加载模型。Transformers 缓存变量的弃用警告不是失败原因。

上一轮完成的是代码/配置迁移和 CPU 回归，不能称为服务器环境已准备好。当前缺的不只是可随意 pip 补装的几个纯 Python 包。

## 已有证据

- `training/b_sft/VLLM_SAME_CONDA.md`：用户之前要求保留原 mas conda；记录 driver API11040，libcuda.so.470.256.02；torch2.6.0+cu118、vLLM0.8.5.post1+cu118。仅改 CUDA_HOME 不能升级驱动能力。
- 2026-09-14 下载的 `new/local_data/social_runs/social_l0_probe_20260915/g16-20260914-145804/performance-20260914T190410Z/metadata.json` 的 gpu_initial 再次记录驱动470.256.02。
- 仓库 `requirements_torch260_vllm.txt` 指定 Transformer Engine2.2.0；`docker/Dockerfile.torch260.vllm` 安装 torch2.6.0 cu124。该 Dockerfile 的 megatron-core0.11.0 与当前 MCA 的 >=0.12,<0.13 要求也不一致，不能整份照搬。
- 找到的 SoC 作业脚本通过 conda 激活运行。尚未找到证明 SoC 当时准确包版本的环境快照，不将仓库 Dockerfile 当成旧作业实际环境证据。
- [TE2.2 构建源码](https://github.com/NVIDIA/TransformerEngine/blob/v2.2/build_tools/pytorch.py#L64) 明确要求 CUDA>=12.0；[TE1.12](https://github.com/NVIDIA/TransformerEngine/blob/v1.12/build_tools/pytorch.py#L68) 也有此检查。因此不能对当前 cu118 环境直接推荐这两个版本。
- [NVIDIA CUDA forward compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html) 提供数据中心 GPU 在受支持组合下使用兼容库的路径；不是仅安装 toolkit 或更换 conda。当前文档已不列470分支，且 CUDA12 的部分虚拟内存功能要求更新内核驱动，不能未经验证承诺 compatibility 包即可运行本仓库 vLLM sleep 路径。

## 待解决

需要确定服务器是否允许管理员升级驱动，还是必须保留470；这决定选择 CUDA12 环境迁移，或研究保留cu118的旧TE源码组合/其他适配。旧TE组合尚未验证，不能发送无版本限定的 pip install 命令，也不能继续让用户重跑完整训练来判断环境。

没有更改远程环境、升级驱动或发起安装。Megatron代码保留；此次报错并不证明Megatron训练逻辑或显存已失败，也没有提供后端加速的实测证据。
