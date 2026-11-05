# 800筛选v3：结果JSON保存修复

2026-11-04。v2第一阶段已证明硬约束可行、父×用途覆盖364，但objective为np.int64，写OPTIMIZATION时TypeError，未导出SELECTION。
v3仅把日志objective转Python float；rank命名空间显式固定为v2，保证同seed下候选缩减和hash顺序不变。
配额、重复/窗口/信息渠道/split/保护见证/目标函数/60秒时限均继承[原设计](../slice800_selection_v1_20261104/DESIGN.md)。
旧失败run、v1语法启动失败保持身份；v3源码AST解析与np.int64目标值JSON转换检查通过后注册。
每次实际运行有完整pipeline_snapshot；正式数据仍待全部原生导出复核，D/训练未跑，active v8。
