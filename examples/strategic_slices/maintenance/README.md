# 仓库维护记录

## 2026-10-29：运行日志退出Git跟踪

按用户要求，将146个已跟踪日志和生成的控制台/作业输出改为本地保留、Git忽略，约4.28 MiB。
包括训练/服务/测试日志、Slurm输出及两个LaTeX生成的`.out`文件；同时补齐轮转日志、
stdout/stderr、TensorBoard、wandb等后续产物的忽略规则，取消旧测试目录对两个`.log`的例外。

执行仅使用`git rm --cached`，本地文件逐项校验存在且hash未变；没有删除文件、提交或改写Git历史。
Git暂存区显示这些日志为删除，是取消版本跟踪的表现。
忽略规则不会释放本地磁盘或缩减历史Git对象；未来新clone不含本次退出跟踪的原始日志，旧提交仍保留它们。

代码、论文源码、题库、Oracle reference/标签、pipeline_snapshot、source快照、版本注册、报告和hash继续跟踪。
实验参数、prompt、Q/S/D、训练行为和生产active v8均无变化；本次属于仓库维护，不创建新的实验版本。

完整路径、大小、SHA256和检查结果见[维护清单](log_tracking_20261029.json)。
