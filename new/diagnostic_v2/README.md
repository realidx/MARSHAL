# B/P 诊断试验：开发 pilot v2

已生成题目、请求和评分器，未运行任何模型。此包检验实验接口，不预设 trained 胜过 base。无需训练，不修改训练数据。

## 33 个独立请求，三次采样 = 每模型 99 次调用

1. **23 道单项开发题**：来自 v5 candidate validation；覆盖 B1/B2/B3 的 binary/linear 和 full/reduced support；P1/P2/P3；P4 值得调查、不值得调查和结果利用的可用子类。按事先定义的格子对 ID 做稳定哈希选择，不按模型表现选择。B/P 标签沿用开发集已审核 teacher，本次只检查渲染和评分通路，不宣称重新求解了全部单项题。
2. **6 个同历史组合请求**：一个 binary 结构 × voluntary/preset 两种证据来源 × B/P_gold/P_infer。已用当前 teacher 重新求解并核验原生转移、独立终局收益、posterior，以及两种证据条件下不相交的可接受动作集合。共享状态和工具；三个调用上下文互不相通。只一个结构，不能据此概括组合能力。
3. **4 个 P→B 解析控制请求**：相同的观测动作 A，改变备选 B 的效用，使 A 分别有偏好区分力/没有区分力。各做原始效用表和正确 likelihood 辅助两个条件。前者需要逆向规划与贝叶斯更新，后者跳过似然推导，但不提供 posterior。此为独立小型解析题，**不是 BENAC 原生题或完整局证据**。

P→B 的这里指“理解伙伴规划→推断伙伴偏好”。自己的规划→调查→后续判断/行动是另一种过程：单项 P4 仅提供组成环节的诊断，当前包尚未实现同一调查轨迹的完整配对闭环。不能声称两类过程均已验证。

## 明确保留的缺口

- 当前 validation 缺少满足选择条件的 `P4/binary/query_only`（排除 result_use 后），写入 manifest 的 missing_cells，不用任意其他题冒充。
- 组合配对暂时只有 binary，没有 linear；没有多未知偏好相关性诊断。
- P→B 表格显式给出效用，检验的是受控逆向规划，不证明模型能从长原生历史自行算出这些效用。
- 没有完整的“belief 改变但正确动作保持不变”原生配对；解析题只有“行为不具有偏好区分力”的对照，二者不等价。
- 33 个请求不是 33 个独立结构。单项题仍属开发诊断；当前选中题与 v5 B/P train 的输入没有精确 JSON 重复，但同结构、语义近重复没有因此被排除。
- 自身规划的信息获取暂不扩展 OFFER/MENU。

## 运行（用户在服务器操作）

使用已经启动的兼容工具调用模型端点，不自动启动服务。三种模型分别运行，保持模型模板与参数一致：

```bash
python new/diagnostic_v2/evaluate.py
python new/diagnostic_v2/run.py \
  --base-url http://127.0.0.1:8000/v1 --model YOUR_SERVED_MODEL \
  --output runs/diagnostic_v2/q0 --repeats 3 --temperature 1 --top-p 1
```

训练模型分别使用独立输出目录。每次最多 1024 输出 tokens、无重试；截断和格式失败计入准确率分母，基础设施失败及缺失使对应完整准确率不可报告。原始响应保留。不得向模型发送 tasks.jsonl 或 certificates.json；runner 只发送 requests.jsonl 内的 request。

单项分题结果见 summary.json 的 per_task；同历史和逆向规划配对见 paired_cases。先报告各机制全部结果，再列 base→trained 的错→对、对→错、均对、均错；不能只挑改进案例。独立采样配对不证明内部机制，也不把三个重复当三种结构。

验证：

```bash
python -m unittest discover -s new/diagnostic_v2 -p 'test_*.py' -v
```

四项测试覆盖合成正确答案/截断、缺失处理、解析 Bayes 标签和 P 条件工具一致。合成答案验证不是模型结果。
