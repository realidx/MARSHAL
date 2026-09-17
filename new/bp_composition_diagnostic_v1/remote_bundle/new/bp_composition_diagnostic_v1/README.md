# 同一历史上的 B/P 组合诊断 v1

已完成CPU验证，尚未调用模型。当前训练集、prompt和训练配置没有修改。

**在chenjiahao服务器执行请使用[完整远程命令](REMOTE.md)**，已填写SSH地址、环境、模型、双卡服务启动和结果下载。下面的端点命令仅供已有服务时使用。

这是开发诊断包：2个结构家族 × 2种证据来源 × 3个条件 = **12个独立请求**。默认每题8次，共96次模型调用，每次上限1024 tokens。不是12个独立结构，也不是冻结泛化测试集。

## 三个条件

| 条件 | 模型要做什么 | 提供的辅助信息 |
|---|---|---|
| B | 判断唯一未知的伙伴目标偏好，使用原有possible/favored格式 | 不提供答案belief |
| P_gold | 在该历史的当前状态作出下一动作 | 提供从同一历史计算的正确联合belief |
| P_infer | 自行根据该历史推断并作出下一动作 | 不提供答案belief |

同一case的公开信息、私有信息、物理状态、游戏规则、背景和teacher行为约定一致。两个P条件的工具完全一致，只有P_gold多出正确belief。三个条件是**独立请求**，不会把B回答或P_gold答案传给P_infer；不改self-play调用范式。

当前只有一个未知槽位，因此正确联合belief在这批小题中就是该槽位的完整分布。这个包没有覆盖联合相关性推断、多个未知偏好或噪声对手；不把它当作这些能力的检验。

## 两个真实行为历史及对照

### mixed_partial_completion

Blair自愿提出Maple/Maple，Alex接受，随后轮到Alex进行最后一次提案。Blair对Orchard的want/neutral/avoid先验均为1/3。

当前teacher下，该OFFER在三个世界中的似然分别是 `0 / 1/4 / 1`，所以posterior为 `0 / 1/5 / 4/5`。Alex自己的ACCEPT在三个世界中的似然均为1，不提供额外偏好证据。

- B正确答案：possible={neutral,avoid}，favored=avoid。
- 正确belief下，只让一方新增Cedar，期望自身效用2。
- 忽略行为证据、仍按先验规划，会让双方都新增Cedar；实际posterior下期望自身效用1.6，损失0.4。

### binary_complementarity

Blair自愿提出自己Cedar、Alex Maple，Alex接受，随后轮到Alex进行最后一次提案。未知的是Blair对Library的偏好。

该OFFER在want/neutral/avoid世界中的似然分别是 `0 / 1/8 / 1/3`，posterior为 `0 / 3/11 / 8/11`。自身ACCEPT同样不提供额外证据。

- B正确答案：possible={neutral,avoid}，favored=avoid。
- 正确belief下，只要求Blair新增Maple，Alex不增加承诺，期望自身效用2。
- 按先验规划会额外承诺Alex的Cedar；实际posterior下期望效用17/11，损失5/11（约0.455）。

### 每个家族的preset对照

将上述OFFER和ACCEPT标为被要求执行，而不是自愿选择。**行动序列、当前绑定承诺、行动时点和合法动作保持不变**，但它们不应更新偏好belief。正确belief保留三者各1/3，B回答全集、favored=undetermined。

两个家族中，preset与voluntary条件的可接受动作集合均不相交，已计入0.1评分容差。这样可以识别“看到任何历史行动都更新”或“总选保守提案”等简单策略。全程保留完整原生合法工具，不增加最佳动作提示或人为策略菜单。

注意：preset版本的teacher在强制事件之后选择后续策略，voluntary版本在整段自愿历史之前选择策略。两版本的最终决策逐世界收益已独立核实相同；行为证据的可用性是有意设置的差异。

## 选择与验证

`discover.py`从现有训练题的双人小结构出发，把顺序设为`[1,0]`，搜索teacher可达、没有调查、伙伴行为影响最终提案的历史。42个候选设定中41个求解成功，1个因策略迭代循环没有标签；找到2个满足“更新后与忽略行为后的可接受动作无交集”的历史。没有按LLM答题成功与否筛选。

