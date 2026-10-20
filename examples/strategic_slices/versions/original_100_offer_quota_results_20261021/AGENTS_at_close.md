# Strategic slices实验版本记录

用户明确要求：沿用9月可读题面与具名工具；任何prompt、工具、题目筛选、Oracle、奖励、
advantage、训练参数、采样、评测、保存/恢复或运行环境的改变都必须留痕，不得当作内部细节省略。

- 修改前读 `examples/strategic_slices/PIPELINE_CONFIG_COMPARISON_20261017.md` 和
  `examples/strategic_slices/versions/index.json`，确定当前基线。
- 已关闭的版本快照不可覆盖。语义或参数默认值变化时增加版本，保留原快照；在版本索引中列出
  与父版本逐项差异、动机、用户授权范围、完整参数及验证结果，区分已运行与仅实现。
- prompt变更必须导出实际request函数生成的完整system/user/tools样例并链接，不能只摘一句提示。
- 保存题库/selection/D测量的版本与hash；更换prompt后不能把历史D误称为新prompt的测量。
- 代码/source与注册快照必须匹配；每次实际运行必须写入完整 `pipeline_snapshot.json`，包括CLI覆盖、
  resolved config、模型/数据/source身份、采样/reward合同。配置缺失项标“未记录”，不能用今日默认值补猜。
- 旧记录与旧checkpoint保留原身份，不静默混用新接口；CPU验证不能写成GPU、收敛或效果验证。
- 2026-10-18题面审阅：保留当前玩家真实调查答案，去掉额外来源/谁由调查知道什么的提示；
  公开调查行为保留在历史。计分定义集中在GAME RULES，公开事实与当前私有事实分开。
  简化偏好support必须先证明与题库概率等价，不得删掉真实联合限制；见
  `examples/strategic_slices/PROMPT_REVIEW_20261018.md`。
- 2026-10-21：全体玩家只在ACCEPT/REJECT自身预期最终效用平局时，优先最大化其他玩家
  预期最终效用总和；不扩展到proposal。已发现v8参考策略有此规则、focal评分却只看own Q的
  缺口，不能只补prompt就声称已对齐。状态/累计调查答案必须每次完整披露；V9目前仅审阅草案。
  继续工作先读 `examples/strategic_slices/PROMPT_PROTOCOL_REVIEW_20261021.md`。
- 2026-10-21当前工作顺序：先解决游戏机制，再继续prompt。稀缺资源/有限合同/期限/联合类型的
  校准提案见 `examples/strategic_slices/GAME_MECHANISM_PROPOSAL_20261021.md`。
  新的两人非对称原型已做精确分数验证，但不等同现有轮换提案或三人游戏的认证；未激活新规则。
- 2026-10-21后续用户澄清：机制研究固定原100父游戏，允许有些题不需调查，不以额外toy代替整批。
  仅研究提出OFFER立即扣个人报价额度，调查和独立偏好保持原样，dependent preference暂缓。
  整批现为70局等价、29局新认证、1局未认证；未认证局仍保留，不能按0信号或旧profile当新标签。
  见 `examples/strategic_slices/OFFER_QUOTA_ORIGINAL_POOL_RESULTS_20261021.md`。当前未激活新训练版本。
