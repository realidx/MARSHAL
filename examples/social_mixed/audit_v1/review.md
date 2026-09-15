# 混训数据结构审计与诊断清单（2026-09-15）

本次只读当前冻结数据，未运行模型、未改训练题/标签/划分，也未重新求解标签。源文件 SHA256 已对照 manifest 核验。可复现脚本：`examples/social_mixed/audit_data.py`（Python 3.8+）。详细统计、源 hash 和选择 ID 见 `audit.json`。

## 结论

混合训练有可检验的技能连接，但当前 B/P 不能被描述为完整覆盖 self-play。优先补收益计算与接受/拒绝对照，检查教学题曝光，暂不增加一轮混合比例搜索。是否带来收益提升仍由正式 mixed vs selfplay 对照回答；本次审计不证明因果收益或梯度方向一致。

| 数据 | train | validation | 结构/能力 |
|---|---:|---:|---|
| B formation | 63 | 12 | 初次偏好推断 |
| B update | 52 | 12 | 更新已有 belief |
| B maintain | 37 | 9 | 无信息证据下保留 belief |
| P complete | 32 | 8 | 完整信息决策 |
| P uncertain | 32 | 8 | 不确定信息下决策 |
| P result_use | 32 | 8 | 使用调查结果 |
| P information | 32 | 8 | 是否调查；train 正反各16，validation各4 |
| Self-play | 60 | 12 | 真正零历史开局；train双人40/三人20 |

## 标签分布和实际曝光

- B train 152题：44题的可能集合是全集（28.9%），其中38题还要求 favored=undetermined（25.0%）。并非多数 gold 都是全集；模型容易在这部分获得正奖励与标签比例是不同问题。
- 当前 B 槽位 formation/update/maintain/update。在各池均匀抽样下，固定输出全集且 undetermined 的预期正确率约20.66%。这是静态答案捷径基线，不是模型实测。
- B来源：original119、bridge30、简化L0仅3；采样器下 bridge 约19.23%，L0约2.60%。因此入口教学题实际曝光很低。不能仅按合并后的题目数判断课程有效。
- B自愿证据长度：133题只有1条，19题有2条；没有3条及以上。长度只是结构代理，不证明19题都考察累计推断。
- P train：109题只接受OFFER类型；16题只接受INVESTIGATE；2题接受OFFER/PASS；1题接受INVESTIGATE/OFFER/PASS。没有ACCEPT或REJECT标签。调查正反平衡不等于行动类型覆盖充分。
- train/validation 的B/P目标全部为binary。本轮没有把合法全集答案、纯报价题或低奖励题删除。

## Self-play覆盖

- 训练轮数2/3/4/5为24/18/12/6；validation为5/4/2/1。
- train binary-only/linear-only/mixed各20；validation各4。
- train有20个开局声明偏好域[0,1]，40个声明[-1,0,1]；34个真实世界包含负偏好。validation对应4/8，6个有负偏好。
- 偏好域是公开规则的一部分，不能把B/P的三值先验机械套到所有self-play开局。这里是分布差异，不是已证实的规则bug。
- 每个split有6个精确索引下的目标/动作几何；60个开局不是60种结构。train/validation没有相同的该几何hash，但此hash不消除玩家/动作重命名同构，不能据此声称独立结构泛化。

## 重复与划分检查边界

B/P跨train/validation的id、semantic_id、family、精确input以及精确索引几何交集均为空。Self-play的id、精确raw+world、精确索引几何交集为空。

这些检查排除相应定义下的精确重复，不排除同构或共享策略模板。B/P train最大family包含96/280题，也不是96次相同题：需按语义与对照角色解释。最终论文不应仅用无ID重叠宣称结构泛化。

## 能力连接与补题优先级

| Self-play真实错误/需求 | 当前B/P支持 | 建议 |
|---|---|---|
| ALL_OF与linear收益、负收益 | binary有覆盖；linear无覆盖 | P0：构造合法短局binary/linear对照，部分完成时改变正确动作；核验所有合法动作收益及teacher平局 |
| 收到报价后接受/拒绝 | B含行为解释；P没有这两类动作标签 | P0：相同偏好比较接受/拒绝分支，再改变偏好或目标结构翻转动作；不能仅改变人名 |
| 无关证据不该排除 | B maintain37；L0仅1个train | P0：保留维持控制，和真正排除题成组；增加独立结构而非复制L0 |
| 多次行为累积更新 | 最多2条自愿证据 | P1：补3步证据链，含信息证据和无关证据，核验每步支持集与posterior |
| 调查是否值得及结果使用 | information/result_use均存在 | P1：显式建立调查价值与后续决策配对；不能只要求调查正反数平衡 |
| 三人、伙伴选择、联合belief | self-play含三人；本轮尚未完成联合belief语义审计 | P1：独立检查边缘belief能否误代联合分布；不据本次计数宣称已覆盖 |

建议首批新增规模：12–18道train候选，围绕前两个P0缺口组成4–6个对照组；先核验再决定实际入库。具体题面与标签尚未构建，此处是补题规格，不是已验证的新数据。不得从validation失败题改名派生训练题。原validation保持不变；新增评估题另建独立结构的开发诊断集，test不参与。

## 固定诊断抽样

`bp_selected.jsonl`：24题（train B8/P8，validation B4/P4），每题8次，共192次回答。包含3个train简化L0，各P池、train调查正反例；按未覆盖的家族、来源、标签和证据特征作确定性覆盖选择。不是按成功率挑题，也不是严格成对对照；后者需要新构造。

`selfplay_selected.jsonl`：12个真实开局（train8，validation4），各4条独立完整轨迹，共48局。覆盖train全部6种精确几何及2–5轮，保留真实world，不调用solver筛选。为覆盖而抽，不要求小样本重现总体2:1人数比例。两个清单均为内部含标签/隐藏world的数据，只能通过现有renderer生成模型可见请求，不能原样发送模型。

模型沿用正式4B Instruct、原生工具、1024输出，temperature=1，top_p=1，与主实验一致。旧temperature不同的结果作为历史证据单列，不合并作同设置统计。此次只导出清单，尚未启动HTTP测试或新增远程启动入口。

## 采样后必须交付的判断

1. B/P每类的二元奖励混合组、全零组、全集捷径与过度排除；将“正确 vs 完整错误”和“正确 vs 截断”分开。
2. 所有正例与选定反例对照审阅理由；特别检查报价前后时序。错误理由不能修改二元奖励，但需限制能力结论。
3. Self-play按开局×玩家位置分别计算utility方差、协议方差、完成率与有效outcome组；失败utility不补零。
4. 按正式分组和loss权重离线重算advantage，报告有效单位及token成本。此诊断清单刻意超采L0等类型，不能直接把它的平均分或有效组比例当成正式采样器期望；另给按池的估计并标注小样本不确定性。
5. 根据已确认结构缺口补train题；不删除所有全零/复杂self-play，不为了base表现反复改规则，不进行按validation逐题优化。

本轮不宣称难度已经平滑、混合比例最优或混训已有效。
