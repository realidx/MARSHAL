# CalBench chenjiahao 接入验收

2026-09-18：完成真实本地 Qwen3-4B-Instruct-2507 端到端开发测试。

- 远端：/raid/chenjiahao/mas/runs/calbench-dev-20260917-143231
- 本地完整结果：runs/remote-results/runs/calbench-dev-20260917-143231
- 官方源码 archive SHA256：dfbbc7633a27d7326b8fab322fe8c3699ca4f5b6997f980c00e981ae99da823f
- 源码逐文件固定且未修改；仅适配 provider HTTP transport 和运行/日志接口。
- 独立 .venv-calbench；vLLM 继续使用 mas 环境。原训练依赖未修改。
- 启动在 GPU6、7；退出后两卡显存为0。EXIT_CODE=0，RUN_FINISHED healthy_transport=true。

| 开发局 | 调用 | 局内耗时 | 调用中位数 | 成功会议 |
|---|---:|---:|---:|---:|
| dev_0 | 18 | 100.98s | 3.27s | 1/2 |
| dev_1 | 18 | 109.81s | 4.65s | 1/2 |

两局并行，不含模型初始化的整体时间约110秒。每局输出2219 tokens，最大输入4940 tokens。两局使用相同世界、同一Q0权重、temperature=0，仅focal标记不同，输出相同；不构成两个独立能力样本。

36次请求全部成功，无截断；按严格thinking/actions envelope离线复核格式错误0；batch_rejected、decision_failed、invalid_tool_call均未出现；无fallback事件。每局第一场会议所有参与者选择slot5，成功；第二场agent1/2选择slot3，agent3选择slot5，协调失败。模型动作分别合法，不代表共同安排一致。引擎正常记录失败并结束。

这验证通信、私有历史、原生协议与终止/失败记录链路，不证明迁移效果。当前为4人、8slot、2meeting、2轮交流、1次决策重试的开发配置；无强制JSON解码、无额外策略提示、无算法补排、无隐私反思调用。成本均0，因此本局不是成本敏感能力检验。

验证：原生calendar/llmclient/protocol测试72项通过；本地适配器测试3项通过。

入口与操作说明：examples/final_evaluation/CALBENCH.md。

后续工作：冻结有成本冲突和跨会议依赖的正式场景、确定交流预算、轮换全部座位，接入Q0/SP/Mixed/BP模型路径。不依据本次模型输赢选择正式实例。
