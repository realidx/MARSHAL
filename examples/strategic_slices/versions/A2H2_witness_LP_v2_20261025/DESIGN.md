# A2H2 own S见证独立LP复核 v2

2026-10-24批准的A2H2校准，执行延续至10-25。沿用研究v1主标签，不改solver/game/Q/S。
相对原review helper：仅对有正S见证的游戏构树，跳过无见证游戏的无效构树；仍覆盖全部正S父游戏。
每父游戏/通道挑最大S，以及proposal阶段最大S，按S、reference mass、较早node/cell确定并去重。
每个见证分别独立LP计算完整信息与遗漏信息森林的聚合own最优值，核对保存DP标签加权值。
另在遗漏own最优解集合内求该真实context的自身值上下界；社会response约束放宽，给保守S区间。
同时记录森林平均信息收益，不能把某个真实context的平局依赖与整组合并后的信息收益混为一谈。
单worker；构树沿用实际request的资源配置；LP无额外硬限。实际所有参数/source/input记录到run snapshot。
没有增加新的主S、reward或训练方法；只核查被选见证，不证明所有标签、跨均衡或模型D。
冻结时尚未执行；运行结果另写EVIDENCE，不改此快照。
