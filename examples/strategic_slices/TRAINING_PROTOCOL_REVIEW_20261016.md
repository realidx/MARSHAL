# 2026-10-16：训练 protocol 的文献核对与建议

本记录响应“先依据论文确定protocol，避免继续凭经验调整batch/曝光”的讨论。
只使用论文原文和官方文档；区分论文结论、代码事实和本项目的建议。
**下方是实施前的研究/协议历史；同日v5已接入已定方案，本轮未运行GPU。**
当前实现、命令和验收见[训练文档](TERMINAL_TRAINING.md)。
原job 915731和候选v4代码保留原身份；20×8并未因本次阅读而获得效果验证。

**最新已采纳决定：**同节点8采样、连续oracle Q/负regret reward、标准组内GRPO、
均匀随机推进1条、最多k个focal节点；严格0/1最优率保留评测，不增加其他credit
方法对照。见[专项协议顶部](MULTITURN_GROUPING_REVIEW_20261016.md)。本页较早的
binary/outcome-only/动态采样建议为讨论历史，不覆盖新决定；已实施为v5。

**后续讨论更新：用户支持中间oracle监督，并要求先调查多轮同上下文分组。**
见[多轮分组专项记录](MULTITURN_GROUPING_REVIEW_20261016.md)。本页此前关于
outcome GRPO作为主线的建议未采纳；保留为讨论历史，不能据此开始outcome-only
训练。整轨迹baseline对完整return可有依据，当前local reward减轨迹均值则
不能解释为同节点动作的相对优势；两者不能混为一谈。

## 研究边界与本页建议的状态（同日澄清）

**本文研究slices相对完整SP的训练效率，不提出新的GRPO方法。**训练算法应选定
一个有明确出处的成熟实现，并在两个实验臂保持一致；slice入口、窗口/数据分布
及其对应的成本差异才是研究变量。任务所必需的多轮接口与reward定义需要说明，
不能借此默认拼接Dr. GRPO、DAPO、GiGPO或oracle辅助学习组件。

以下文献解释已知现象，不等于已经采纳其算法。下方原“建议先固定的基线”一节
改列为历史候选，**不作为实施清单**；其中算法变更只有在本项目有充分、具体
动机时才重新讨论。此前把“不标准GRPO”作为笼统表述不准确：原GRPO本身同时
有outcome和process版本，开源实现也有不同配置；必须按指定版本逐项对照。

### 当前实现相对原论文具体有什么不同

