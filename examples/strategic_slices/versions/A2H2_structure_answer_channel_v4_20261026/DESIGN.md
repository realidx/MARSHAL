# 结构诊断v4：第62/78局调查答案渠道

v3发现代表路径62调查严格优于非调查、78与非调查平局。为避免把公开调查行为的信号收益当私人信息收益，
固定同一公共调查行动、额度状态、历史和对手reference，仅在focal全部后续决策屏蔽该目标答案。
恢复原生query祖先剩余子树，加载原完整策略对应policy切片；全信息与屏蔽答案两种focal完整策略均到native terminal，
full query值必须匹配原已存Q。比较best nonquery仍引用相同query入口的原Q，不重定义主S或更改oracle。
两例已由用户点名为结构重点，不扩展选择/训练，不做不可见调查或重新求均衡。
max_nodes200000、构树30s、单worker/数值线程1；原生终局forest求值无额外硬限，input/source/CLI写实际snapshot。
此前版本与已关闭结果均保留；冻结时本v4未运行，结果另留EVIDENCE。