两例有正的历史概率（5/12、11/72），不是拿teacher零概率行为硬推posterior。它们沿用精确teacher的假设，因此仍依赖其行为模型；没有解决噪声对手鲁棒性问题。

从原题改动包括：移除原有预置历史，从初始局开始；binary家族提案顺序由`[0,1]`改为`[1,0]`，mixed家族原来就是`[1,0]`。所有策略、似然和标签重新求解，没有沿用原标签。

验证包括：

- 完整teacher稳定性证书、原生转移和终局效用回算。
- 独立最终回合收益计算，含回应者信息集一致性检查。
- 正确belief的Bayes更新、实际历史正概率、自己的回应不额外提供证据。
- matched物理状态、相同合法工具、disjoint可接受动作与0.1容差。
- 7项CPU回归：标签/答案不泄漏、对照合法、正确与错误动作评分、格式失败/截断计入分母、缺失/基础设施失败不冒充完整结果、合成正确回答的评分通路、双端点参数及分配（mock，无模型调用）。

合成正确回答只验证评分器，不是模型准确率。

## 文件与运行

- `requests.jsonl`：可以发送给模型的12个请求。只发送每行的`request`字段。
- `tasks.jsonl`：含本地评分标签，**不能作为模型prompt**。
- `certificates.json`：世界、先验、posterior、逐步行为似然、动作效用和teacher证书。
- `manifest.json`：题包和依赖散列；变化后必须显式重建审查，不能静默换标签。
- `discovery.json` / `discover.py`：teacher层面的候选筛查记录与脚本。

在仓库根目录验证：

```bash
python new/bp_composition_diagnostic_v1/evaluate.py --check
python -m unittest discover -s new/bp_composition_diagnostic_v1 -p 'test_*.py' -v
```

需要显式重建时：

```bash
python new/bp_composition_diagnostic_v1/prepare.py
```

在已启动且已验证正常的OpenAI-compatible模型端点运行，替换URL和模型名：

```bash
python new/bp_composition_diagnostic_v1/run.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model MODEL_NAME \
  --output runs/bp_composition_v1_baseline
```

默认8次重复，temperature=1.0、top_p=1.0、top_k=-1、repetition_penalty=1.0、max_tokens=1024，匹配最近distribution probe的实际HTTP采样配置。随机打乱调用顺序，每端点并发16；`--base-url`可接多个端点，每个case按replica均匀分配。每次独立上下文，无答案重试；如端点需要认证，读取`OPENAI_API_KEY`。端点版run.py不会启动服务器或训练；远程启动脚本会管理两台自有vLLM服务。对比不同checkpoint时应保持采样参数一致。

也可以自行采样，每行输出：

```json
{"task_id":"mixed_partial_completion:voluntary:B","replica":0,"completion":{"raw_message":{"role":"assistant","content":"...","tool_calls":[]},"finish_reason":"stop"}}
```

以上仅展示封装，实际正确答案需要对应工具调用。默认replica取0–7。离线评分：

```bash
python new/bp_composition_diagnostic_v1/evaluate.py \
  --responses PATH_TO_RESPONSES.jsonl \
  --output runs/bp_composition_v1_scored
```

输出目录必须不存在，避免覆盖原结果。

## 结果怎么解释

汇总同时保留：

- 每条件、每case的完整准确率、合法率、截断/格式失败及覆盖率。
- 同一case/replica的B、P_gold、P_infer三项成功组合计数。
- 正确belief辅助与自主推断的准确率差。
- 每个结构在voluntary与preset对照上同时正确的比例。

格式失败和截断算失败，不只报告合法子集。缺失或基础设施失败会使完整运行accuracy为null，另报覆盖与已观察正确数，不把没有生成的回答当模型失败。

三条件是独立采样，按case/replica配对只为对照统计，并不观测同一次推理内部的belief。若B与P_gold较好、P_infer较差，只能说值得进一步检查自主推断/决策组合，不能据此证明内部belief正确或精确定位故障层。尤其B正确仍不等于完整概率推断正确。

两个家族的重复rollout不能支撑广泛结构迁移结论；本包适合训练前后能力检查，不报告把所有rollout当独立结构得到的置信区间。当前还没有真实模型结果。
