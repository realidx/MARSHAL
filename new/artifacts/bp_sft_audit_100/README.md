# BENAC-P：100 个源游戏的 B/P-SFT 数据审计

这是一批 **development_audit_only** 数据。用于审查生成分布、监督正确性与成本，不是最终训练集或未见测试集。没有调用模型、执行 SFT 或产生新的能力诊断结果。

先读 [report.md](report.md)，机器可读统计见 [summary.json](summary.json)。

| 文件 | 内容 |
|---|---|
| `source_games.json` | 100 个源游戏，seed 50000–50099；含内部偏好和候选目录，不作为模型输入 |
| `games/*.json` | 每游戏的完整轨迹、证据过滤、决策状态、精确标签、分支及耗时 |
| `examples.jsonl` | 1,347 条去重的 messages/tools 示范；967 B、380 P |
| `labels.jsonl` | 对应答案、源游戏归属和采样来源 |
| `planning_cases.jsonl` | 完整合法动作、Q、全部最优动作和展示索引映射；仅用于审计 |
| `failures.jsonl` | 搜索失败记录；本批为空，215 个超出 P 剩余回合预算的状态另记于各游戏 |
| `token_lengths.jsonl` | 每条示例的实际 token 长度和目标 loss-mask 边界 |
| `tokenization_audit.json` | 固定 Qwen tokenizer/template 的语义与序列化验证结果 |
| `manifest.json` | 生成参数、版本、源文件 hash；全部种子事先固定，无失败替换 |
| `source_snapshot/` | 与 manifest hash 对应的生成源文件，以及本次验证脚本 |
| `checksums.json` | 数据包文件校验和 |

## 如何使用

训练候选数据在 `examples.jsonl`，只把 `messages` 和 `tools` 交给模型模板。`id`、`source_game`、`case_id`、`kind`、`split` 是元数据，不序列化进 prompt。内部 Q、真实偏好和来源证书不进入模型输入。P 的正确显式伙伴判断是任务本身的 oracle assistance。

示范是直接 tool submission，没有人为编造的 reasoning。模板允许简短推理或直接提交。训练仅监督目标 assistant completion，保留 `<|im_end|>`；不训练 user/system 或公开历史中的其他玩家行动。

所有 1,347 条示例通过本地模板/token roundtrip、目标语义和 token 边界检查。总序列约 209 万 tokens；最长 4,436 tokens，75 条超过 4,096。不得静默截断。远程 vLLM/Hermes 和实际 GPU trainer 尚未验证。

## 正式训练前需要处理

- 149/380 个 P 状态所有动作同值，需与有区分度的策略数据分开采样。
- 400 条空历史 B controls 占比较高，不能直接照搬为正式训练配比。
- 有 62 条 MENU 示范，但没有“仅 MENU 最优”的局面，也没有 ego CHOOSE_1/CHOOSE_2 示范。
- 100 个不同源游戏包含 95 个去标号公共超图；未来划分应将同源派生和同构增强放在同一组。
- 200 条完整采集轨迹都完成，283 个干预行动保留了所有证据分支及其原始权重。这些分支不是独立游戏。
- 595 个不同 ego 决策状态都验证了合法前缀回放；380 个 P 标签完成精确搜索。84 个源游戏另通过一处短后续局面的独立 ego 搜索递归比较；其余没有声称已做该比较。独立递归仍共享伙伴 kernel 和环境转换。

## 复现

生成不需要 GPU，仅需要项目环境与 numpy：

```bash
PYTHONPATH=third_party/negotiation_benchmark/src \
python -m benac_p.sft_data_audit \
  --output-dir new/artifacts/bp_sft_audit_100 \
  --seed 50000 --games 100 --workers 4 --resume
```

`--resume` 会检查源文件 hash。工作区实现发生变化时应使用新输出目录，或在隔离副本中恢复 `source_snapshot` 对应版本，不要覆盖正在开发的代码。重新导出后需要重新运行 tokenizer 验证。

验证工具需要 `tokenizers`、`jinja2` 及本地 tokenizer 文件：

```bash
PYTHONPATH=third_party/negotiation_benchmark/src \
python -m benac_p.sft_audit_validate \
  --output-dir new/artifacts/bp_sft_audit_100 \
  --tokenizer-dir /path/to/pinned-tokenizer
```

tokenizer 目录包含 `tokenizer.json`、`tokenizer_config.json` 和本数据包的 `tokenizer_provenance.json`（复制为 `provenance.json`）。两个 tokenizer 文件来自 `Qwen/Qwen3-4B-Instruct-2507` 的固定 revision `cdbee75f17c01a7cc42f958dc650907174af0554`，下载地址为：

```text
https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/cdbee75f17c01a7cc42f958dc650907174af0554/tokenizer.json
https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/cdbee75f17c01a7cc42f958dc650907174af0554/tokenizer_config.json
```

本批没有调整已有 diagnose 或 dependency 实验的逻辑。生成器与验证器以独立模块添加。
