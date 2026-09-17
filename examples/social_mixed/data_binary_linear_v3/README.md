# Binary / linear 训练数据 v3

当前唯一训练数据入口 `training.social_mixed.core.DATA` 指向本目录。Mixed 完成规则已从训练、开发验证、结构测试、self-play 配置及对应模型请求中排除。历史 v1/v2 保留用于结果追溯及过滤来源，不由当前训练入口加载。

| 数据 | binary | linear | 合计 | 删除 mixed |
|---|---:|---:|---:|---:|
| B/P 训练 | 278 | 148 | 426 | 16 |
| B/P 验证 | 248 | 27 | 275 | 26 |
| B/P 测试 | 23 | 21 | 44 | 21 |
| self-play 训练 | 48 | 48 | 96 | 48 |
| self-play 验证 | 16 | 16 | 32 | 16 |

不存在单独的 self-play 测试配置文件，未虚构新测试集合。4 道仅诊断的 linear 题保留；P4 调查—答案利用链接均完整。生成的 requests_train/validation/test 与保留题一一对应。

筛选依据为每个目标的真实 `binary` 字段，而非题目名称或元数据。保留行的输入、标签、ID、split 与 v2 完全一致，不重新分配测试结构或重求解 teacher。训练/验证/测试仍结构隔离；训练包含 28 个几何家族，验证 15 个、测试 11 个（含 self-play 几何）。

生成器：`python -m training.social_mixed.prepare_binary_linear`。它从 v2 过滤并拒绝覆盖已有 v3。Manifest 记录来源哈希、删除数量、模式计数、请求文件及辅助链接校验。CPU 检查：`python -m training.social_mixed.preflight`。

正式训练：`bash examples/social_mixed/start_training.sh h100-96 both`，详见 [FULL_TRAINING.md](../FULL_TRAINING.md)。Mixed 训练组仍指 B/P+self-play，与已排除的 mixed 完成规则无关。提交回执及 experiment.json 明确记录仅 binary/linear。数据哈希已改变，不能续训旧 v1/v2 实验。

本地完成静态和回归检查，未运行 GPU 训练；保留此前关于 test 来源历史使用情况尚未核实的限制。
