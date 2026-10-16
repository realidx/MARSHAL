# 2026-10-16：多轮采样、可比组与分支预算

响应用户的“每个后续决策点再采样8个回答、同题面组内比较”。本次只查论文、
公开实现和本仓库，**未修改训练算法，未启动训练**。研究仍是slices/SP效率，
下述方法不是已采纳组件，不将其组合成新的GRPO。

## 最终训练口径（同日用户已逐项确认，作为实施依据）

以下合并已采纳决定，优先于本页下方的讨论历史。**协议已于同日实施为v5，
完成本地验收，GPU未启动。**见[实施与启动](TERMINAL_TRAINING.md)及
[准备检查](../../new/terminal_node_grpo_readiness_20261016/README.md)。
std采用样本标准差（correction=1）+1e-8；组内range≤1e-7视为Oracle数值等值。

| 项目 | 已确定的规则 |
| --- | --- |
| 本步候选 | 同一决策上下文独立采8个回答，输入、评分条件和剩余k相同。 |
| 合法task reward | `r_i=Q(h,a_i)-max_a Q(h,a)`，即负regret，保留native效用尺度。 |
| 非法/截断task reward | `r_fail=min_a Q(h,a)-max_a Q(h,a)`，即该节点最差合法动作的负regret。 |
| 协议惩罚 | 非法/截断调用另有独立`protocol_advantage=-0.2`，不先混入task reward归一化。 |
| task advantage | 仅在本节点8个reward内做group mean/std；采样值等同的组task优势为0。 |
| token credit | 本节点优势仅用于本回答生成tokens；不把后续优势回传给prefix。 |
| loss权重 | 节点组等权、组内8回答等权、回答内token平均；取消入口链额外1/T权重。 |
| 推进 | 从8个原始样本均匀抽1个执行，保留重复样本，不看oracle分数；失败则终止。 |
| 链深度 | 最多k=1/2/3个focal决策；reference推进，剩余k递减，提前结束不补齐。 |
| update目标 | 20个实际节点组×8个回答；不要求20个有效梯度组，不默认过滤/补采。 |
| 批次边界 | 达目标后不再接新入口，已开始的入口链全部采完再更新；允许略超，记录实际组数。 |
| 采样与更新 | 整个collection固定behavior权重；全批梯度累积后一次optimizer更新，同批只训练一遍。 |
| 评测 | 保留严格0/1最优动作率、regret、终局utility及既有validation整段成功指标。 |

失败reward是明确的评分约定，不是伪造失败轨迹的native terminal utility。
Q已包含全部合法动作，失败评分使用其最差值，不使用本组采样到的最差值。
平坦Q节点中合法/失败task值可能相同，协议失败仍由独立−0.2项处理。
抽中失败样本不重抽，不追加LLM/oracle修复；未选中的失败回答也保留训练和成本记录。

若实际采到M个节点组，task主项的归约为`mean_g(mean_i(mean_token(loss_git)))`；
protocol和KL沿用同样的节点/回答权重，各自单独记账。所有实际生成回答，包括
零task优势与失败回答，都计入生成token预算；验证、测试和oracle计算另行计账。
模型、数据身份、初态terminal reference、1024输出/16K context、6M训练token
预算和低频验证/保存等已有设置沿用；原slices/SP比较保留，不另开credit方法对照。

采样器/评分/loss/恢复合同已实施。剩余是实际模型信号、GPU性能/恢复和评测覆盖验收；
下方“尚未实现”均记录实施前的讨论状态。

## 最新决定：采用连续oracle价值奖励（用户已确认，尚未接入代码）

用户追问“选出的题有价值差异，却被二值化抹掉，究竟是否该用binary”，并在
文献口径澄清后确认采用：**在已定同节点GRPO中，以连续oracle行动价值或等价的负regret作为
合法动作task reward；0/1最优动作标签保留作严格评测。**此前优先保留binary、
通过过滤补采缓解信号不足的建议，未对准已经确认的价值信息丢失，需要修正。
这是已采纳的奖励定义，不增加新的GRPO估计器、方法对照或分支选择策略。

