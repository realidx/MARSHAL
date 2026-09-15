# 首轮小样本检查名单

仅完成选题，尚未调用模型。原 B/P 每池 4 题，新 B 各层 4/4/2/4/4 题，self-play 各计分层 4 个开局。

这是按能力和对照关系分层的诊断集，不按总体数据比例抽取，平均成绩不能当作完整数据集准确率。层内用固定 seed 20260915 的 ID 哈希选择；未读取任何模型结果。

原 B/P 每池 2 train + 2 validation；直接读取真值题和 held-out test 均不入选。新 B 的层 0–2 没有可用 validation，均从 train 抽取；层 3–4 各 2 train + 2 validation。

建议每道 B/P 采 8 次（368 次回答），每个 self-play 开局采 4 场（48 场）；次数尚未执行。原 B/P 已有基线，可先按这份名单提取旧回答，避免无条件重跑。旧 validation 每题只有 4 次，若对齐到 8 次需要补采并保留批次标记。

## B/P 逐题名单

| 来源 | 类别／层 | split | ID | 选取理由 |
|---|---|---|---|---|
| 原 B/P | B/formation / stage 0 | train | `0699ae6fcd16e2a4db06` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/formation / stage 2 | train | `cb104be8bf0c7e4d0f97` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/formation / stage 0 | validation | `002723e1f59bfeb073aa` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/formation / stage 1 | validation | `8388673040dd7708ecfb` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/maintain / stage 0 | train | `f50ee1b492ef340a5ccf` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/maintain / stage 1 | train | `f0dc964863ca614b0d7c` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/maintain / stage 1 | validation | `3c6d6e52763973e525f8` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/maintain / stage 2 | validation | `ce8000513f97992ed11d` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/update / stage 1 | train | `285a539c5478123a2009` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/update / stage 2 | train | `c76e67f3abdd8ae5cadb` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/update / stage 0 | validation | `5417077830a43c91de97` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | B/update / stage 1 | validation | `f76286017755f185f72c` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/complete / stage 0 | train | `6d6f8bfdbd54504328ea` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/complete / stage 1 | train | `4e6557e0294c9495d344` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/complete / stage 0 | validation | `0f67ee777a0dd5908c3f` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/complete / stage 2 | validation | `4e2cac0f2eba7ad622ba` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/uncertain / stage 0 | train | `caf8ef5e89e4f40a5b3a` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/uncertain / stage 1 | train | `dfd44943249fde4a3ce2` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/uncertain / stage 1 | validation | `e3c47b18b8b4fa46e870` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/uncertain / stage 2 | validation | `86af7d0f7a292b74e486` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/result_use / stage 1 | train | `4622754faf052bbf46ca` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/result_use / stage 2 | train | `d71af8ccfae85c56f205` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/result_use / stage 0 | validation | `b534c29ff71c3c99179a` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/result_use / stage 2 | validation | `24c1c964060a4d66edd7` | 每池 2 train + 2 validation；优先覆盖难度、人数和答案／belief 差异；哈希打破并列 |
| 原 B/P | P/information / stage 0 | train | `cb2ba36c583f31e33193` | 调查严格提高自身收益；与下题同 contrast_group |
| 原 B/P | P/information / stage 0 | train | `c6ffc4005ef0b4b3b00c` | 配对的最后机会不调查反例 |
| 原 B/P | P/information / stage 2 | validation | `0c9d104af3b28b7c5d71` | 验证集：调查严格提高自身收益 |
| 原 B/P | P/information / stage 2 | validation | `db6e17a60c3e337fd3af` | 验证集：仍有后续机会但不应调查 |
| 新 B | B/formation / L0 | train | `34da1223fa394d51c38f` | 两候选：接受／拒绝导致相反结论的形成对照 |
| 新 B | B/formation / L0 | train | `ee0c38cd5b14b726d4bf` | 两候选：接受／拒绝导致相反结论的形成对照 |
| 新 B | B/update / L0 | train | `e4e9396536f45f0de445` | 两候选：承接旧 belief 后更新 |
| 新 B | B/maintain / L0 | train | `fdcef144ef63d8c67397` | 两候选：无关证据下维持 |
| 新 B | B/formation / L1 | train | `766ef4dc7ed36966c875` | 同为接受，改变观察者收益后 neutral 的选择不同 |
| 新 B | B/formation / L1 | train | `6f8a9c7952f7c209ddd7` | 同为接受，改变观察者收益后 neutral 的选择不同 |
| 新 B | B/update / L1 | train | `fa2123708ddbd4d1ecca` | neutral 平局：拒绝后的更新 |
| 新 B | B/maintain / L1 | train | `40faa0b8fbc106166729` | 三候选：无关证据下维持全集 |
| 新 B | B/maintain / L2 | train | `6cfbe5e792966eb339da` | 相同多目标收益背景下，接受维持／拒绝更新对照 |
| 新 B | B/update / L2 | train | `ed731ab1d7acb047447f` | 相同多目标收益背景下，接受维持／拒绝更新对照 |
| 新 B | B/formation / L3 | train | `aef4ba13b7dec54f86c7` | 多元素集合内明确 favored；接受／拒绝对照 |
| 新 B | B/formation / L3 | train | `e0229e76ada9fe7c5a10` | 多元素集合内明确 favored；接受／拒绝对照 |
| 新 B | B/update / L3 | validation | `cabfe149a8d3ebf3b237` | 多元素集合内明确 favored；接受／拒绝对照 |
| 新 B | B/update / L3 | validation | `f095d91d487f239dda5f` | 多元素集合内明确 favored；接受／拒绝对照 |
| 新 B | B/update / L4 | train | `42f514c50d2e9a21657e` | 联合约束：集合不变的 favored 更新／同时改变集合的对照 |
| 新 B | B/update / L4 | train | `349c390e78f9013b1ce1` | 联合约束：集合不变的 favored 更新／同时改变集合的对照 |
| 新 B | B/update / L4 | validation | `a88f4f75481a717601be` | 联合约束：集合不变的 favored 更新／同时改变集合的对照 |
| 新 B | B/update / L4 | validation | `cd84696e6601b48c909b` | 联合约束：集合不变的 favored 更新／同时改变集合的对照 |