以[DeepSeekMath §4.1.2–4.1.3](https://arxiv.org/html/2402.03300v2#S4.SS1.SSS2)
为对照。outcome版本对同一prompt的G个完整输出分别给标量reward R_i，
令`A_i=(R_i-mean(R))/std(R)`，该输出的token共享A_i。
process版本则归一化逐步奖励，再将后续步骤奖励之和分配给token。
“有逐步reward”本身不意味着偏离原GRPO；区别在实际advantage和回传定义。

当前实现是：

```text
每个受控decision都有binary reward r_it
Rbar_i = mean_t(r_it)
b_-i = mean_j!=i(Rbar_j)
A_it = r_it - b_-i
```

| 组件 | 当前实现与原论文的关系 |
| --- | --- |
| 策略比值、PPO clipping、reference KL | 仍使用GRPO/PPO类训练的共同骨架；不能因此推导全部估计器相同。 |
| LOO baseline，不除组内std | 不同于原GRPO的group-mean/std；单步时LOO与减组均值只差G/(G−1)，但不除std还会改变不同题组的相对权重。 |
| 本步reward减其他轨迹平均逐步reward | 是当前的局部反馈适配，不是原outcome版本的完整输出reward，也不是原process版本的后续奖励累计。 |
| 每个response按实际token长度平均 | 原GRPO本来就有这种归一化，不能因为Dr. GRPO提出移除它，就称本项“不标准”。 |
| trajectory内部再按实际decision数平均 | 是多轮适配引入的额外权重，需要与任务目标一起说明。 |

例如8条轨迹都为`[0,1]`：当前每条得到`[-.5,+.5]`；若采用整段成功/失败的
outcome reward，8条全失败、组内advantage全0。这展示了反馈目标/credit不同，
不证明其中一个在我们的任务上更优，也不是引入新算法的充分理由。

同reward组的advantage为0在原GRPO中同样存在。因此699/2,200个active组的现象，
不能笼统归因于“实现不标准”；需要单独核对reward对比、采样分布与探索。

## 同日追查：为什么改过，能否直接使用原始GRPO？

**可以使用原始outcome GRPO的整轨迹扩展。目前没有项目证据表明必须采用现有
local-LOO适配，也没有先运行匹配的原始GRPO基线、证明其失败的实验。**这里的
“原始”指保留group mean/std advantage、token-level ratio/clipping、reference KL
及每个输出的生成token平均；交互环境需要的rollout与mask接口仍需明确定义。
这是一项基线选择建议，尚未修改训练实现或启动新训练。

### 仓库能支持的历史动机

- `TERMINAL_TRAINING_DRAFT.md`最初提议：用native terminal utility作每条轨迹
  的标量reward，按原有mean/std归一化，各受控call共享trajectory advantage。
  因此从一开始就不存在“多轮游戏不能做整轨迹GRPO”的技术障碍。
- `TERMINAL_TRAINING.md`记录转向局部binary反馈的依据：保存的D中整段成功为
  179/800，strong acquisition为2/96；逐步正确分别为567/1251与86/203。
  这些计数单位不同，只能说明存在部分正确步骤，不能把比例当作同一指标比较，
  也不能据此推导GRPO的组内reward方差或预测哪种训练协议更有效。
- 同页与`binary_advantages`说明LOO排除自身轨迹，以其他replicas提供baseline；
  local reward可保留后来失败轨迹的有效prefix，也不为未访问的步骤补奖励。
  这些解释了首版取舍，但没有证明这种局部credit优于原始outcome/process GRPO。
- 仓库声明不除组内std，却没有为这一选择提供本任务的匹配消融或必要性证据。
  其他论文有关方差/难度缩放的发现只能提供候选解释，不能补写成当时已验证的理由。

**“希望增加信号”是逐步反馈的动机，不是同时改变reward、baseline、normalization
和credit assignment的充分理由。**同样，回到原始GRPO也不会自动解决全错或重复
错误动作；若同组标量reward相同，task advantage仍为0。

### 更接近本项目的论文如何选择训练方法

以下核对论文原文的明确协议，不宣称逐行复现了各自发布代码。版本和节号用于
避免把“论文称GRPO”误读为所有实现细节都与DeepSeekMath完全相同。

| 论文及定位 | 实际训练选择 | 对本项目的可用证据 |
| --- | --- | --- |
| [Search-R1 v5，§3.1、§3.4、§5.1、附录B/F](https://arxiv.org/html/2503.09516v5) | 同时支持PPO与GRPO，多次搜索交互构成一条完整输出；只用最终答案EM奖励，mask检索内容。默认PPO，作者在其设置中观察到PPO更稳定。 | 多轮获取信息并不必然需要局部advantage；可以保留成熟优化器，把适配集中在交互与外部token mask。不是游戏，也不证明我们的任务一定学得动。 |
| [ReTool v2，§2.3.1–2.3.2](https://arxiv.org/html/2504.11536v2) | 沿用PPO；代码执行与反馈交错，只按最终答案给+1/−1；不加代码可执行性奖励，mask解释器输出，先做工具使用cold start。 | 工具中间反馈可作为observation，不必都变成训练reward；cold start与RL阶段有明确分工。本文并非建议我们增加SFT或迁移PPO。 |
| [SocialRL，§4.2、§5.1](https://arxiv.org/html/2608.13787) | 与本项目同为Qwen3-4B-Instruct-2507；六类协商/协调环境均用终局标量收益，无中间reward shaping。specialist训练沿用PPO加独立critic，部分环境先SFT。 | 在接近的私有偏好与协商环境中，成熟RL算法加终局连续收益是实际采用的路线；它不是精确oracle最优动作监督，不能把效用提高解读为已收敛至最优动作。 |
| [SPIRAL v3，§3、§4.1、附录E.2](https://arxiv.org/html/2506.24119v3) | 多轮双人零和self-play，使用终局回报和REINFORCE；专门提出按game/role维护EMA baseline的RAE，并给出消融。 | 最接近完整SP，但不是“原版GRPO成功案例”。其改动针对角色不对称与方差，有明确方法贡献和实验责任；不能把RAE默认为本项目必需组件。 |
| [Social-R1，§4.2、§5.1](https://arxiv.org/html/2603.09249) | 声明沿用GRPO/verl；贡献集中在社会推理过程与组合reward，包括答案、过程质量、格式和长度。 | 可以沿用既有优化器来研究监督设计；但它主要是社会情境选择题，不是多轮博弈环境，也未在正文逐项证明与原始GRPO所有细节一致。 |
| [GIFT，§4.1.2、附录B.1/B.3](https://arxiv.org/html/2601.05633) | 用RAGEN的StarPO*，trajectory-level scalar reward/advantage；具体还包含DAPO与高方差轨迹过滤，另提出CST任务更新调度。 | 不能仅凭“backbone是GRPO”称为原版GRPO；该工作本身也研究训练调度，不能将整套改法作为本项目默认设置。 |
| [GiGPO v2，§4、§5.2](https://arxiv.org/html/2505.10978v2) | 把整轨迹GRPO与RLOO作为多轮agent基线；自己提出episode与anchor-state两层credit并消融。 | 直接确认整轨迹GRPO是可实施的多轮基线。局部credit是该文研究对象，不因它的结果较好就必须成为我们的主线。 |

以上论文没有形成“多轮任务必须使用某种GRPO改版”的统一协议。较接近且不研究
advantage创新的路线，通常先固定成熟PPO/GRPO，把任务接口、reward和训练阶段
写清楚。SPIRAL、GiGPO等对估计器的改动则属于其明确的方法贡献。

### 前一轮候选判断（未采纳）：整轨迹outcome基线

以下保留前一轮建议，不是当前实施计划。曾建议主比较采用**原始outcome GRPO的整轨迹扩展**，不默认保留当前local-LOO，
也不拼接其他论文组件。一次调查及其后续决策可以属于同一条trajectory：

1. 同一初始任务/入口与指定focal role采样G条交互轨迹；一组采样期间固定权重。
2. 每条trajectory得到一个预先定义的标量`R_i`；
   `A_i=(R_i-mean(R))/(std(R)+epsilon)`，同轨迹受控player的生成tokens共享A_i。
3. 使用原始token ratio/clipping/KL和每条trajectory生成token的平均；环境观测、
   frozen oracle及其他player的输出不作为这个focal loss的生成targets。
   不再额外把每个call等权平均后声称它就是原始整输出token平均。
4. SP按同初态、同player角色分别比较各自回报，不把不同玩家的收益混成一组；
   各player都可更新同一个模型。轨迹内部状态分叉是正常的，不要求后续节点相同。
5. 格式失败、超长、终止与reference continuation的处理仍须写入固定任务合同；
   “使用原版GRPO”不会自动提供这些环境规则。

**但优化算法不能替我们决定R_i。**native terminal utility、整段oracle-correct
binary，以及逐步oracle正确率的聚合，是不同学习目标；不能为了恢复公式就随手
相加局部标签，或把原本逐步目标未经说明地改成整段全对。连续/二值reward与
是否使用GRPO是两条独立选择轴，GRPO不要求reward必须是0/1。

如果SP用终局utility，而slices用逐步oracle正确率，即使优化器相同，所得实验也
比较了反馈差异。若论文只声称切片带来效率收益，就需匹配反馈条件或加入相应
对照；若保留这种差异，结论必须描述为整套训练方案的比较。原先已授权的
SP/slice对手与窗口口径并未在本次文献核对中被改动。

## 先明确筛选与训练错位的内容

原生utility本身不被限定为0到1。`select_terminal_d_v4.py:choose`使用连续的
D/C、归一化decision-gap spread，以及同prompt的Q差异、完成差异和覆盖约束。
训练`StepRollout.accept`则只给“选到最优动作”1，否则0。
所以Q=.7与.8、最优Q=1的两个动作，在筛选中可有差异，在训练中却都是0。

旧运行的逐题证据见[采样历史](../../new/terminal_training_review_20261008/signal_history/README.md)：
14道持续全错题中，8题在D里曾采到最优/次优混合；12道信息题中7题始终未选对首步。
这证明了采样/目标之间存在错位，不证明连续reward一定更好，也未定位D/native差异的全部原因。

## 直接相关的论文，实际做了什么

| 原始来源与定位 | 论文采用的协议或主要发现 | 对本项目的含义与限制 |
| --- | --- | --- |
| [DeepSeekMath，2024，§4.1.2–4.1.3](https://arxiv.org/html/2402.03300v2#S4.SS1.SSS2) | outcome版每个完整输出一个reward；process版使用后续步骤的归一化奖励之和给token分配advantage。 | 本项目只给当前call局部奖励的做法不等同于该process协议；该文的步骤是生成的推理步骤，并非互动游戏turn，不能原样等同。 |
| [Back to Basics / RLOO，2024，§2.3](https://arxiv.org/html/2402.14740v1) | 用其他完整输出的reward均值作baseline，优化完整输出的序列级目标。 | LOO这一组件有依据，但“本步reward减其他轨迹平均逐步reward”不是文中的序列级估计器。RLHF结果不构成游戏收敛保证。 |
| [Dr. GRPO，2025，§3.1–3.2](https://arxiv.org/html/2503.20783v2#S3) | 保留正确1/错误0；移除逐响应长度除法及组内reward标准差缩放，采用固定归一化常数。 | 改进效率不以换连续reward为前提。我们已无组内std缩放，但仍有实际response长度除法；不能将其论文结果直接外推为本次失稳的因果解释。 |
| [DAPO，2025，§2.4、§3.1–3.4](https://arxiv.org/html/2503.14476v1#S3) | 正确+1、错误−1；动态过滤全对/全错组；采用Clip-Higher、token级归一化及单独的超长处理。 | 同reward组无梯度是已知问题；动态采样提高有效更新密度，并不能凭空生成从未采到的正确动作，也没有承诺覆盖所有困难题。 |
| [GiGPO，2025，§4、附录D](https://arxiv.org/html/2505.10978v2#S4) | episode级return与同一anchor state内的return-to-go分别比较，再组合优势；ALFWorld/WebShop采用16组×8轨迹。 | 多轮步骤不能任意混合比较。隐藏信息游戏还需定义可见历史、belief和剩余窗口，不能只按公共节点合并；改为oracle局部标签属于适配，不是原版GiGPO。 |
| [RAGEN，2025，§4.1–4.3](https://arxiv.org/html/2504.20073v1#S4) | 研究多轮RL中的退化，比较高方差实例筛选、探索与不同rollout配置。 | 有效样本、轨迹多样性与稳定性应先于单一更新数。作者结果来自其模型/环境，不能把过滤比例或rollout数直接当成我们的最优值。 |
| [Entropy Mechanism，2025，§2–4](https://arxiv.org/html/2505.22617v1#S2) | 研究早期熵下降和探索受限，并测试有针对性的熵控制方法。 | 应检查动作重复和真实熵；我们记录的chosen-token概率或8个样本的频率不等于完整策略熵。论文的经验曲线不是本游戏的普适定律。 |
| [AggreVaTeD，2017，§3–4](https://arxiv.org/pdf/1703.01030) | 在learner访问的状态上利用expert cost-to-go；离散动作情形可对全部动作的oracle成本计算更新。 | 我们拥有全部合法动作Q，存在直接利用oracle的文献路线，无需只等抽到正确动作。但它是oracle辅助学习，不能默默混入纯RL对照，且LLM非凸训练不继承其所有理论条件。 |

原论文使用的组大小就包括DeepSeekMath的64、DAPO的16、GiGPO的8，说明不存在
可直接照抄的通用采样次数。需要借鉴的是完整目标、估计器、消融和成本口径。
官方[TRL GRPO文档](https://huggingface.co/docs/trl/main/en/grpo_trainer#loss-types)
也分别实现了GRPO、DAPO和Dr. GRPO的loss reduction；这里用它核对定义，不提议迁移框架。
动态文档查阅日期为2026-10-16，实施时应固定代码版本，不依赖将来变化的默认值。

## 连续信号会不会让策略无法学到最优动作？

### 固定状态、无正则、理想优化：连续不是障碍

以下是本项目的数学分析，假设Q准确，固定同一个可见状态h、剩余k和参考剖面，
有限合法动作，策略可自由表示所有动作分布，且没有KL/entropy项：

```text
J_Q(pi | h) = sum_a pi(a|h) Q(h,a) <= max_a Q(h,a)
```

令最优集合为A*，最小正的次优gap为delta>0，则
`P_pi(a not in A*) <= (max Q - J_Q) / delta`。
因此，如果确实把该目标优化到最大值，概率质量会集中到最优集合。
这说明“连续reward必然只学到差不多的动作”不成立；它**没有证明**神经网络、
有限样本PPO或当前自定义surrogate一定把J_Q优化到最大值。

还应区分：把Q当标量reward、回归Q再argmax、以及模仿softmax(Q/tau)分布。
后者在有限tau下会有意保留次优动作概率；不能把这三种“连续监督”混为一种协议。

### 当前实践中的担心有依据：小gap与固定KL会竞争

标准单步KL正则目标`E_pi[r] - beta KL(pi || pi_ref)`的理想最优解为
`pi*(a|h) proportional to pi_ref(a|h) exp(r(h,a)/beta)`，推导见
[DPO原文§4、式4](https://arxiv.org/html/2305.18290v1#S4)。这里引用其正则化解，
不表示推荐DPO算法，也不将该解直接当作当前token级KL实现的预测。

例如Q/reward为`[1,.99,0]`、beta=.01：均匀reference下最优动作概率约73.1%；
若reference原本极偏好.99的动作，正则化后的greedy动作也可能仍然次优。
同一例子的binary reward `[1,0,0]` 有更大的最优/次优margin。
所以**应分析reward gap相对KL/entropy强度，而不能仅凭连续/离散二分判断收敛**。
binary加正则同样没有精确最优动作概率为1的普遍保证。

### 多步情形不能仅凭单步排序套保证

当前loss为每轨迹等权，内部再按实际决策数和每call实际token长度平均；advantage是
`r_it - mean_j!=i(mean_t r_jt)`，局部反馈不回传后续reward。
它在代码中也明确声明为local surrogate，而非terminal-utility policy gradient。

例如8条轨迹全为`[首步错0，后一步对1]`，当前得到`[-.5,+.5]`；
这不是“8条轨迹中发现了更好的调查动作”。我们信息题的大量active组正需要这种区分。

也不能随手改为累加局部正确奖励：若最优动作立即结束游戏，得1次正确奖励；
一个稍差动作允许后续两次局部正确决策，则binary之和可能变成0+1+1，
反而超过立即最优动作的1。窗口长度可变时，奖励聚合方式本身就是目标定义。

对原始任务增加dense shaping而希望保持最优策略，经典依据是
[Ng、Harada、Russell，1999](https://ai.stanford.edu/~ang/papers/shaping-icml99.pdf)
的potential-based shaping：`F=gamma Phi(h')-Phi(h)`。有限episode还需处理
terminal potential等边界。任意归一化Q奖励并不因此自动成为合法的potential shaping。
而且同起点、terminal potential=0时，整段shaping和只差一个常数；若原终局reward
全相同，纯episode级LOO仍可全为0。它也不能被当成破解全错组的万能方法。

## 代码中应先审计的协议差别

| 当前事实 | 为什么不能只调整batch |
| --- | --- |
| selection接受Q-gap差异，训练只接受binary差异 | 筛选出的诊断题不一定有当前reward的组内对比；两类资格必须分开标记。 |
| 同一初态组的后续轨迹会分叉，baseline却跨不同decision状态混合 | 局部正确率与trajectory回报被混合，造成“后一步对”制造active的现象。 |
| `objective.py`在task_denominator=0时除以实际response长度 | 对应Dr. GRPO讨论的一个归一化问题；其影响需单独消融。 |
| 同时按实际trajectory_length给decision加权 | 这是额外的可变权重，需与所宣称的目标一起定义。 |
| `workers.py`不计算真实entropy，返回zeros_like占位 | 不能将该字段当成测得的低熵；需要真实指标或明确标记未测。 |
| 固定reference KL=.01，1024输出硬截止 | reward margin、KL、长度/失败处理需共同审计，不能以“0/1正确”推导整体协议必然收敛。 |

源码：[reward/advantage](../../training/strategic_slices/terminal_training.py)、
[loss](../../training/social_mixed/objective.py)、[worker](../../training/social_mixed/workers.py)。

## 历史候选建议（未采纳，不作为实施计划）

以下保留初次文献讨论的候选，**不是已采纳的训练方案，也不是接下来默认要做
的算法改造**。是否需要其中任何改动，受本页顶部研究边界与充分动机要求约束。

1. **主线先保留binary oracle-optimal action标签。**连续Q用于报告regret和诊断，
   不因筛选错位立即替换主reward。所有最优平局动作接受；oracle、belief、epsilon
   和失败定义先固定。若主目标改为终局utility，另立一个真正优化terminal return
   的协议，不能仍用当前local loss却换个名称。
2. **先在k=1上建立文献定义清楚的基线。**一次完整model response作为输出，
   同一decision context内按binary reward计算序列级RLOO；不做组内std除法，
   对task loss使用固定token归一化常数（Dr. GRPO思路）。先验证能否改善那些
   固定错误response。它仍可能因探索不足失败，失败应被如实记录。
   k=1是估计器的诊断阶段，不替代k=2/3的调查与后续决策链。
   固定归一化也会改变整体梯度尺度；需要一次可记录的梯度/LR尺度校准，不能把
   除数变化带来的有效步长变化误当成算法收益，也不因此展开新的大规模调参网格。
3. **k>1时先选择局部oracle监督还是整段return，再决定credit。**若沿用当前
   “正确prefix保留”的逐决策目标，可借鉴anchor grouping，只在相同可见信息状态、
   剩余k及参考身份中比较局部binary标签；这属于state-level oracle训练适配，
   不称为原版GiGPO。若改为整段任务目标，则采用真正的trajectory return与
   return-to-go/同state优势，而不能减其他轨迹的平均局部正确率。
4. **验证标签是模型可见信息的函数。**同一实际prompt若因未展示的剩余k或
   其他变量得到互斥最优集合，必须先修正任务条件；只把它们分成不同group不能
   消除监督矛盾。现有compact记录的100个root prompt互不重复，不能据此推断
   全部后续节点也无此问题；完整cross-question审计尚未完成。
5. **按实际训练reward检查有效采样。**借鉴DAPO动态采样的原则，但设置总采样
   预算并保留困难题账本。全错题不能无限重采，也不能删除后宣称问题已解决。
   所有被过滤输出、探索尝试、额外oracle调用分别记账，避免只计入“有用token”
   制造效率优势。增加采样上限不是保证探索成功的方法。
6. **需要利用完整Q时，建立独立oracle辅助对照。**AggreVaTeD等比随手发明
   dense reward更接近我们的信息条件；实现时要说明action概率如何定义、oracle
   成本如何计入。oracle-action监督也可作可学习性诊断。它们不默默混入纯RL。
7. **一次只检验一个算法差别。**先做D/native同权重、同渲染/生成设置的采样
   核对及k=1基线；再看k>1的credit；最后才做连续反馈对照。20×8继续标为
   工程候选，不再同时搜索batch、重复次数、温度、KL与多种新reward组合。

这条路线保留原“对最优行动的明确要求”，同时先解决估计器和探索是否可用。
若要比较SP与slices，双方的oracle信息、reward定义、优化器和预算计法必须一致，
不能让一边获得额外专家动作监督而另一边只有稀疏终局reward，再归因于slicing。

## 最小验收，而非继续堆训练时长

- 同一固定模型的D/native采样差异得到解释；确认weights、tokenized prompt、
  chat template、tool rendering、temperature和输出上限，不能只看messages相同。
- 记录同state组内binary对比、Q-gap对比、首步/后续步骤正确率及格式失败；
  不能只用“整段active组比例”验收信息学习。
- 报告严格最优动作率、整段成功率、regret、动作重复、实际熵（若计算）、
  长度、梯度、KL和behavior/actor差异。验证需补充独立的信息价值题，旧test不重划。
- 用固定held-out检查策略质量；CPU代数检查和别的论文结果都不算本模型收敛证据。

[代数检查脚本](../../new/terminal_training_protocol_review_20261016/algebraic_checks.py)
与[结果](../../new/terminal_training_protocol_review_20261016/algebraic_checks.json)
复核了KL小gap例子、binary丢失次优差异、重复错误时连续LOO也为0、当前local
advantage示例、可变长度奖励累加反例和potential telescoping。它们不包含模型训练。
