# 独立MS错误出现在哪一阶段（2026-11-03）

沿 `原始可见信息 → MS → ACTION → 原生验证结果` 核对。这里判断的是**同一事实或规则的错误第一次出现在哪里**，不把“MS先写错、ACTION也错”自动当作MS导致错误的因果证明。本次不调用模型、不更改实现。

结论：已有直接证据表明，错误既可以先出现在MS，也可以在ACTION新增。当前核对到的硬约束失败更支持“MS先产生错误判断，ACTION沿用或进一步强化”；不支持“MS普遍正确，主要是动作阶段读坏了正确MS”的概括。ACTION也能纠正MS，不能把整个模式理解成它只看MS、不看原始上下文。

## 一组完整定义的小样本

枚举两个v13独立MS运行全部24题的**第一场会议、首次DECISION提交，因为schedule目标已占用而被拒绝**的节点，合计5个。排除后续会议、验证重试、目标重复和错误item等其他拒绝类型。这是一个窄的客观失败子集，不是全量MS语义标注，也不代表所有协调失败。

| 模型/题/玩家 | 原始事实 | MS | ACTION | 错误起点 |
|---|---|---|---|---|
| Qwen dense_varied_s1 A0 | slot5有errand #5，cost7 | 明确说slot5对自己空闲、避开所有errand | 照此直接schedule5 | MS已有本人事实错误 |
| outcome blocked_varied_s3 A2 | slot7为Blocked #21 | 明确说自己在7没有承诺、没有冲突 | 声称日历显示FREE，schedule7 | MS先错，ACTION又把判断说成日历事实 |
| outcome dense_uniform_s1 A0 | slot5有errand #5 | 说自己在5没有安排 | 直接schedule5、不移动errand | MS先错，ACTION沿用 |
| outcome dense_varied_s1 A0 | slot5有errand #5，cost7 | 说该位置对所有人都无需移动、无冲突 | 再明确添加“我的日历上空闲”，schedule5 | MS先有错误总判断；ACTION新增明确的本人事实错误 |
| outcome loose_varied_s1 A1 | slot2有errand #10，cost8 | 明确说slot2对自己空闲 | 照此schedule2 | MS先错，ACTION沿用 |

5个节点在MS中均已有错误判断；其中4个已经明确读错本人日历，第5个是错误的“所有人无需移动”的总判断。它们不能被解释为五次“正确MS被ACTION读坏”。但不能据此推算整个实验有多少下降由MS造成。

数据源和完整wire请求：[MS_ERROR_ORIGIN_CASES.json](MS_ERROR_ORIGIN_CASES.json)。每例保留实际MS与ACTION请求，已断言ACTION保留完整MS输入前缀并追加实际MS回复；原日历并没有被MS替换或从ACTION中删除。

## ACTION确实会新增错误：把他人的errand当成自己的

Qwen `blocked_varied_s3`，第一场Agent0，逻辑call4。

原始收到的Agent1消息：slot4与**Agent1自己的**errand冲突，移动要cost6；建议改slot7，因为7空闲。Agent0自己的日历显示slot4为FREE；自己的item3在slot2。

MS保留了消息来源这一点：它说 **Agent1** 的errand在slot4。但MS也已经错误地把“移动会有成本、所以建议换位置”推断成Agent1需要/愿意移动，这不是一份全正确的MS。

ACTION新增了更具体的归属和执行错误：

- thinking说要reschedule Agent1的errand；
- 实际actions却对**自己的日历**提交 `reschedule(item3,4→7)`；
- 同时在7 schedule会议，连目标也发生重叠。

环境首先拒绝：slot4为空，那里没有item3。这证明ACTION阶段有新增的实体绑定/动作构造错误，不能全部归为照抄MS。它没有证明“加入MS使这种错误增加”：当前没有同一状态、移除MS后的ACTION反事实。

## ACTION还会丢失MS保留的不确定性

Qwen `dense_varied_s1`，第一场Agent2，call4。MS承认Agent1没有回复，并明确使用“assume they are available”；ACTION则写成“agreed upon during cheap-talk”。

这里MS已经有无依据乐观推断，但仍区分了未回复与确认；ACTION进一步把假设升级为共识。因此这是**错误放大**，不是完全正确MS被读错，也不是错误全部在第一阶段完成。

只根据“MS与ACTION都出现同一slot”判断一致性，会漏掉这种确定性级别的变化。

## 事实不一定错，错误也可能是MS先制定了不适当的行动规则

Qwen `blocked_uniform_s2`，第二场Agent2，call9。MS正确指出没有收到Agent3确认，随后已经写出“必须等明确同意才作决定”。ACTION沿用这一策略，输出空动作；环境拒绝“Expected exactly 1 schedule action”。

完整DECISION要求在ACTION里：必须提交本会议的schedule。MS阶段自行形成的“没有确认就不能提交”与此不兼容。这个例子不是单纯的日历记错，也不能因为“未确认”的事实正确，就把整个MS标成正确、把错误算到ACTION头上。

当前独立MS模式先让模型在观察/规则视图下生成自身意图，再在下一阶段恢复完整行动要求；这种时序允许意图先形成，再与正式合同发生冲突。这是实现条件的一部分，不是分阶段推理本身必然如此。

## ACTION也能纠正MS：原始上下文仍然可用

Qwen `dense_uniform_s1`，第一场Agent0，call4。

MS说slot5没有自己的errand。ACTION却写出“my calendar shows slot5 occupied by Errand #5”，随后正确提交 `reschedule(item5,5→2)` 加 `schedule(meeting1,5)`，首批未被拒绝。

这个例子排除了“原始日历已经不在ACTION里，所以它只能相信MS”的解释。ACTION可以重新核查，只是没有稳定地这样做。这里纠正的是本人日历事实，不代表MS中关于共识、紧急性的其他叙述都被纠正。

## 如何解释“context导致更多误读”

日志能够确认：

1. MS可以在ACTION之前就已经把原始事实、承诺或行动约束判断错。
2. ACTION有时继承错误，有时增加错误，有时纠正错误。最近的assistant MS与“依据前面的assessment行动”要求，可能使错误判断成为较强的行动依据；这是与轨迹相符的解释，尚无消融证明其强度。
3. 不是超过context窗口造成的机械截断。前次全量审计中独立MS的最大prompt加请求输出上限约12.2k/11.5k，低于32768；ACTION前缀与MS输入逐字相同。不能据此排除较近MS文字对注意和判断的影响。
4. 不能把事实准确、共识准确、行动策略正确和动作构造正确混成一个“MS对/错”。同一段MS可以正确标记消息来源，却错误推断他人意图；ACTION随后再绑定错item。

如果要定量区分两个因果来源，下一步应冻结相同环境节点与历史，对比原MS、经核验的纠正MS和不提供MS的ACTION；分别评分事实、承诺、策略、合法动作。纠正MS后仍新增错误，才是更干净的动作阶段证据；纠正MS使动作恢复，则支持MS错误传播。这个诊断需要新模型调用，本次没有执行，也未修改prompt。

## 范围与证据

此次人工核对为上面的5个完整枚举失败节点与4个机制例子，共9个节点。机制例子是明确选取的证据，不用于计算整体比例；没有进行全量盲标、没有声称某一类占全部失败的百分比。原始文件哈希和完整上下文保存在cases JSON，可复现提取脚本为[audit_ms_error_origin.py](audit_ms_error_origin.py)，单独执行身份记录见[MS_ERROR_ORIGIN_EVIDENCE.json](MS_ERROR_ORIGIN_EVIDENCE.json)。原有关闭的总体报告和EVIDENCE保持不变。
