# B-only 数据与监督：独立查询偏好版本

2026-09-08。本轮只处理 B 的数据、标签、评分和 SFT 输入；没有训练模型，没有更新 P。

## 当前结论

已经移除“识别背景行就顺带知道被查询 goal”的先验捷径，并完成可复现的 B-only
数据生成流程。固定伙伴策略下的集合标签可以穷举生成、独立重放核验，并直接导出为
Qwen 的 SUBMIT_JUDGMENT tool-call 监督。不是用真实隐藏偏好替代证据支持的集合。

最终语料包含 14 个源游戏，1,316 条不同的原始问题，筛选后 849 条：

| 划分 | 源游戏 | 样本 | 单元素集合 | 两元素集合 | 三元素集合 |
|---|---:|---:|---:|---:|---:|
| Train | 10 | 610 | 240 | 130 | 240 |
| Validation | 2 | 113 | 48 | 17 | 48 |
| Test | 2 | 126 | 48 | 30 | 48 |

两种训练游戏配置分别覆盖 learner P0/P1/P2/P3。验证和测试源游戏在补角色前后保持不变，
没有用它们补训练数据。源游戏及规范化 goal 图均不跨划分；原始/筛选问题均无输入重复。
这仍是小规模开发划分，不是最终论文测试集，126 条测试问题不等于 126 个独立游戏。

## 修复的具体问题

### 1. 查询偏好独立于背景，而非完整偏好模板查表

保留四玩家、每人 2–3 个 commitment 位、12–16 个 ALL_OF goals、4–6 轮、全部原生行动。
每名玩家从以下公开先验独立抽样自己的私有偏好：

```
6 种其他 goals 的背景 × 查询 goal A 的 3 种偏好 × 查询 goal B 的 3 种偏好
= 54 条完整候选偏好
```

两个查询 goal 对每名玩家分别选择，其值相互独立，也独立于全部其他 goal 偏好。
程序逐背景穷举检查：即使固定背景及另一查询 goal，当前查询 goal 仍保留完整三值。
公开输入使用因子化说明和带 null 槽位的背景行；null 明确表示独立槽位，不表示 neutral。
无需向模型展示 54 条重复的完整行。

这仍是有限背景先验，不是完整原生逐 goal 独立先验。背景内的其他 goals 仍有相关性，
但它们不能在没有行为证据时泄露被查询 goal。观察行为之后产生的条件相关性是合法推断，
不应强行维持先验独立性。

### 2. 精确标签对应一个明确固定的伙伴策略

保持 `finite-private-uct-v1`：1024 simulations、最多 3 个自身树内决策/12 个树内阶段，
之后用原有轻量 continuation 模拟至终局。行为不是精确最优策略，但标签是相对于该
确定策略的精确支持集。没有更换预算后沿用旧标签，也没有加入 outcome 作为 B 正确性奖励。

`b_oracle.py` 只增加重复接受率和行动分组的缓存，保持行动排序、随机流和计算结果。
与原实现的 root action、visit counts、means、tree nodes 做逐项一致性测试。
额外检查了一个已完成 goal 的偏好仅增加恒定收益时，不应由该对照中的新行动泄露偏好。
这些是程序检查，不是对所有局面中数值不变性的普遍证明。

每次观察 oracle 行动，枚举该玩家全部剩余候选行，保留会产生该行动的行，再投影到查询 goal。
每行都完成计算，未访问/超时不被当成“不可能”。learner 行动只作干预。
给定 learner 自身偏好后，显式联合空间为 54³=157,464 个配置；生成过程中逐步与它交叉验证。

另外的公开历史 validator 不读取存储的 support_type_ids/行动分区作为答案，重新执行
固定 oracle 并核验每一个不同问题。它使用 learner 自己的偏好，不用伙伴的真实实现行打标签。
法定状态、pending offer 与终局收益另经原生 GameState 核验。

### 3. 降低已知答案重复，覆盖部分更新和不更新

采集完整自然轨迹；对仍不确定的目标，保存观测前后问题，并在同一合法前缀下枚举
其他候选类型会产生的不同原生行动。每个替代分支都有兼容的隐藏配置见证和原生重放，
不是将任意动作拼进历史。所有这些分支留在同一个源游戏划分内。

去掉 189 次重复插入；对已知目标只保留少量控制样本。每个源游戏按答案集合大小设上限，
不足的类别不复制凑数。1316 个原始不同问题中筛选 849 个，所有七种非空语义集合在
训练/验证/测试中均有覆盖。部分集合仍比单元素和完整集合少，不能声称完全均衡。

保存了 987 对观测前后更新问题，其中也包括 learner 行动不能排除类型的控制。
不是每一对的两个端点都进入最终限额筛选；评分器会明确统计当前 split 中可配对的数量。

一个自然例子：`n4_k2_g12_r4_s63000`，查询 P3 对 G11 的偏好。
观察到 P3 的 CHOOSE_2 后，集合从 `{want, neutral, avoid}` 变为 `{want, neutral}`。
没有强行标成真实类型，也没有将一次选择简单等同于 want。

### 4. 补齐角色，并隔离源游戏

最初 8 局的训练 learner 只出现 P1/P2。额外选择 6 个训练源游戏补齐各配置的四种角色。
选择依据只有公开初始角色和 goal 图是否与已有源重复；没有按模型失败、收益或标签难度筛源。

- 4/2/12/4 的额外训练 seeds：63005（P2）、63006（P0）、63014（P3）。
- 4/3/16/6 的额外训练 seeds：63004（P3）、63005（P0）、63008（P1）。
- 两配置的原 63000/63001 为训练，63002 为验证，63003 为测试。

