# 调查前后标签链条一致性核验v1

2026-11-04。承接235调查入口的答案访问诊断，直接核对该事前收益与已有逐条私人答案S。
不改主S、Oracle、父池或800标准；用于回答“调查—获得答案—下一次选择”的监督口径能否对接。

每个已完成调查分支，从相同pre-query belief强制调查后，按原生对手reference展开到第一次本人决定或终局。
不优化本人行动、不重求均衡，不使用前一诊断forest的局部节点映射；重新通过原生全局节点/实际历史定位。
对每个首次本人完整信息context，核对条件belief与保存profile相同，读取该次目标的既有private S。
验证`full_query - blind_query = sum(probability_of_first_context * its_private_S)`，终局前无本人动作的分支两边相同抵消。
另分别核对full与blind期望收益，而不只检查差值；记录每个后继原node/cell、概率和当前/后续S分解。

默认workers2、数值线程1、子节点缓存8192，匹配误差<1e-7；所有51父/353条已核验调查分支全部检查。
任何缺失post-context/不一致belief/不一致收益保留错误，不把结果写成0。
这是已有标签的独立衔接核验，不是新的选择分数或模型D；生产active v8，800/split/test未执行。
