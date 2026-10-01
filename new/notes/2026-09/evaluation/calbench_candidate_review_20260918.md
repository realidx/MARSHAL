# CalBench 候选审查（2026-09-18）

状态：用户决定放弃 C2C，转而研究 CalBench。仅研究，未部署、未运行模型；本轮没有停止旧 C2C 进程。

来源：
- 最新论文 v3（2026-06-05）：https://arxiv.org/html/2605.09823v3
- 官方匿名仓库：https://anonymous.4open.science/r/calbench2026-235F/README.md
- 已实际读取 README、pyproject.toml、experiments/example.yaml；未完成环境/客户端源码审计。旧 github.com/bosonphoton/calbench 的 git ls-remote 返回 Repository not found。

判断：适合作为私有信息下多方协调的跨环境候选，比战争游戏更贴近 BENAC 的共同承诺。不能凭结果把行为改进归因为隐藏偏好推断，也不等价于自利博弈迁移。

需要保留的结构：不同个人调整成本；跨会议参与者重叠；后续会议可能要求协调改动已有会议；每个模型仅收到自身日历和可见消息。

建议协议（尚未冻结）：[M,Q0,Q0,Q0,Q0]，轮换 focal；原生五人/每会三人结构；varied 为主，uniform 为控制；只换 focal 模型。先独立开发实例测调用量、长度、合法性和端到端耗时，不依输赢挑正式实例。不把非当前会议参与者删掉，否则会损失跨会议依赖。

指标：成功率优先；同时保留 focal 成本、团队成本、失败和重试、token/延迟。不能因少安排会议、成本少就算更好。CP-SAT 为全信息评分参考，不是同可见信息 teacher 对手；不向模型暴露 oracle 或 witness。隐私 VPS 不是正确 belief 标签；暂不复现额外隐私 judge。

成本：论文配置有每会15轮交流，不能假定便宜。仅三位参与者每轮发言即 5*15*3=225 次交流调用，尚未计决策、外部参与者、重试与可选测量；这是预算示例，不是实测平均。

代码可行性：README 声明 OpenAI-compatible API，论文描述 LiteLLM 路由，可按 agent 配置模型；本地 base_url 透传仍需客户端源码验证。Python>=3.11；依赖 ortools、dspy 等；应使用独立环境，避免升级现有训练环境。伴随 a2a-engine/expt-runner 已 vendor。

版本风险：README 发布 uniform90+varied90，但论文主实验为总90任务，不能混称同一测试集。v3 正文、主表、排行榜说明中的1/2/3和1/10/100成本尺度不同，应核对源码并冻结评分口径；v2/v3 excess cost定义也有变化。暂不使用排行榜综合分。

下一步：取得完整源码快照并固定版本/文件哈希，检查客户端/可见信息/成本与失败评分/额外LLM调用，再决定最小本地开发配置。不立刻扩大正式测试。

## 接入进展（2026-09-18）

已获取官方 ZIP，源码逐文件 SHA-256 记录在 examples/final_evaluation/calbench_source.json；未修改上游源码。当前引擎默认 enable_fallback=True，会在协调失败时算法补排，论文实验 YAML 多处显式禁用。我们的开发运行同样禁用。enable_reflection 默认 True，开发关闭；decision_retries 引擎默认3，开发设1（部分上游小局示例也为1）。

原生客户端使用 a2a_engine 工厂和 streaming_with_retry 接口，本次只替换 provider transport，保留 LLMClient 的提示、历史、原生 json_repair 和环境验证。基础设施失败仍可能被原生客户端转换为空输出，因此独立传输日志与 healthy_transport 必須共同检查，不能仅看进程退出码。

远端 .venv-calbench 是不包含 system-site-packages 的独立 Python3.11 venv。GPU服务继续使用 mas Python，不升级原环境。已通过原生72项测试与本地3项适配器检查。启动两局4-agent、2-meeting、8-slot开发任务：runs/calbench-dev-20260917-143231（服务器文件名时间）。运行中，尚未记录最终结果。

开发运行已完成，结果见 calbench_integration_result_20260918.md：36次真实本地调用无截断/格式/非法动作错误，两局均成功1/2会议；另一会议为合法但不一致的决策。两局并行约110秒（不含模型加载），GPU自动释放。接入成功，不是迁移效果结果。
