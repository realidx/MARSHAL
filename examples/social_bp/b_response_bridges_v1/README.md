# B 行为推断入门候选 v1

本包用于替换直接读取真值的 B 教学题，并检查更浅的推断链是否提供可用学习信号。它不是已验证学习效果的新完整训练集。旧 384 题基准和本轮 P 题没有重写，尚未调用 base model 或启动训练。

## 教学次序

| 层级 | 题数 | 推断负担 |
|---|---:|---|
| 0 | 12 | 从正确的 want/avoid 旧 belief 和一次末回合回应排除一个候选；同时给形成与维持对照 |
| 1 | 24 | 加入 neutral；改变另一方收益，比较利他平局；包含真正无关的行为证据 |
| 2 | 4 | 两目标同时完成，需加总收益；行为出现但输出也可能完全维持 |
| 3 | 12 | 单一隐藏偏好；原有残余平局机制带来明确的支持差异，possible set 和 favored 不再重复 |
| 4 | 16 | 两个隐藏偏好；联合生成约束或重叠目标使 favored 出现/消失，包含集合保持全集的更新 |

共 68 个 checkpoint：形成 34、更新 25、维持 9。单/双/三元素答案分别 22/24/22，直接读取真值题为 0。16 题有多元素集合的具体 favored，其中 4 题是集合不变的 favored-only 更新。

这些是 **5 个结构家族的教学变体与配对 checkpoint**，不能算作 68 个独立游戏，也不以数量宣称覆盖充分。层级是根据推断结构设定，是否真的对模型由易到难仍需实测。层级 4 没有覆盖 favored 反转、长历史证据累计及完整私有信息视角；那些应保留为后续能力目标。

## 游戏和标签依据

- 两名玩家、2–3 个 ALL_OF 目标，末次 OFFER 由任务给定，玩家自主选择 ACCEPT/REJECT。给定 OFFER 不是偏好证据，自主回应才是。
- 偏好按当前公开生成规则展开支持；没有把原始人工目录限制偷偷保留在 teacher 中。每人至少想要一个目标、每个目标至少有一名非 neutral 玩家等约束均保留。
- 自身收益优先，再比较他人总收益，最后沿用原有残余平局随机化；未新增玩家类型、行为噪声或启发式伙伴。
- 每道题都有独立计算的完成目标、双方收益、回应似然与 posterior，逐项对照 solver 的响应策略和标签。独立计算只使用响应者自己知道的偏好与公开的其他玩家偏好。
- 旧 belief 也从真实先验与所给历史核验，不手填一个方便的 possible set。不会要求从缺失信息中恢复标签。
- favored 维持现有精确定义；本包先使用明确的并列和倾向，不用微弱领先充当入门题。不新增部分分、答案 retry 或 length penalty。

`review.md` 是可以直接阅读的题面例子，末尾另列本地教师核算。教师核算、内部权重和标签不会进入 `requests.jsonl` 的 model request。

## 家族隔离与小规模 probe

沿用旧基准已有家族的 split，新结构作为开发训练候选：train 36、validation 10、test 22。与旧 test 同家族的 22 题没有导出模型请求。`requests.jsonl` 因而只有 **46 题，每题 8 次，共 368 次回答**。保持 native SUBMIT_BELIEFS、temperature=0.8、max_tokens=1024。这个包的 manifest 不是旧固定 256+64 launcher 的 manifest，不应直接覆盖旧 bundle。

本地 Qwen3-4B-Instruct-2507 tokenizer 检查：完整 tool prompt 1215–1312 tokens；响应预算仍为 1024。`token_audit.json` 中的 roundtrip 是人工构造正确工具提交的评分检查，不是模型正确率。

当前跨家族 validation 主要检查 favored 类，不构成所有入门层的完整泛化验证。train 与 validation 的角色分别报告，不能把本包平均成绩当作完整 B 泛化成绩。已有 B 验证题继续作为迁移对照。

## 文件与复现

- `tasks.jsonl`：本地完整教师题目；`audit.json`：逐题独立核验和对照组。
- `requests.jsonl`：无标签、无教师权重的可见请求；`probe_manifest.json`：冻结哈希、数量与采样设置。
- `review.md`：题面阅读样例。

在仓库根目录，用已有本地 Python 环境生成到一个新目录：

```bash
python -m training.b_sft.build_b_response_bridges --out /tmp/b_response_bridges_review
python -m unittest training.b_sft.test_b_response_bridges training.b_sft.test_social_bp_training
```

后续下载正式采样的 `samples.jsonl` 后，本地评分（不要混入 preflight 或 retry）：

```bash
python -m training.b_sft.score_b_response_bridges \
  --pack examples/social_bp/b_response_bridges_v1 \
  --samples /path/to/formal/samples.jsonl \
  --out /path/to/new/local_scoring
```

先看每层、每种形成/维持/更新任务的混合奖励组是否出现，再看截断、错误全集、集合正确但 favored 错误。不能只看平均正确率：如果提高只来自维持题，核心形成和更新仍可能没有学习起点。只有实测确认更浅题能提供信号后，才决定替换完整训练集的具体配额及晋级条件。

未来调用 `build_bp_pilot.write_dataset` 重新组装时，B 直接读取题已改为单独保存到 `direct_reading_checks.jsonl`，不再补足更新题配额。此改动未自动重新生成旧冻结数据。
