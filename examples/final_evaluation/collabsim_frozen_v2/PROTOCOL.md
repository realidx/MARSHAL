# CollabSim 冻结协议 v2（2026-09-24）

用途：同一 checkpoint 控制全部席位的小规模外部交互诊断。不是原论文全面复现，不单独支撑广泛社会推理提升结论。不改变原生提示、规则、材料、角色、工具解析和终止机制。

| 项目 | ShapeFactory Lite | Hidden Profile |
|---|---|---|
| 每模型运行数 | 4 局 | 同一案例重跑 3 次 |
| 玩家 | 3，A/B/C | 3，A/B/C |
| 实例 | circle/square/triangle 三种专长，两个方向的订单循环 × private/dashboard | 原生单一候选人案例与私有材料 |
| 任务量 | 每人一个非专长订单；生产上限3 | 初始投票→讨论→最终投票 |
| 采样温度、环境 seed | 0、42 | 0.2、42 |
| 时间／步数 | 原生900秒、10秒触发、30秒生产延迟 | 原生max_steps=30、discussion_duration_sec=300 |
| probe | 原生每5次动作 | 原生per_action |
| 通信 | 原生direct；仅dashboard可见性不同 | 原生broadcast |

完整有效配置在 templates.json；模型地址、模型名和输出目录使用占位符。冻结来源 commit 08ed0ed1cefb2edf1ea389b20ba8355815a7c8d0；manifest 对原生来源记录、适配器、汇总器、配置模板和本协议记录 SHA256，启动前逐一核验。

## 执行约束

- 各模型使用同一服务设置：上下文98304（96K），同一输出预算4096、同一推理后端版本、精度与 batch-invariant 设置，逐项归档实际启动命令。**wrapper 只记录此要求，不能远程认证服务参数或权重。** 未核实的运行不得伪称已满足。
- 单局依次执行，不并行多个游戏；原生局内并发不改。真实时钟保留，900秒或300秒不是进程墙钟时长上限，不据此宣称调用数或机会相等。记录真实耗时、行动数、token、probe、超时及服务错误；推理速度仍可能影响结果。
- 不裁剪/总结历史，不改提示，不补动作，不把长轨迹的上下文超限算作模型决策失败。统一修复基础设施后，保留旧尝试、为比较模型使用相同新协议。
- 同一模型全部7局都报告，不能只保留成功运行。原生停止或外层COMPLETE不代表任务成功。完整最终投票缺失也不能算作正确或错误投票的普通样本。
- 三次 Hidden Profile 重跑测的是同一材料的运行变异，不是三个独立场景；ShapeFactory 四局只有两种订单循环及两种可见性条件，不是四种独立结构。不得将它们混成“7题总准确率”。

## 冻结指标

ShapeFactory：逐条件报告订单完成数/总订单数、三方均完成局数、人均最终余额（起始200）。辅报生产、成交、剩余库存、行动调用与错误。private/dashboard 配对比较；不得把余额上升或交易增加单独视为更强合作。

Hidden Profile：逐次报告初始和最终每席位投票、最终正确票数/实际投票数、全队是否一致且正确、最终投票阶段是否发生。原生正确答案固定Candidate C。信息分享和使用只作轨迹分析，不新增心理推理评分器。

服务/进程失败独立报告；应用内部处理的HTTP错误、probe失败也要查，不能只看退出码。

## 命令

校验冻结文件（不调用模型）：

```bash
python -m examples.final_evaluation.collabsim_frozen_v2 --verify
```

用原生依赖环境生成7局配置并做schema校验（不调用模型）：

```bash
python -m examples.final_evaluation.collabsim_frozen_v2 \
 --model YOUR_SERVED_MODEL --base-url http://127.0.0.1:8000/v1 \
 --checkpoint-id Q0_SHA256 --output runs/collabsim/q0-preflight
```

实际运行另用新目录加 `--run`。本入口不启动或提交模型服务。冻结后任何规模/计时/提示/重复次数更改都应另建协议版本，不覆盖本版本的结果。

## 三人订单分配

专长固定为 A=circle、B=square、C=triangle。forward 订单为 A=square、B=triangle、C=circle；reverse 为 A=triangle、B=circle、C=square。使用原生按 shape_options 索引生成订单的逻辑，每人仍一个订单，均为非专长。允许非专长自给，不强迫交易。三人完整完成每局3项，四局共12项。三人循环并非保证实际交易发生。v1 两人配置及文件保持原样。
