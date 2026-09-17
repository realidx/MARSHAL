# SoC 运行时修复交接（2026-09-17）

来源：用户提供的服务器修复提交与诊断结果。本地已fetch并快进soc-runtime-fixes至d3139d0，逐项确认以下16个提交均在HEAD历史中。最终853616诊断产物已在本地读取；本地14项CPU回归通过，没有重新执行GPU训练。

|提交|修复／产物|
|---|---|
|fcb664a|MIG UUID保留为字符串；Transformers 5 tokenizer additional_special_tokens及ids API兼容|
|063a6d4|按运行时签名适配Torch _new_process_group_helper|
|4478b42|CUDA13 cuDNN frontend runtime，避免选到libcudart.so.12／找不到-lcudart|
|ad550bf、373f0ae|TE attention backend完整组合flash=1,fused=0,unfused=0|
|74a05d2|853488原始失败报告与逐token记录|
|c1e174c|log_probs.detach()与scheduler缩放共用存储，改detach().clone()保留未缩放概率|
|f547566|microbatch修复后的诊断产物|
|ffc6d1c、69b0ff4、278f6ee|独立切换NVTE backend、Megatron实现与sequence parallel的诊断开关，不改变默认生产配置|
|3c11c1b|local路径复用标准get_ltor_masks_and_position_ids，生成四维布尔causal mask|
|a0cfbf9|临时RoPE探针，发现实际theta错误为10000|
|47805ba|从Transformers5 rope_parameters读取迁移后的RoPE设置，避免静默回退；模型要求theta=5000000|
|d9a3e1a|RoPE修复后完整通过诊断记录|
|de2346d|删除临时硬编码RoPE探针|

## 已定位根因（用户服务器诊断）

1. 概率结果共享存储：detach不复制tensor，调度器原地除以microbatch数污染返回log-prob。这是实现错误，不能解释为后端正常浮点差异。
2. 配置迁移漏读：Transformers5将rope_theta移入rope_parameters，adapter未读取导致MCore用10000代替5000000。修复后实际inv_freq与正确theta的最大误差5.96e-08。

## 用户报告的最终结果

HF batch/single、Megatron batch/single、reference drift、vLLM同步前后、sleep/wake均0。HF/Megatron mean从.9339降至.02479；gross_mismatch为空。一次诊断optimizer更新确实改变参数，KL=.002531，loss=-.33426，PG=-.33428，grad norm=14.422。更新后actor/vLLM mean=.02424、P99=.22751、max=.37899。

这些结果支持重新开始正式训练；不是完整逐参数同步相等证明。此次仅固定token诊断及一次抛弃式更新，没有正式Social训练、完整游戏rollout或训练checkpoint，没有通过调整KL来掩盖问题。先前mixed-851174的40步不应作为健康训练结果或续训起点。

## 本地同步状态

已同步原提交，保留完整历史。生产默认配置与远程一致，临时硬编码探针已删除。d3139d0还按远程原提交删除了失败851174原始产物；未自行恢复，可从旧Git提交追溯。当前使用soc-runtime-fixes分支，旧new分支指针未移动。