所有源的完整轨迹、局部分支、重复背景派生问题均同组。规范化拓扑检查忽略玩家、
commitment、goal 的重命名，防止同一图仅改编号后跨划分。
验证/测试各只有两种 learner ID，不据此声称已经完成所有角色的泛化评估。

### 5. B 评分不奖励猜真值，也不混淆协议失败

`b_eval.py` 输出：

- 全部请求精确集合准确率、有效输出上的精确率；
- 有效输出的错误排除数、额外保留可能数；
- 缺失、格式失败单独计数，不伪装成 B 推断错误；
- 按源游戏、真实集合大小分层，以及成对更新的两端同时正确率。

测试集上的 always-all 基线精确率为 38.1%，平均多保留 1 个可能；它没有错误排除，
但不能因此被判定为好的 B。金标回填自检精确率 100%，只是评分管线自检，不是模型结果。
训练多数类基线也是完整三元素集合。

### 6. 导出可检查的工具调用监督

最终使用 `b_sft_ready_roles_v1` 下的导出，不使用早期审计目录中的草稿 chat 文件。
System 明确写出 1=want、0=neutral、-1=avoid、ALL_OF、不可逆 commitment、
offer/menu 响应和 turn 的含义，以及 learner/target 的区别。

SFT 目标只有经验证的 SUBMIT_JUDGMENT 调用，没有编造教师推理链。
允许模型简短推理，不要求输出概率、Q 或 plan variable。模型输入不包含证书、
剩余类型编号、真实伙伴行或金标。推理 prompts 和 gold labels 分文件导出。
训练端必须 mask system/user/tool description，仅监督 assistant completion。

使用本地官方 Qwen3-4B-Instruct-2507 tokenizer/template，revision
`cdbee75f17c01a7cc42f958dc650907174af0554`，逐条检查工具 JSON、prompt/completion
边界和 token 边界。最终长度统计保存在 `b_sft_ready_roles_v1/token_lengths.json`。
849 条样本的完整序列最长 3,385 tokens，工具调用监督目标为 26–30 tokens；
全部可容纳于 4,096 token 序列，不需要截断。这不代表单卡全参数训练显存已验证。
这确认的是数据/模板可用性，尚未跑远程 vLLM/Hermes 预检或 ROLL GPU 训练。

## 运行与文件

原始和中间记录全部在 `.gitignore` 排除的 `new/local_data/` 下，没有加入 Git。

```bash
# 第一批：8 个源游戏，固定伙伴策略。
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.b_data_audit \
  --output-dir new/local_data/b_independent_focal_v1

# 独立重放和首批 grounded chat 导出。
PYTHONPATH=/tmp/benac-audit-tokenizer:third_party/negotiation_benchmark/src \
python -m benac_p.b_data_validate \
  --source-dir new/local_data/b_independent_focal_v1 \
  --output-dir new/local_data/b_sft_ready_v1 \
  --tokenizer-dir /tmp/benac-qwen-tokenizer

# 只添加训练角色，不改验证/测试数据。
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.b_role_coverage \
  --source-dir new/local_data/b_independent_focal_v1 \
  --output-dir new/local_data/b_independent_focal_roles_v1

# 最终导出。旧问题只有在数据、源游戏和策略哈希均一致时才能复用既有验证。
PYTHONPATH=/tmp/benac-audit-tokenizer:third_party/negotiation_benchmark/src \
python -m benac_p.b_data_validate \
  --source-dir new/local_data/b_independent_focal_roles_v1 \
  --output-dir new/local_data/b_sft_ready_roles_v1 \
  --tokenizer-dir /tmp/benac-qwen-tokenizer \
  --verified-base new/local_data/b_sft_ready_v1

# 以后有模型输出后，单独评分；prediction 每行包含 id 和 answer。
PYTHONPATH=third_party/negotiation_benchmark/src python -m benac_p.b_eval \
  --gold new/local_data/b_sft_ready_roles_v1/test_gold.jsonl \
  --predictions /path/to/predictions.jsonl \
  --pairs new/local_data/b_independent_focal_roles_v1/update_pairs.jsonl
```

复跑使用新输出目录。`/tmp/benac-audit-tokenizer` 是本机已有的 tokenizers 依赖位置；
其他机器只需相应的 tokenizers/Jinja2 和同 revision tokenizer 文件，不依赖这些绝对路径。
本轮没有新下载模型或安装依赖。

源码：`b_training_data.py`、`b_oracle.py`、`b_data_audit.py`、`b_role_coverage.py`、
`b_data_validate.py`、`b_eval.py`，均位于 `third_party/negotiation_benchmark/src/benac_p/`。
相关新增和回归测试共 43 项通过。配置、源码指纹、数据校验和随本地运行保存。

## 已处理的范围与仍需实验回答的事

本轮处理了可生成性、背景泄漏捷径、标签核验、重复/已知样本、角色覆盖、源划分、
评分口径和工具格式。14 局核心生成耗时约 445 秒，不含后续独立重放和全部文件导出。

不能把这解释成“B 能力已经解决”：尚无 Qwen 的本轮预检、B-SFT 或迁移结果。
自然轨迹仍常在早期辨别出偏好；增加候选数没有保证长期不确定性。
固定策略下的精确标签不自动适用于未知策略或伙伴策略池。
正式 Diagnose 的角色预检及新的完整能力缺陷/修复效应仍须另行验证，本轮没有改写其结果。

下一阶段应使用这份有限规模语料进行 B-only 模型预检和小规模 SFT，按集合大小及源游戏
检查是否超过无推断基线，并分别检查错误排除和额外保留。P 暂不混训；B 的学习效果成立后，
再用固定 P checkpoint 检查判断改善是否有助于决策。不能用终局收益上涨替代 B 的直接评估。
