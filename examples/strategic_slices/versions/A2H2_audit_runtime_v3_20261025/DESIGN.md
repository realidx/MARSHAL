# A2H2审计启动环境 v3

冻结paired v1和LP v2方法/source保持原身份。首次直接启动paired v1在导入阶段缺少benac_p路径，
尚未创建分析输出或测量。失败单独记录，不能声称此前完成过验证。
本版本只在导入领域模块前显式加入仓库root与third_party/negotiation_benchmark/src，
设置5个数值库线程变量=1；实际launcher argv、原PYTHONPATH、resolved sys.path写入pipeline_snapshot。
既有paired v1与LP v2计算函数不改；通过同一启动器分别调用。选择、Q/S与所有比较定义均不变。
生产active/prompt/D/训练均不变。当前冻结时新启动器尚未实际执行，完成结果另行留档。