**状态：连续reward已确定，旧binary训练实现尚未替换；每节点8个、组内GRPO、
随机推进1条和最多k节点的采样决定不变。**binary标签用于评测，不再是新训练
的唯一task reward；下方主方案已同步更新。动态过滤/补采仍未采纳。

### 直接证据与适用范围

重新读取Git跟踪的`signal_history/questions.json`：持续全错且k=1的题中，7题
有18个组实际采到不同root Q-gap，binary reward却全0。题`328b5d8e`在第1次
曝光的8个有效回答中，regret=2的4个、约2/3的3个、0.5的1个，prompt一致，
唯一最优动作未被采到。负regret reward会保留这些错误动作之间的价值排序。
对应[逐题记录](../../new/terminal_training_review_20261008/signal_history/README.md)。

不能把它扩写成“所有选题每次都有advantage”：首版100题中88题有已观察的
gap/completion contrast，另12题为完整控制组保留。题目存在Q差异、某轮确实
采到不同Q的动作、训练reward保留其差异，是三个不同条件。连续reward只
修复最后一项；若8个都采到同一错误动作或等价值动作，仍可能全无task优势。

### 不需要改变GRPO公式

固定可见上下文h和剩余k，对合法动作使用`r_i=Q_oracle(h,a_i)`，或
`r_i=-(max_a Q_oracle(h,a)-Q_oracle(h,a_i))`；后一种仅减去同节点常数，
组内中心化后相同。然后仍用`A_i=(r_i-mean(r))/(std(r)+epsilon)`。
[原始GRPO §4.1.2](https://arxiv.org/html/2402.03300v2#S4.SS1.SSS2)接受标量
reward，并不要求二值；不必将oracle信息先阈值化再找新算法补信号。

数值处理仅应依照oracle误差/tolerance，避免把求解噪声放大成动作偏好；不
随意新增可接受regret阈值。训练group仍须是相同输入与评分条件，不能只用
连续值就恢复旧跨轨迹local-LOO。

### 对最优动作的要求没有取消，但不承诺有限训练必然收敛

固定h、精确Q、无正则且可自由选择策略时，`sum_a pi(a|h)Q(h,a)<=max_a Q(h,a)`；
最大值仍由只支持oracle最优动作的策略达到。这是标量价值优化，不是把
softmax(Q)当作含次优概率的蒸馏目标。

它不证明当前有限样本LLM训练在clipping/KL/参数共享下必然收敛。每组标准差
归一化会改变不同组的权重，故前一轮`E[raw Q]-beta KL`的小gap例子也不能
直接作为当前标准化GRPO损失的定量预测。严格最优动作率、regret和终局utility
仍需同时验收；连续reward只观察到次优动作时，也不能凭空发现未采到的最优动作。

合法reward保留native utility尺度；记录Q和regret，固定用`r=-regret`计算同组
GRPO，不默认引入min-max/softmax或binary与连续奖励混合。相同采样价值的组
task advantage=0，oracle数值等值按既有精度口径处理，不强行制造梯度。
**失败评分已确认：**使用该节点最差合法动作的负regret，保留独立protocol
penalty=-0.2；不把旧binary失败task=0直接搬过来。确切合并规则见顶部最终口径。

## 用户已确定的主方案（同日后续决定，优先于下方候选历史）

用户接受第二种路线，只采用一种credit方案，不额外开展整轨迹credit方法对照。
原项目slices/SP效率比较仍保留，本次决定不取消SP实验臂。

- 每个实际决策上下文独立采8个本步回答，以连续oracle Q/负regret评分；同组
  使用相同输入、剩余k和评分条件，以group mean/std计算标准GRPO优势。
  严格0/1最优动作率保留作评测，平局最优容差沿用1e-7；不采用旧跨轨迹local-LOO。
- 所有8个回答参与该节点训练；从8个原始样本中均匀抽1个执行，保留重复样本，
  不按oracle分数择优，也不把不同合法动作去重后再均匀选。
- 执行既定reference回应，到下一focal决策再开8个回答的新组，最多k=1/2/3
  个focal决策节点。提前终止不补深度；每次入口曝光最多8k个模型回答。
- 后续组优势不回传给已有prefix；每个回答只用所属节点组的优势。
  collection期间固定behavior权重，采完才更新。
- 模型、100题入口池及train/validation/test身份、oracle/profile、1024输出/
  16K context和6M生成token预算先沿用。仍从原base开始新合同，不将旧训练
  checkpoint当成新协议的静默resume。
- 现有reference执行、隐藏world与可见posterior区分不变。已有独立protocol
  penalty=-0.2保留，它是额外项；失败task评分为该节点最差合法动作的负regret。
  抽到失败样本则停止该推进路径，不重抽或oracle修复。
- 按连续价值记录组内contrast；binary全错组若Q不同仍可有task信号。采样
  价值相同的组task advantage=0。不默认过滤、补采或动态增加宽度；protocol/
  KL是否有贡献单独记录，全部回答照实计入采样成本。

**状态：设计已定，代码尚未实现。**下面的候选/文献描述作为讨论历史；
不能把当前旧v4命令当作已实现上述分组方式。

### 本轮补充确认的训练口径

节点组/回答等权、回答内token平均；update目标20个实际节点组，已开始的链
完成后更新；失败按最差合法值评分并保留独立协议惩罚。三项已全部接受，
完整公式及边界以顶部最终口径为准，不再作为待选方案。

### 待验收的问题，不是重新选择算法

- **选集信号。**现有100题仍冻结；新节点组实际连续Q/regret差异、重复动作和
  binary正确率尚未测量。连续reward恢复已采到的价值差异，不能解决只采到同一
  动作/同价值的情况。如仍需重筛，仅使用train证据，另行记录选集版本。
- **评测覆盖。**沿用现有validation整段成功率选择best，继续报告终局utility/
  regret；独立强信息held-out不足仍是旧缺口，不能用训练信息题证明信息泛化。
- **工程。**需新sampler、advantage、日志/合同版本和resume身份；检查相同prompt/
  scoring、组内归一化、随机推进、失败/提前终止、采样权重冻结及token成本。
  原有低频验证/保存调度继续沿用，不把旧GPU smoke当作新协议验收。

## 同日补充：更新batch与二值奖励零方差组

用户进一步要求依据论文确定每次更新样本量，并处理全对/全错组。本节保留连续
reward决定之前的讨论；binary零方差条件不能直接套用到新reward。本节为文献
核对与建议，**未采纳动态过滤，未改变顶部已经确定的采样主方案或启动训练**。

### 论文中的batch不能直接按数字比较

| 原始来源 | 明确给出的设置 | 单位限制 |
| --- | --- | --- |
| [DeepSeekMath §4.2](https://arxiv.org/html/2402.03300v2#S4.SS2) | 每题64个输出，training batch size=1024，每轮采样后一次更新。 | 该段没有明确1024是prompt还是已展开response，不据此反算入口数。 |
| [GiGPO v2 附录D.1](https://arxiv.org/html/2505.10978v2#A4.SS1) | ALFWorld/WebShop均16组×8=128个environment rollout；mini-batch分别256/64。 | rollout含多轮，后续展开的step样本数不同；不能称128个回答就是一次optimizer step。 |
| [Search-R1 v5 附录B.2](https://arxiv.org/html/2503.09516v5#A2.SS2) | GRPO每题5个输出，沿用所列total batch512、mini256、micro64。 | 论文数字涉及rollout/mini/micro三个层级，精确更新次数需对应具体实现。 |
| [DAPO v1 §4.1](https://arxiv.org/html/2503.14476v1#S4.SS1) | 512个prompt×16=8192个回答；mini-batch512，明确一轮rollout有16次梯度更新。 | rollout iteration不是optimizer step；不能把这些设置直接套进我们的一采一更。 |

对本项目，应分别报告：每节点宽度G、每optimizer step的节点组数M、每轮采样
被重复训练的次数、实际生成tokens，以及非零task advantage组数M_eff。microbatch
只用于显存/累积梯度；并发32不定义optimizer batch。相邻节点来自同一入口，
也不能简单当作完全独立任务。

**20×8仍是工程候选，无论文证明20优于16或32。**本轮不因为读到16×8就再次
改数；保留20的候选尺度、一次采样只做一次optimizer更新、不重复epochs。
关键要明确20是全部节点组还是有效task节点组。旧local-LOO数据重分批的统计
不能替代新节点GRPO的实际有效组比例。

### 全对与全错：同一代数现象、不同学习问题

对固定节点的二值标签，8个全0或全1的group-mean/std优势均为0；加epsilon、
换LOO或把0/1改成−1/+1不会制造组内差异。协议penalty和KL需单独统计。

若本节点每次独立正确概率为p，同组8个样本独立，则至少有一对正误样本的概率为
`q(p)=1-p^8-(1-p)^8`。这是本项目的二项分布计算，不是对LLM收敛的定理。

| p | 8个回答形成正误混合组的概率 |
| --- | ---: |
| 0.001 | 0.80% |
| 0.01 | 7.73% |
| 0.1 | 56.95% |
| 0.5 | 99.22% |
| 0.99 | 7.73% |

扩大optimizer batch可让一次更新含更多有信号组，却不改变某个固定节点的p。
全对一次不代表永久掌握；旧日志有整组由错变对再变错的题，不能永久删除。

### 已有方法：DAPO动态采样解决有效batch，不保证攻克困难题

[DAPO §3.2](https://arxiv.org/html/2503.14476v1#S3.SS2)过滤accuracy=0或1的
题组，继续采其他题组填满有效训练batch。它保留二值奖励，不需要发明新的
advantage；但会改变训练采样/权重及生成成本，不能称与未过滤协议完全等价。

公开[veRL DAPO recipe](https://github.com/verl-project/verl-recipe/blob/main/dapo/README.md)
分别配置gen_batch_size与train_batch_size，另有max_num_gen_batches上限；
达到上限仍不足时报告错误，不会无限补采。此处只核对机制，不采用作者示例的
1536/512/10等数字，也不顺带引入Clip-Higher、token reduction等其他组件。

若采用这项数据采样策略，它能改善“采20组但只少数组有task信号”的问题；
对正确动作概率接近0的题，换其他题填batch并没有让该题学会正确动作。
对于本项目，还必须保留以下约束：

- 全对/全错节点仍按已定规则随机推进；不能仅从混合组推进，否则暗改状态分布。
- 所有丢弃/补采回答计入生成token和时间，不能只算最终有效160个回答。
- 已有失败penalty及reference KL不因task advantage=0就自动消失；若引入
  task组过滤，必须另写这两项作用范围及归一化，不能按“零loss组”一并删除。
- 不无限重采同一全错节点；困难题保留账本与定期复查。全对题也不能永久出池。

### 本项目先解决什么

1. 在同一初始模型、新native输入/工具渲染和正式生成配置下重测train信号。
   筛选资格应包含同题binary正误对比，不能仅以连续Q-gap差异代替。只看一次
   8采样也不能断言p严格为0或1。现有数据身份先保留，重筛必须另记版本。
2. 核对D与训练采样错位。旧14道持续全错题全部k=1；其中8题D曾有root正误
   混合，含6道固定错误response题。单改多轮分组不会自动修复它们；同权重下
   的prompt/token/template/输出上限等需一致性检查。
3. 若新采样的有效组比例仍低，优先考虑有上述直接动机的、带上限的动态采样，
   将20作为有效节点组目标。**这是待定建议，不替换顶部“不默认补采”的现行决定。**
4. 对持续全错且采样链路无误的题，二值GRPO无法利用“两个错误动作Q不同”
   这条被丢弃的信息。要进一步解决，需改善探索/可学习性准备，或明确修改奖励/
   额外监督；本轮不偷偷改连续reward、加teacher答案或声称过滤已经解决。

全错困难题与全对饱和题的处理不能只写“过滤”。预算补采、持续困难题覆盖及
协议/KL作用范围，需要在启用动态采样前一起固定；尚未新增GPU实验或新算法臂。

## 当前实现及需要纠正的解释

源码：`terminal_training.py:77,100,112,159–166`及`terminal_d.py:110,135`。

- 一题创建8个StepRollout，共享入口、world、focal player；模型/reference随机
  流独立。首步输入相同，执行动作及reference回应后，后续输入可以分叉。
- k=3为最多3个focal决策，不是3个RR；最多24次模型调用，提前结束会更少。
  每次仅生成当前call，执行后再渲染下一输入，没有每个后续状态追加8次采样。
- 全组结束后，当前代码计算`Rbar_i=mean_t(r_it)`、
  `b_-i=mean_j!=i(Rbar_j)`、`A_it=r_it-b_-i`；没有按后续同输入重新分组。

若8条路径都得`[0,1,1]`，每条当前task advantage都是`[-2/3,1/3,1/3]`。
非零task advantage不代表观测到了同节点正误对比；699/2200 active组不能
直接解释为699个有可比行动的局部组，也不能直接断言这些梯度全部无效。

**当前估计器不是同上下文的relative action advantage，也不是完整return的
策略梯度估计器；但跨状态baseline并非一概无效。**在普通、未裁剪且无额外
动作相关权重的score-function梯度中，与本次动作独立的baseline满足
`E_a[b(h)*grad log pi(a|h)]=b(h)*grad sum_a pi(a|h)=0`。
其他同起点完整轨迹的return因此可提供Monte Carlo baseline；它不必准确等于
每个后续节点的V_pi(h)。参见[RLOO §2.2–2.3](https://arxiv.org/html/2402.14740v1)。
这个恒等式不保证当前含局部奖励、裁剪、KL和可变长度权重的整套实现无偏。

当前binary task baseline在[0,1]内，正确动作的task advantage不会为负，错误
动作不会为正；不能说它直接颠倒了0/1标签。真正缺失的是明确的局部比较对象、
目标/credit依据与项目验证。不能仅凭本次阅读认定它已被证实导致训练退化。

## 文献与公开代码核对

### 1. 整轨迹分组：比较完整任务完成结果

[Search-R1 v5 §3.1、§3.4](https://arxiv.org/html/2503.09516v5)：从同一问题采
多个包含搜索交互的完整输出，以最终EM评分，mask检索内容。后续状态不必
相同，因为比较单位是完整任务；这不能为“局部reward减轨迹平均正确率”背书。

### 2. GiGPO：复用已有轨迹中的重复状态，不追加分支

[GiGPO v2 §4.1–4.3](https://arxiv.org/html/2505.10978v2)：同起点采N条轨迹，
把相同anchor state的行动重新分组，比较return-to-go，再组合episode与step
优势。局部组大小不固定；singleton没有局部对比。并非每状态另采N条。

核对[core_gigpo.py](https://github.com/langfengQ/verl-agent/blob/master/gigpo/core_gigpo.py)：
`compute_step_discounted_returns`累积后续reward，`build_step_group`在episode
组内按anchor_obs建组，`step_norm_reward`组内归一化。它使用环境reward后缀，
并非本项目即时oracle正确标签；当前代码另有近似匹配选项，不能因此把不同
私有信息/belief的游戏节点安全合并。

### 3. HGPO：相同观测也可能带着不同历史

[HGPO §4.1–4.2](https://arxiv.org/html/2602.22817)直接讨论historical context
inconsistency：当前状态相同但memory不同，模型条件分布仍不同。严格匹配组
可能很小；作者按不同历史长度建层级组并加权，不额外rollout。文中“Oracle
group”指历史条件严格匹配的组，不是博弈最优oracle。

核对[core_hgpo.py](https://github.com/langfengQ/verl-agent/blob/master/recipe/hgpo/core_hgpo.py)：
按观测历史后缀建cluster，跳过singleton，计算各cluster优势后聚合。它不是
固定宽度8的同完整输入分支组，不应仅因问题相近就默认采用其层级加权。

### 4. Tree-GRPO：共享前缀、有限次数追加后缀

[Tree-GRPO §3.1–3.2、附录D](https://arxiv.org/html/2509.21240)：先生成M条
初始化路径，再选择非终止节点续写；M/N/L控制树数、扩展节点数与轮数，
不遍历完整8叉树。共享前缀降低重复生成成本。

**但树形采样不等于每父节点的兄弟组独立GRPO。**作者组合树内与树间的完整
轨迹reward优势，不是本项目设想的同节点即时oracle标签归一化。

代码证据：

- [generation_ts.py](https://github.com/AMAP-ML/Tree-GRPO/blob/main/search_r1/llm_agent/generation_ts.py)：
  树数、扩展数、扩展轮数和样本选择数可配置，从已有节点恢复前缀续写。
- [ray_trainer_ts.py](https://github.com/AMAP-ML/Tree-GRPO/blob/main/verl/trainer/ppo/ray_trainer_ts.py)：
  `adv_estimator='tree'`分别按uid与tree_uid计算GRPO优势再相加。
- [作者示例](https://github.com/AMAP-ML/Tree-GRPO/blob/main/train_multihopqa_tree_search.sh)：
  M=2/N=2/L=1，另有K=3样本选择参数；不是我们的默认推荐。

### 5. ARPO：只在部分交互节点分叉，设总额度

[Agentic Reinforced Policy Optimization §3.1–3.2、附录E](https://arxiv.org/html/2507.19849)：
总额度M中先生成N条初始路径，保留M−N额度给工具反馈后的续写分支，依据熵
变化触发，到额度即停；还区分共享与分叉token的优势处理。因此接近“后续
节点也有多个同前缀候选”，但不扩展所有节点，也不是简单逐节点binary GRPO。

作者[仓库示例](https://github.com/RUC-NLPIR/ARPO)含总16/初始8/分叉宽度2的
配置；这里只确认有限预算机制，不采纳其熵调度。特指2507.19849，避免与其他
同名ARPO混淆。

以上代码为2026-10-16查阅的公开分支，未固定commit、未运行上游程序；没有
声称完整复现其论文。若未来采用，须固定版本及实际公式。

## 对8条再各采8条的回答

同前缀追加采样有文献依据，但可限制节点/分支额度：

| 方式 | 分组与成本 |
| --- | --- |
| 完整8叉树、深3 | 最多8+64+512=584个模型调用，原8条链最多24个。 |
| 已有轨迹重分组 | 不新增生成；组大小不保证8，稀少重复上下文可能使后续大多singleton。 |
| 选部分决策上下文追加采样 | 每处采8个，只推进部分分支；总节点额度及状态覆盖分布单独记录。 |

本项目额外拥有oracle Q/正确性评分：固定h和剩余k时，每个动作可直接评分，
**不必为估计该动作reward而生成LLM后缀**。oracle求解仍需计算，其值依赖
已声明的reference/控制窗口。这不取消实际调查后继续决策的多轮采集要求。

最接近用户原意的最小候选是：选中的每个决策上下文作为一题，采8个本步回答，
binary oracle标签只在这8个内计算标准GRPO优势；执行选定分支产生后续题。
这只是任务/采样协议候选，不是已实现合同，也不声称复现上述任一完整算法。
不默认增加熵选点、层级加权或树内外优势混合。

## 本项目的分组与成本约束

- 同实际模型输入：private信息、已获证据、公共历史、剩余k、合法动作和实际
  携带memory。仅同player的第2步或同公共棋面不足以定义可比局部组。
- 同评分条件：focal身份、reference、oracle窗口、posterior定义及tolerance。
  同输入若因未展示条件产生矛盾标签，须修复条件，而非只换group id。
- 隐藏world只用于执行，不能泄漏或把期望Q改成已知world评分；环境快照与
  oracle可见信息评分是两种不同条件。
- 局部组优势作用于该组新生成回答；共享prefix不能无说明地重复计入梯度。
  采样期固定behavior权重，保存token/logprob对应。
- 新增/失败回答、prefix计算与缓存收益、oracle计算均计账，不能只匹配最终
  轨迹条数。样本数相同不自动代表生成token或wall time相同。

本节最初提出的宽度、节点额度和推进规则已由顶部决定固定；跨入口/跨曝光的
样本复用不默认引入。仍需实测可比组reward contrast和成本，不能预先宣称效果。

## 预算讨论历史：每节点8个回答，每层推进1条（现已采纳，尚未实现）

用户进一步询问“有限分支预算是否指从最高分回答继续”。这里区分数量额度与
推进规则，提出了以下候选。用户后续已接受主方案，最新状态与未定项以顶部为准。

| 参数 | 首版候选 |
| --- | --- |
| 每个决策上下文的回答组宽度G | 8，独立采样 |
| 每次入口曝光最多扩展的上下文数 | k，仍为1/2/3个focal决策点 |
| 每组继续执行的分支数 | 1 |
| 推进分支选择 | 从这8个回答中均匀随机选1个，不依据oracle分数 |
| 每次曝光的模型调用上限 | 8k；k=3时24次 |
| 更新时机 | 整个collection采样期间固定behavior权重，完成后更新 |

具体执行：h0采8个本步回答，用同一h0/剩余k的oracle标签各自评分并在组内算
GRPO优势；抽1个回答执行，按既定reference得到下一focal决策h1；h1重新采8个，
只在h1组内算优势；最多到k个上下文。所有8个都进入本节点训练，不仅选中的
那个；未推进的7个不额外生成LLM后缀。提前终局则停止，不另抽入口补满深度。
抽到非法/截断回答按已声明失败规则终止，不能暗中重抽合法回答来改变分布。
每个call只用所属上下文组的局部优势，不把后续组优势复制给共享prefix。

若8个候选都是当前策略的独立样本，均匀抽取其中1个，所选回答的边际分布
仍为当前策略：`P(selected=a)=sum_i P(a_i=a)/8=pi(a|h)`。这是本项目的数学
说明，不是声称上述论文采用完全相同的协议；有限样本训练的收敛仍未验证。

**最高分推进也能定义，但会变成oracle筛选过的状态访问分布。**例如正确动作
采样率p=.2，G=8，若二值奖励下总是从最高分候选中选，推进正确动作的概率
会由20%升至`1-(1-.2)^8=83.22%`（正确候选存在时必选正确）。每个局部组仍
可使用GRPO；但访问后续状态时已使用teacher筛选，不能称为普通当前策略
rollout，也不能认为已验证学会了独立完成前面的决策。局部全对/全错组仍无
task差异，选最高分不会自动解决这一点。

最高分规则可作为明确的teacher-guided curriculum候选，其好处是更容易走到
可学习后续，代价是减少模型实际错误路径的覆盖。首版建议先用均匀随机推进，
以固定数量额度、保持模型自然访问分布；不默认再增加混合比例、熵选点等参数。

该候选与原先8条完整链有相同的8k调用数上限，但只推进一条实际路径，状态
覆盖及组结构不同；它并非在原8条链上叠加额外8叉树，也未证明实际token/时间
成本相同。总训练仍须按实际生成tokens及oracle/prefill成本计账。
