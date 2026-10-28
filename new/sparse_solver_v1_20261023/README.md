# Solver修复研究，2026-10-23

正式说明与结果见 [SOLVER_REPAIR_20261023.md](../../examples/strategic_slices/SOLVER_REPAIR_20261023.md)。
这是独立CPU研究目录，没有激活训练版本。默认算法只需NumPy/SciPy；`deps`中的PyGambit是可选对照，不是默认求解依赖。

已批准的有限窗口，一条命令生成、补充搜索并独立复核100个reference：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.sparse_solver_v1_20261023.pipeline --output new/bounded_reference_my_run --workers 2
```

该入口先检查研究版本注册source hash；代码变化需登记新版本。输出`references/REFERENCE_INDEX.json`和`references/COMPLETE.json`；缺失任何一局时不会写成功完成标记。该集合尚不含新Q/S/D或训练selection。

完整终局研究及独立复核：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.sparse_solver_v1_20261023.run --output new/terminal_solver_my_run --indices all --workers 2
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.sparse_solver_v1_20261023.verify --run new/terminal_solver_my_run --output new/terminal_solver_my_reload --workers 2
```

沿用已批准窗口的整批研究命令：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.sparse_solver_v1_20261023.window_run --output new/window_solver_my_run --workers 2
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m new.sparse_solver_v1_20261023.window_verify --run new/window_solver_my_run --output new/window_solver_my_reload --workers 2
```

输出目录必须不存在。`--workers`是CPU进程数；没有GPU要求。每次运行保存参数、完整source副本和hash、数据hash、实际环境、成功与失败结果。失败题保留，不赋0、不换题。

`reduction.py`和`engine.py`是主要有效改动；`joint.py`为原数值残差的研究包装。
`sequence.py`、`double_oracle.py`、`gambit_backend.py`及其他单题实验是独立候选/诊断路径，不能把它们的普通Nash候选或低数值残差当作通过完整原生认证。

局部运行测试：

```bash
PYTHONPATH=.:third_party/negotiation_benchmark/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest new.sparse_solver_v1_20261023.test_sequence -v
```
