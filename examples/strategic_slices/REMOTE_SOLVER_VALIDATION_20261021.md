# 远端CPU求解包：本地验收与版本边界

2026-10-21，协议`strategic-parents-remote-terminal-solver-v1`。
用户要求提供完整远端指示，不预设已知机器配置；本轮未连接服务器或提交远端作业。

交付：[完整远端指南](REMOTE_SOLVER_20261021.md)，
[独立压缩包](../../new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz)，
[SHA256校验文件](../../new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz.sha256)。
压缩包178204字节，55个清单文件，SHA256：
`44f93be412e1c369db8390168c3892e10b4450c98820de6a6504b9a412a08bc0`。

固定输入仍是同一个100父游戏，SHA256
`30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad`。
不把本地7例已认证profile静默混入远端：第一轮从同一池重新完整求解；
扩展run只从相同包/数据/数值环境的前一轮显式导入成功reference并保留来源参数。

## 相对本地12例探针的变化

- 支持全部100局、保守自动worker数和可调并发，每worker数值库1线程；无需GPU。
- base单次求解300秒，extended900秒，扩大候选、joint cells/evaluations和sweeps。
- extended按uniform、Dirichlet信息集初始化seed0/1/2的固定顺序取首个认证策略；
  不使用Q/S/D选策略，不更换题目或放宽认证容差。
- 完整原生终局、epsilon1e-8、response tie1e-9及独立完整偏离/平局审核不变。
- 逐局/初始化保留结果、日志和完整快照；中断中的初始化重算，不冒称solver内部checkpoint。
- 支持明确的断点恢复合同、执行锁、父进程取消子进程、硬时限，以及单独重载NPZ的完整审核。
- 正常完成所有尝试与100局全部认证分别标记；仍缺失的局保留，不制造标签。

## 实际验收

在仓库之外的临时目录解压**最终归档**，仅用本地Python3.12.2、NumPy1.26.4、SciPy1.12.0：

1. 包内hash/100父游戏检查及6项规则/计数CPU测试通过。
2. 对冻结index0做真实完整终局求解，并从保存的NPZ重新构树、重做独立认证与policy hash检查。
3. 同合同恢复完整run，已认证reference未重写；显式导入成功策略后仍能按原构造参数完整复核。
4. 极短预算强制失败，按缺失记录；扩展模式4个声明的初始化全部按顺序尝试。
5. SIGTERM中断后释放锁，保留未完成execution；恢复另建execution继续。
6. 失败局在新扩展run认证后立即停止后续初始化。
7. 改变恢复参数、篡改reference或输入数据均被拒绝；单例smoke不能冒充100局认证完成。

机器可读[VALIDATION.json](../../new/remote_solver_bundle_20261021/VALIDATION.json)
记录11项集成断言、实际命令/退出码/耗时/源码hash；日志与运行证据一并保存。
早期候选归档另存`new/remote_solver_bundle_20261021_candidate1/`，最终使用上列SHA的归档。
候选与最终版的取消处理实现不同，不能混续；最终归档已重新完整执行上述验收。

这只验证本地CPU交付流程和一例真实父游戏，不是远端Linux/Slurm、100局认证率、
GPU性能、模型D、训练效果或一般和求解收敛保证。现有solver的失败仍可能需要方法改进。
生产v8、旧checkpoint、prompt、reward/advantage和既有题库身份均未改变。
