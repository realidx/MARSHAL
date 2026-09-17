# Q0 冻结集首轮基础设施故障审查

本地来源：runs/remote-results/calbench-q0-debug/runs/calbench-formal-q0-v1。

12 局全部受到基础设施故障污染，无完整有效局；不能报告为 Q0 成功率 0/12。共 114 次调用，2 次返回成功、112 次基础设施失败。旧 EXIT_CODE=0 只反映 runner 返回，没有正确反映服务健康。

两台服务错误均为 `RuntimeError: Triton Error [CUDA]: device kernel image is invalid`。调用栈为 XFormers → PagedAttention.forward_prefix → prefix_prefill.context_attention_fwd → Triton load_binary。后续 HTTP 500、连接拒绝和请求超时是服务崩溃的后果；没有证据表明这是显存不足。

之前提交的启动命令设置 CUDA_HOME/PATH/LD_LIBRARY_PATH，却漏掉已在 CALBENCH.md 要求的 TRITON_PTXAS_PATH。日志没有记录实际采用的 ptxas，因此不能据此完全证明底层编译器原因；应先修正已知配置遗漏，在开发题验证后再重跑。

本地修复：launcher 显式解析/校验并传递 TRITON_PTXAS_PATH，记录 ptxas --version，仍使用每次运行独立 Triton cache；transport 的基础设施异常绕过原生空动作回退，保存中止结果；runner 每次只派发一个并行批次，批次基础设施失败后停止后续题并返回非零退出码。输出截断仍作为模型结果，不当成网络故障。

测试集、日历和最优成本证书未修改。首轮结果保留。用户在远端执行独立开发检查后，再以新输出目录重跑同一冻结集；不挑选性保留首轮结果。所有后续模型使用同一修正版执行器。
