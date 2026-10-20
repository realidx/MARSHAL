# OFFER额度机制研究

用户当前决定：保留调查原机制，只研究提出OFFER立即消耗个人报价额度；逻辑依赖偏好暂缓。
完整[研究记录](../../examples/strategic_slices/GAME_OFFER_QUOTA_RESEARCH_20261021.md)。

- `research.py`：独立规则、完整向量best response/答案消融、所有边的额度审核。
- `test_research.py`：4项语义回归检查。
- `run.py`：raw、源码/配置身份、全终局求解、独立认证、reference保存。
- `analyze.py`：全部既定样例初始信息集配对，不按正结果筛选。
- `run_v1`：早期审核字段错误中止，原source留档、无可用标签。
- `run_v2`：7个父游戏×2条件，14/14完整终局认证，7个一轮非约束控制通过。

结果：部分报价Q下降，但6个紧凑独立偏好控制的调查价值仍为0；已有原生样例首步调查优势仍为0.25。
因此报价预算有效施压，尚未证明它改善调查信号。没有因此加入dependent preference。

CPU结果不是GPU或训练效果。生产active仍v8，prompt/Oracle/题库/GRPO未接入新规则。
`pipeline_snapshot.json`保持启动身份，完成状态另见`COMPLETE.json`；已存在输出不可覆盖。
