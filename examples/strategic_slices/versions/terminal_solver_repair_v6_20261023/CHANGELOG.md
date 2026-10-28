# Solver研究v6

父版本：remote terminal solver staged15 v5；有限窗口沿用game design v2，不覆盖其已关闭快照。
用户授权：解决当前求解阻塞；此前已同意检查1 RR加下一次自身proposal的统一窗口。

- 增加保留完整收益平局自由度的逆向缩减与收益向量复用；原历史/信息集不合并。
- 候选BR保留仍最优的当前分布；局部修复按实际continuation求值。
- 终局重新求全部100，并独立重载审核；99通过、25仍缺失。
- 对全部100统一应用已批准窗口，补充固定玩家顺序候选；100通过窗口认证。
- 提供保存source/参数/hash的CPU命令及统一reference索引；保留候选来源与失败记录。
- 保存可选sequence-form、MILP、Gambit、支持求解等独立研究及容量诊断，未把它们当作整批成功方法。

未改正式父池/原生规则/先验、生产prompt/tools、GRPO/reward/advantage、训练参数、模型或active v8。
没有完成新Q/S/D、slice selection或训练；没有用有限窗口结果改写终局缺失标签。

完整结果、数值范围、代码及真实run链接见[本轮说明](../../SOLVER_REPAIR_20261023.md)。
