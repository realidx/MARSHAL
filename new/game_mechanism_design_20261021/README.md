# 2026-10-21 游戏机制校准

完整规则、原型边界和下一步：[设计提案](../../examples/strategic_slices/GAME_MECHANISM_PROPOSAL_20261021.md)。

`verify_contract_witness.py` 用标准库Fraction验证一个新的两人非对称议价原型：3合同/3联合类型、2次提案机会、最多签一个合同；调查一个偏好消耗一次机会，拒绝免费。响应按自身终局收益优先、平局帮助对方。

- 调查X：5/3；最佳不调查完整offer试探：4/3；严格优势1/3。
- 同一调查行动屏蔽答案：2/3；纯答案价值1。
- 包含混合策略的不调查上界，通过32个宽松策略顶点的双线性最大化验证。
- 构造并逐项验证首次响应、拒绝后Bayes belief、最后报价和最终响应的策略。
- 改成二值单槽查询，或允许第三次报价后，严格调查优势为0。

运行：`python new/game_mechanism_design_20261021/verify_contract_witness.py`。

`witness_results.json` 为机器结果。原型不等同现有BENAC-P：它使用完整项目合同菜单、稀缺资源、成功签约结束，以及A拥有两次提案权的角色设计。不是现有轮换提案/三人游戏的均衡证书，也不是唯一均衡证明。生产代码/题库/prompt/Oracle未变，无模型调用或GPU任务。
