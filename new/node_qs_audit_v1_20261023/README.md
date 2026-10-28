# 当前节点Q/S与交互性CPU审计

结果、口径与局限见[完整报告](../../examples/strategic_slices/SOLVER_QS_AUDIT_20261023.md)。
研究版本`node-qs-interactivity-audit-v1`，生产active保持v8。没有改prompt/游戏/训练或测D。

需要上轮冻结的`new/sparse_solver_v1_20261023/full100_v1`和
`pipeline_e2e_v1/references`，只读取保存reference，不重新求均衡。
依赖沿用本地CPU NumPy/SciPy；不需要GPU、模型、Gambit。

终局99局（25缺失保持为缺失），输出目录必须不存在：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.run --mode terminal --output new/qs_terminal_my_run --workers 2
```

统一开局锚定窗口100局（独立口径）：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.run --mode window --output new/qs_window_my_run --workers 2
```

聚合、强制动作/当前行动与后续S分解：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.analyse --run new/qs_terminal_my_run --output new/qs_terminal_my_analysis
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.overview --run new/qs_terminal_my_run --output new/qs_terminal_my_overview
```

独立LP与S保守区间、严格最优调查的私有答案访问诊断：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.witness --run new/qs_terminal_my_run --output new/qs_terminal_my_witnesses --workers 2
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.query_diagnostic --run new/qs_terminal_my_run --output new/qs_terminal_my_query_access --workers 2
```

第25题失败诊断、真实游戏独立原生复核、六项CPU测试：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.diagnose25 --output new/qs_my_diagnosis25
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.case_review --run new/qs_terminal_my_run --output new/qs_my_native_review
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 python -m new.node_qs_audit_v1_20261023.validate_lp --output new/qs_my_cpu_tests
```

每次run先核验注册source，保存完整source副本、原始注册文件、实际CLI、resolved config、环境与输入hash。
`cases/<index>/labels.jsonl.gz`为逐节点完整表，`examples.json`为当前真实历史/承诺/pending的可读核查数据。
主Q/S依赖同一选定reference；零counterfactual reach的S为null，不能以缺失当零信号。
历史S以一条完整公共回合事件为单位，保留当前完整物理状态；遗漏策略的剩余平局均匀混合。
`query_diagnostic`是事前答案访问对照，不是当前节点S。LP区间只核查每父游戏每通道的一个最大S见证，
不声称所有标签均为多均衡或所有遗漏策略下不变。