## Self-play 开局

| 课程层 | split | 人数 | 每人轮数 | ID |
|---|---|---:|---:|---|
| foundation / linear | train | 2 | 2 | `cooperate_a-r2-s4` |
| foundation / linear | train | 3 | 3 | `third_party_intro-r3-s0` |
| foundation / linear | train | 2 | 4 | `cooperate_a-r4-s0` |
| foundation / linear | validation | 2 | 2 | `validation-2p-0` |
| adaptation / mixed | train | 2 | 3 | `partner_type_choice-r3-s0` |
| adaptation / mixed | train | 3 | 4 | `third_party_uncertainty-r4-s0` |
| adaptation / mixed | train | 2 | 2 | `partner_type_choice-r2-s1` |
| adaptation / mixed | validation | 3 | 3 | `validation-3p-2` |
| tradeoffs / binary | train | 2 | 5 | `interacting_commitments_a-r5-s0` |
| tradeoffs / binary | train | 3 | 2 | `third_party_conflict-r2-s0` |
| tradeoffs / binary | validation | 2 | 2 | `validation-2p-2` |
| tradeoffs / binary | validation | 2 | 3 | `validation-2p-5` |

## 文件与边界

- `bp_requests.jsonl`、`bridges_requests.jsonl`：可直接发送的无标签模型请求，沿用冻结的 B/P 原生工具、temperature 0.8、1024 输出预算。
- `*_tasks.local.jsonl`：本地评分标签；不作为模型输入。
- `selfplay_resets.environment.jsonl`：环境重置用，包含真实隐藏世界；只能经 safe_observation 向模型生成输入。
- `selection.jsonl`、`manifest.json`：选取理由、来源与文件哈希。
- self-play 的 validation 按 completion 对应课程层归类，不声称其难度与 train 相同；未筛 solver 收敛或高收益开局。
- 新 B 对照题通常来自同一家族；重复采样及相邻 checkpoint 均不增加独立场景数。
- 当前 P 库尚缺计划中的新增后续决策配对，不能把本次 result_use 选题声称为已补齐该缺口。
- 旧 self-play 的 --suite all 不读取本名单；本次只冻结开局，运行前需要接入显式 reset 文件。
