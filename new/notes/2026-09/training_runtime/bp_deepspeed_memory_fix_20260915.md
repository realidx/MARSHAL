# DeepSpeed 双 A100 backward OOM 与 v2 修复

用户提供 `runs/bp_deepspeed_20260914-180041/train.log` 尾部：进入 backward，申请742MiB失败，剩余606.19MiB；当前进程33.75GiB，其中PyTorch allocated28.09GiB、reserved但未allocated2.52GiB；同一设备还有两个进程分别占3.10、2.08GiB。仅凭尾部不能确认这两个PID属于哪些角色，不能要求终止它们，也不能确认已完成多少更新或已有checkpoint。

错误证明已越过初始化、采样和loss forward，但不证明训练完成。2.52GiB reserved不能全当可满足任意连续分配的显存；日志不足以断言纯碎片。继续保留ZeRO-2，不改变任务预算、奖励和分组。

## 修复

1. DeepSpeed B/P 两卡训练逐microbatch按attention_mask最后有效位置去除右padding，同时对齐input/position/response_mask，以及长度T-1的old/ref log-probs、advantages、final_response_mask。保留原batch，不减少有效token或输出预算。生产postprocess已将原始左padding转换为右padding。
2. entropy_loss_coef=0且该loss函数没有报告entropy时不构造全词表entropy及其autograd计算。它原本不影响目标；这是无用计算与瞬时分配，不声称其图一定保留到了backward。
3. backward之后显式删除output/logits和loss，避免上一microbatch的大词表输出活到下一次forward或optimizer onload。
4. torch.optim.AdamW由foreach=False单张量实现改为fused=True，避免对ZeRO扁平FP32大分片执行单张量更新时的大型中间数组。使用PyTorch内置CUDA内核，不安装DeepSpeed FusedAdam扩展。算法/超参不变，浮点舍入不声称逐bit一致。[PyTorch2.6 AdamW源码](https://github.com/pytorch/pytorch/blob/v2.6.0/torch/optim/adamw.py)。GPU环境检查在加载LLM前对两卡各执行3次小张量更新，与原AdamW对比，并检查现有Adam状态卸载/恢复及state_dict重载。
5. ZeRO通信overlap关闭，reduce/allgather bucket各从50M改为10M元素。让出通信缓冲显存，可能牺牲通信重叠吞吐。
6. optimizer.load_state_dict可能把缓存CPU offload buffer映射到CUDA；下次offload检查buffer设备并在目标设备重建，避免恢复后缓存失去卸载作用。前置小张量检查断言Adam moments实际进入CPU并回到当前GPU。

## 验证与限制

本地新增padding边界、loss/梯度等价性、entropy开关和丢弃有效response的拒绝检查。实际小型Qwen3模型使用SDPA和非reentrant gradient checkpointing，裁padding前后GRPO loss及所有参数梯度在容差内一致。此前52项测试通过；随后通信配置新增断言另测。没有在Mac执行CUDA fused AdamW或真实4B双卡更新，环境前置CUDA检查将由用户运行。

上传包 `/private/tmp/marshal-bp-deepspeed-train-v2`。正式入口不变 `examples/social_bp/run_two_a100_train.sh`，使用新结果目录。不会自动升级环境、缩短1024输出、换奖励、改采样数、切换ZeRO-3或反复retry。
