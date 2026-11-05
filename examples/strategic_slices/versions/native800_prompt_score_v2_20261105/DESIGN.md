# Native800题面与回应评分v2：单复数文案修订

2026-11-05。v1完整800 CPU请求/评分检查通过；预览发现1 OFFER actions、1 times单复数。
v2只改为1 OFFER action和INVESTIGATE at most once，增加独立request/Decision版本身份；scoring-v1逐字不改。
其余system/user/tools/公开私有信息/规则/连续负regret/1e-9/GRPO/条件world与v1一致，完整合同见[父v1](../native800_prompt_score_v1_20261105/DESIGN.md)。
原v1源码/实际CPUrun/请求预览保留，不覆盖。新源码AST通过后注册，重导出完整请求并跑同一800核验。
旧active v8不改，D/训练未执行；此项是实际prompt变化，不能把v1请求或旧D称作v2测量。
