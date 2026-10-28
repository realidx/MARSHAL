# 三人复杂度独立研究

研究版本`three-player-complexity-study-v1`，生产active仍v8。
[本地有效性与第25局结论](../../examples/strategic_slices/THREE_PLAYER_COMPLEXITY_20261023.md)，
[远端完整指示](../../examples/strategic_slices/REMOTE_THREE_PLAYER_20261023.md)。

`pool_v1`保留原33局几何的H2/H3/A2H2各33局（99个候选），没有修改旧100。
H2是建议先跑的设置：两个隐藏偏好分属不同玩家，9个world；2RR/调查1/报价1不变。
`small_endgames_v1`是预定原index3/7、每种设置的原生终局子局；不是完整父游戏认证。
`full_H2_reuse_v1`对原index7匹配上轮capacity raw/reference，重新完整认证并测Q/S，明确保存复用来源。
`parent25_v1`用两个预定调查目标对照检验原25的最后报价信息价值；不补齐它的完整开局reference。

核心命令（仓库或独立包根目录，先设置PYTHONPATH及单线程数值库）：

```bash
python -m new.three_player_complexity_v1_20261023.remote doctor
python -m new.three_player_complexity_v1_20261023.validate --output new/study_my_tests
python -m new.three_player_complexity_v1_20261023.pool --output new/study_my_pool
python -m new.three_player_complexity_v1_20261023.remote run --jobs new/study_my_pool/games.jsonl --output new/study_my_run --workers 1
python -m new.three_player_complexity_v1_20261023.remote audit --run new/study_my_run --output new/study_my_reload --workers 1
```

上面的完整pool命令会尝试99个研究候选；远端交付包另有`data/H2.jsonl`方便先只跑33个H2。
生成包使用`python -m new.three_player_complexity_v1_20261023.build_bundle --output <新目录>`；
读取原始99终局Q/S统计作为历史baseline，只导出紧凑指标/身份，不包含模型或大量旧日志。
默认最大600000公共节点、Linux每case8GiB虚拟内存、1worker，具体软/硬预算在PROTOCOL和实际run snapshot中。
失败、超时、认证成功但测量缺失分开记录；零counterfactual节点的S为缺失。
不因Q/S挑reference，不改训练GRPO，也不在本地跑99个完整扩展游戏。
