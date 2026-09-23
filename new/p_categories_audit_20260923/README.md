
## P分类覆盖修正（2026-09-23）

D采样状态升级为`d-coverage-fixed12-pcategories-v2`，旧v1状态不允许直接恢复。P每步仍4道、每题8回答；先选累计曝光最少的非空类别，再在类别内按原低曝光/久未访问规则取题。同一步P不重复。类别为当前合法操作（response、investigation_choice、ordinary_proposal）×直接终局/多步×binary/linear×原有relevant/control，共12个合格训练类别。这是类别均衡，不是按题库数量比例采样，小类别会更频繁复习；不是已证实最优比例。

逐题核验497个train/validation P：合法动作数与三态评分数一致、后继转换数一致、状态标签合法；终局依据所有即时后继是否terminal。原始pool/history_planning仅留作来源，不当作当前无历史P能力标签。private_results仅作来源记录，不能称P在读取调查历史。relevant沿用原标记，不声称每题都迫使模型改变动作，也不声称完成了跨belief接受集合认证。直接终局合格P均为control，没有制造不存在的类别。多步P的固定continuation限制不变。

逐题结果与汇总：new/p_categories_audit_20260923/tasks.jsonl、summary.json。任务、标签、资格、提示与奖励未改。12项测试覆盖实际题库的关系完整性、P资格、类别累计均衡、固定批次、恢复连续性与版本拒绝；未启动训练。

复核命令：`PYTHONPATH=. python training/social_mixed/p_task_categories.py`。这是元数据/状态一致性分类核验，不是重新求解teacher或新增P充分性证明。
