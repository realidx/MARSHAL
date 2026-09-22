# 阅读顺序与证据索引

1. PRO_BRIEF.md：最新统一说明，包含用户约束、纠正、配置对照和需要回答的问题。
2. configs/old_bp/：旧两段原始 resolved_config、experiment、environment；configs/current/：本次所有已解出的运行配置，包含失败尝试，不能把失败配置当有效主链。
3. new/osc_training_analysis_20260922/：本轮分析脚本与JSON，先读O_RELEVANCE.md。README中O39→99“反驳没有可保持积累”的论断过强，应以本brief的端点限制为准。
4. new/old_bp_retention_audit_20260922/：旧BP逐题获得/丢失/恢复。
5. new/calbench_bp99_mechanism_audit_20260921/、new/training_debug_20260921/：诊断、历史配置差异和轨迹证据。旧文状态以本brief为准。
6. examples/social_mixed/paired_bank_v2/：实际数据、训练计划、P认证和当前README；training/social_mixed/为当前实现，不是完整旧版实现。
7. PRIOR_PRO_RESPONSE.md：之前PRO建议原文。当前约束见brief，不要重复不可行建议。

## 完整原始数据（full_evidence.zip）

- new/osc_training_evidence_20260922/：此次所有原始training分片和CalBench归档、原始校验清单。
- new/training_chain_evidence_20260921/：旧BP、新BP、新SP现有训练证据，原始配置/metrics/验证/抽样calls/source patches/data manifests。
- runs/calbench_soc/{old,new}-bp99-*：新旧BP99冻结24局逐局、events、transport和运行标识。
- runs/diagnostic/ 中选择的新旧BP99 v5/v6/v6s：全部本地原始诊断结果。
- new/bp99_checkpoint_results_20260921/：export配置、来源、权重哈希，无权重本体。

review.zip提供直接阅读材料、配置、派生JSON和当前实现；full_evidence.zip另含原始日志与数据。两包保留仓库相对路径。主brief位于new/pro_final_training_review_20260922/。全包FILES.sha256不含其自身及zip；本轮归档内部完整成员索引见archive_index.json。不存在的日志/权重不作补造。
