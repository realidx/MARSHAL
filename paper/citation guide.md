1. Σ-Mem
Σ-Mem: An Online Reliability Memory for LLM-based Multi-Agent Systems
目前应引用 arXiv 2607.27958；DBLP 也仍将它作为 CoRR/preprint 收录，没有找到正式会议版本。arXiv
@misc{feng2026sigmamem,
  title         = {{$\Sigma$-Mem}: An Online Reliability Memory for LLM-based Multi-Agent Systems},
  author        = {Peilin Feng and Suorong Yang and Soujanya Poria},
  year          = {2026},
  eprint        = {2607.27958},
  archivePrefix = {arXiv}
}
内容定位： 它研究的是 longitudinal partner reliability / trust memory。不是单纯存 interaction history，而是维护每个 peer 的 competence/reliability state，以及 peers 之间的关系信息，并根据后续 correctness feedback 在线更新。尤其适合你写 partner belief / partner adaptation / reliability tracking 的 related work。Hugging Face
2. A Benchmark for Multi-Party Negotiation Games from Real Negotiation Data
目前只有 arXiv 2603.14066，repo 里甚至还明确写着 venue TODO，所以这里不要编会议。arXiv
@misc{benac2026benchmark,
  title         = {A Benchmark for Multi-Party Negotiation Games from Real Negotiation Data},
  author        = {Leo Benac and Jonas Raedler and Zilin Ma and Finale Doshi-Velez},
  year          = {2026},
  eprint        = {2603.14066},
  archivePrefix = {arXiv}
}
内容定位： 这就是我们一直说的 BENAC。核心是 multi-party negotiation 被表示成一系列 binding action-level commitments，而不是一次性谈出最终 allocation；环境能控制 incentive alignment、goal complexity、payoff structure，并研究不同 value approximation / planning 方法。对你最重要的是它给了一个 multi-party strategic planning under commitments 的现成 formal environment。arXiv
3. A game theory for foundation models shows new paths to rational cooperation through similarity inference
目前仍是 arXiv 2608.03958。作者 Guillaume Lajoie 的 publication page 也明确标为 arXiv，并提供了 BibTeX。Guillaume Lajoie
@misc{meulemans2026gametheory,
  title         = {A Game Theory for Foundation Models Shows New Paths to Rational Cooperation through Similarity Inference},
  author        = {Alexander Meulemans and Maciej Wo{\l}czyk and Marissa A. Weis
                   and Rajai Nasser and Roberta Rocca and Seijin Kobayashi
                   and Guillaume Lajoie and Angelika Steger and Blake Richards
                   and Marcus Hutter and James Manyika and Rif A. Saurous
                   and Jo{\~a}o Sacramento and Blaise Ag{\"u}era y Arcas},
  year          = {2026},
  eprint        = {2608.03958},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI}
}
我这里特意把特殊字符处理成 LaTeX，避免 reference.bib 以后因为 Wołczyk / João / Agüera 出问题。
内容定位： 它认为 foundation-model agent 不完全符合 classical game theory 的“decoupled agency”假设，因为模型在规划时也会预测自己的行为。作者提出 embedded Bayesian agent / embedded equilibrium：agent 可以从自己与对方的行为相似性推断对方，从而在 social dilemmas 中出现经典 Nash reasoning 不预测的合作。arXiv
这篇对你比较偏 theoretical motivation，不是直接 MAS training baseline。
4. CollabSim
CollabSim: A CSCW-Grounded Methodology for Investigating Collaborative Competence of LLM Agents through Controlled Multi-Agent Experiments
目前引用 arXiv 2606.06399。作者 Jiaju Chen 的主页和 Microsoft Research 都仍然把它标成 preprint/arXiv。Jiaju Chen / 陈家驹
@misc{chen2026collabsim,
  title         = {{CollabSim}: A {CSCW}-Grounded Methodology for Investigating Collaborative Competence of {LLM} Agents through Controlled Multi-Agent Experiments},
  author        = {Jiaju Chen and Bo Sun and Yuxuan Lu and Yun Wang and Dakuo Wang and Bingsheng Yao},
  year          = {2026},
  eprint        = {2606.06399},
  archivePrefix = {arXiv}
}
这里有个小 metadata 问题：Microsoft 页面写的是 Baochen Sun，但 arXiv 和第一作者主页写的是 Bo Sun；既然我们引用的是 arXiv，我建议 bibliography 跟 arXiv metadata，用 Bo Sun。arXiv
内容定位： 它从 CSCW 文献出发，把 collaborative competence 分解成 common ground、shared task understanding、individual/collective incentives、misalignment repair 等，并用 controllable multi-agent experiments + action-level probes 来诊断这些能力。和你的工作关系主要在于：不要只看 task reward，而要诊断 interaction process 本身。 Microsoft
5. Commitment To Cooperation With Self-Negotiated Contracts
这个应该明确引用 COLM 2026，而不是 arXiv。COLM 官方 accepted-papers 页面已经列出，作者自己的 lab 页面也标成 COLM。Colm Event Hosts
COLM 2026 的正式名称是 The Third Annual Conference on Language Modeling；常见 BibTeX booktitle 写法是 Proceedings of the Third Conference on Language Modeling (COLM)。Colmweb
@inproceedings{wyse2026commitment,
  title     = {Commitment To Cooperation With Self-Negotiated Contracts},
  author    = {Tim Wyse and Kaitlin Bustos and Yulia Volkova and Max Kleiman-Weiner},
  booktitle = {Proceedings of the Third Conference on Language Modeling (COLM)},
  year      = {2026}
}
等 COLM proceedings 正式上线后，如果有 pages / OpenReview identifier，可以再补，但现在这条已经足够用于 ICLR submission。
内容定位： 它研究的正是你之前关注的 commitment problem：合作成本先发生、收益后发生，所以 agent 有中途 defect 的诱因。它在一个 bargaining + spatial navigation 环境里让 agents 自己 negotiate contracts，并比较 programmatic contracts、natural-language contracts 等。合同作为 explicit commitment mechanism 能提升合作结果。arXiv
6. Cooperate to Compete: Strategic Coordination in Multi-Agent Conquest
这篇现在应该引用 EMNLP 2026 Main Conference。Alan Zhu 的 publication page 明确写了 “2026, EMNLP Main Conference”；作者团队也公开宣布 accepted to EMNLP 2026 Main。Alan Zhu
目前 ACL Anthology 的最终 proceedings metadata 似乎还没上线，所以先用：
@inproceedings{oneill2026cooperate,
  title     = {Cooperate to Compete: Strategic Coordination in Multi-Agent Conquest},
  author    = {Abigail O'Neill and Alan Zhu and Mihran Miroyan and Narges Norouzi and Joseph E. Gonzalez},
  booktitle = {Proceedings of the 2026 Conference on Empirical Methods in Natural Language Processing},
  year      = {2026}
}
以后 Anthology 上线后只需要补 pages，不必换 citation key。
内容定位： C2C 是一个很典型的 mixed-motive, long-horizon, multi-party environment：每个 player 有 private objective，可以进行 private negotiation，agreement 非 binding，因此联盟可以形成、维持、背叛；短期 cooperation 服务于长期 individual objective。arXiv
对你来说，它是非常重要的 realistic strategic interaction / mixed incentives reference，但它重点不是 partner belief + conditioned planning 的机制拆解。
7. Epistemic Context Learning
Epistemic Context Learning: Building Trust the Right Way in LLM-Based Multi-Agent Systems
目前还是 arXiv 2601.21742。作者所在 DeCLaRe Lab 目前也明确列为 “arXiv preprint”，没有发现正式会议版本。DeCLaRe Lab
@misc{zhou2026epistemic,
  title         = {Epistemic Context Learning: Building Trust the Right Way in {LLM}-Based Multi-Agent Systems},
  author        = {Ruiwen Zhou and Maojia Song and Xiaobao Wu and Sitao Cheng
                   and Xunjian Yin and Yuxi Xie and Zhuoqun Hao and Wenyue Hua
                   and Liangming Pan and Soujanya Poria and Min-Yen Kan},
  year          = {2026},
  eprint        = {2601.21742},
  archivePrefix = {arXiv}
}
内容定位： 这篇和 Σ-Mem 很接近你的 partner belief。它认为 MAS 会 blind conformity，一个关键原因是 agent 不会根据 interaction history 判断 peer reliability。ECL 显式从 history 构建 peer profiles，然后让模型基于这些 profiles 做判断，还进一步用 RL 优化。arXiv
区别可以粗略理解为：
- ECL: explicitly build/use epistemic peer profile；
- Σ-Mem: maintain an online reliability memory/state。
8. Patterns and problems in emerging multiagent systems
你给的标题少了一个词。Anthropic 官网正式标题是：
Patterns and problems in emerging multiagent systems

发布日期是 August 13, 2026，页面属于 Anthropic Frontier Red Team；网页列出的 corresponding author 是 Carolyn Zou。Anthropic
这不是论文，所以不要写成 arXiv 或 conference。我建议用 corporate author，最稳：
@misc{anthropic2026multiagent,
  author       = {{Anthropic}},
  title        = {Patterns and Problems in Emerging Multiagent Systems},
  year         = {2026},
  month        = aug,
  howpublished = {Anthropic Research},
  note         = {Published August 13, 2026}
}
如果你坚持记录访问日期，可以再加：
note = {Anthropic Research, accessed September 20, 2026}
我倾向于不要把 Carolyn Zou 写成唯一 author，因为页面只说 “Corresponding author”，并没有给完整个人作者列表；引用机构 {Anthropic} 更稳妥。
内容定位非常重要： 它不是单个 benchmark，而是总结 Anthropic 对 emerging agent-agent interaction 的一系列观察，包括：
- swarm coordination；
- conformity / correlated failures；
- unreliable-source / epistemic failures；
- hidden-profile information pooling；
- incompatible goals；
- long-lived peer interaction。Anthropic
尤其和你的 motivation 很吻合：他们明确指出 agents 擅长把其他 agent 当作“tool invocation”，但对 distinct, long-lived peers with their own goals and behaviors 的处理还很弱。Anthropic
9. Social Gym and SPaRTan
Social Gym and SPaRTan: Benchmarking and Improving LLM Social Reasoning via Multi-Agent Game Tournaments
目前建议 arXiv 2608.09128。虽然已经能看到 ACL anonymous submission，但现在没有可靠 evidence 表明它已经成为正式 ACL/EMNLP paper，因此不能提前写 conference。arXiv
@misc{he2026socialgym,
  title         = {Social Gym and {SPaRTan}: Benchmarking and Improving {LLM} Social Reasoning via Multi-Agent Game Tournaments},
  author        = {Keyu He and Xuhui Zhou and Maarten Sap},
  year          = {2026},
  eprint        = {2608.09128},
  archivePrefix = {arXiv}
}
内容定位：
- Social Gym：21 个 rule-verifiable multi-agent social games；
- 用 tournament / Elo 做跨游戏评价；
- 覆盖 cooperative、competitive、mixed-motive、hidden-role 等；
- SPaRTan：self-play → trajectory reflection → transferable playbook → 在后续 games 中复用；
- 它是 training-free，并不是 weight-level RL self-play。arXiv
所以它对你最重要的是 game-based social reasoning evaluation + cross-game transfer motivation。
10. Systematic Failures in Collective Reasoning under Distributed Information in Multi-Agent LLMs
这篇必须引用 ICML 2026，不要再用 arXiv。
第一作者主页给出的正式 BibTeX 是 “Forty-third International Conference on Machine Learning”，ICML 官方列表也已经收录它。Yuxuan Li
推荐：
@inproceedings{li2026systematic,
  title     = {Systematic Failures in Collective Reasoning under Distributed Information in Multi-Agent {LLM}s},
  author    = {Yuxuan Li and Aoi Naito and Hirokazu Shirado},
  booktitle = {Proceedings of the 43rd International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {306},
  year      = {2026}
}
现在先不硬填 pages；最终 PMLR metadata 完全稳定后再补即可。已有文献也将它引用为 ICML 2026 / PMLR 306。ResearchGate
内容定位： 这就是 HiddenBench。它通过 Hidden Profile paradigm 控制 distributed information：共享信息倾向错误答案，每个 agent 又各自掌握部分 decisive hidden facts，因此必须主动交换 unique information。核心发现是 multi-agent interaction 远低于把所有信息直接给一个 agent 的 full-profile baseline，主要问题是 无法识别 latent information asymmetry、过早围绕 shared evidence 收敛、没有主动探索别人可能知道但尚未说出的信息。alphaXiv
这是你 partner belief / epistemic uncertainty detection motivation 最直接的一篇 reference。
11. Talk is Cheap, Communication is Hard
这篇现在已经是 COLM 2026 accepted paper。COLM 官方 accepted-papers 页面明确列出。Colm Event Hosts
但这里有一个我们必须认真处理的 metadata 问题：
- arXiv/current preprint：Yiheng Yao, Chelsea Zou, Robert D. Hawkins；arXiv
- COLM 官方 accepted-papers 页面：Yiheng Yao, Robert Hawkins。Colm Event Hosts
因此，我现在不建议把 conference-author list 永久冻结。最稳妥做法是：
@inproceedings{yao2026talk,
  title     = {Talk is Cheap, Communication is Hard: Dynamic Grounding Failures and Repair in Multi-Agent Negotiation},
  author    = {Yiheng Yao and Chelsea Zou and Robert D. Hawkins},
  booktitle = {Proceedings of the Third Conference on Language Modeling (COLM)},
  year      = {2026}
}
然后在 COLM final proceedings 上线后重新核一次 author list。
这里我暂时保留 Chelsea Zou，是因为实际你正在阅读和引用的 manuscript、arXiv metadata、OpenReview preprint PDF 都是三位作者；仅凭 conference schedule 删掉一个作者风险更大。arXiv
内容定位： 它提出 dynamic grounding failure。两个 agents 各有 private projects，需要通过多轮 communication 协调共享资源；单个 agent 在 oracle/full-information 条件下会解，但 pair interaction 仍显著失败。论文归纳的 failure 包括 shared-history loss、early-proposal anchoring、默认 equal split、referential binding error，并强调瓶颈不只是信息有没有交换，而是 joint plan formation, commitment, and execution。arXiv
这对你现在的 conditioned interaction planning claim 很有用。

1. I-POMDP：你的 citation 基本正确
正式 JAIR 版本就是 2005 年 Volume 24, pp. 49–79，DOI 也正确。ML Anthology
我建议把你那个 url={[https://...](https://...)} 删掉——那是 Markdown 混进 BibTeX 了，而且既然已有 DOI，其实没必要放一个 PDF URL。
@article{gmytrasiewicz2005ipomdp,
  author  = {Gmytrasiewicz, Piotr J. and Doshi, Prashant},
  title   = {A Framework for Sequential Planning in Multi-Agent Settings},
  journal = {Journal of Artificial Intelligence Research},
  volume  = {24},
  pages   = {49--79},
  year    = {2005},
  doi     = {10.1613/JAIR.1579}
}
这篇对我们的作用非常核心。 它把 POMDP 扩展到 interactive settings：agent 的 belief 不只是 environment state，也包含 models of other agents；然后 action 是在这个 interactive belief state 上做 sequential planning。也就是说，它非常适合作为我们论文里：
partner belief → belief-conditioned planning

这整个 formalization 的理论根。ML Anthology
2. Carmel & Markovitch：正确，但我建议稍微补完整
Springer LNCS 1042，pages 40–52，1996，DOI 都是对的。Workshop 实际发生于 IJCAI 1995，但 Springer proceedings 出版年份是 1996，所以你的 year={1996} 没问题。Tilda
@incollection{carmel1996opponent,
  author    = {Carmel, David and Markovitch, Shaul},
  title     = {Opponent Modeling in Multi-Agent Systems},
  booktitle = {Adaptation and Learning in Multi-Agent Systems},
  editor    = {Wei{\ss}, Gerhard and Sen, Sandip},
  series    = {Lecture Notes in Computer Science},
  volume    = {1042},
  pages     = {40--52},
  publisher = {Springer},
  year      = {1996},
  doi       = {10.1007/3-540-60923-7_18}
}
这里我把你 DOI 里的 \_ 改成了 _。在 doi={...} field 里不要人为加 LaTeX escape 更干净。
内容定位： 非常经典的 opponent modeling：从 opponent 的 input/output behavior 推断对方模型，然后针对 inferred opponent model 求最优 interaction strategy。所以它支持的是比“预测别人”更强的观点：
opponent modeling is useful insofar as the inferred model changes one's interactive strategy.

这和我们现在强调的 belief 和 conditioned planning 依赖关系非常吻合。Tilda
3. HOP：你这条是对的
PMLR 官方就是 ICML 2024，Volume 235，20004–20022。Proceedings of Machine Learning Research
清理后：
@inproceedings{huang2024hop,
  author    = {Huang, Yizhe and Liu, Anji and Kong, Fanqi and Yang, Yaodong and Zhu, Song-Chun and Feng, Xue},
  title     = {Efficient Adaptation in Mixed-Motive Environments via Hierarchical Opponent Modeling and Planning},
  booktitle = {Proceedings of the 41st International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {235},
  pages     = {20004--20022},
  publisher = {PMLR},
  year      = {2024}
}
这篇其实是我们现在最漂亮的 classical/MARL bridge reference 之一。HOP 明确分成：
\[
\text{opponent modeling}
\rightarrow
\text{belief over goals}
\rightarrow
\text{planning/MCTS best response}.
\]而且 belief 会 across episodes 和 within episode 更新，然后 planning module 用 inferred goal information 做 best response。Proceedings of Machine Learning Research
换句话说，我们论文如果写：
Classical multi-agent decision-making has long coupled opponent modeling with downstream planning rather than treating belief inference as an isolated prediction task.

后面放 Carmel + I-POMDP + HOP 会非常合理。
4. CalBench
正式标题：
CalBench: Evaluating Coordination-Privacy Trade-offs in Multi-Agent LLMs
目前我没有找到正式 conference version，应该按 arXiv:2605.09823 引。
这里有一个需要注意的 metadata 更新：搜索结果的旧 metadata 有时只显示 4 位作者，但最新版 manuscript 和 DBLP 已经包括 Noah D. Goodman，所以现在应该用五位作者。arXiv
@misc{zou2026calbench,
  author        = {Zou, Chelsea and Yao, Yiheng and She, Selena and Goodman, Noah D. and Hawkins, Robert D.},
  title         = {{CalBench}: Evaluating Coordination-Privacy Trade-offs in Multi-Agent {LLM}s},
  year          = {2026},
  eprint        = {2605.09823},
  archivePrefix = {arXiv},
  primaryClass  = {cs.MA}
}
这个我现在认为应该进我们的 reference.bib。
它不是一般的“让几个 agent 聊天” benchmark，而是 deliberately decentralized：
- 每个 agent 只有自己的 private calendar；
- 没有一个 agent 能看到 global state；
- 必须 communication 才能完成 shared scheduling；
- 有 oracle solution；
- 可以量 coordination quality、communication efficiency、fairness、privacy leakage；
- communication 和最终 scheduling commitments 是分开的。arXiv
所以它和我们的 BENAC-P 不同，但在论文里很适合支持：
recent benchmarks are moving toward necessarily decentralized tasks with private information and verifiable joint outcomes.

它尤其适合放在 environment / benchmark motivation 那部分。
从我们过去项目讨论里，我建议再补的 references
我把过往聊天扫了一遍。除了你第一轮已经列出的 ECL、Σ-Mem、BENAC、C2C、CollabSim、HiddenBench、Talk is Cheap、Social Gym/SPaRTan 等，我们反复关注过的 work 里，下面这些最值得进入最终 bib。
我先按和当前论文的相关性分，而不是按历史讨论次数。
A. 我认为几乎一定会 cite：MARSHAL
MARSHAL: Incentivizing Multi-Agent Reasoning via Self-Play with Strategic LLMs
这里有个很重要的更新：不要再引用 arXiv 版本，它已经是 ICLR 2026 正式论文。官方 project page、OpenReview 和 ICLR 信息都确认了这一点。Thu Nics
@inproceedings{yuan2026marshal,
  author    = {Yuan, Huining and Xu, Zelai and Tan, Zheyue and Yi, Xiangmin and Guang, Mo and Long, Kaiwen and Hui, Haojia and Li, Boxun and Chen, Xinlei and Zhao, Bo and Zhang, Xiao-Ping and Yu, Chao and Wang, Yu},
  title     = {{MARSHAL}: Incentivizing Multi-Agent Reasoning via Self-Play with Strategic {LLM}s},
  booktitle = {International Conference on Learning Representations},
  year      = {2026}
}
作用：training + transfer 核心 comparison。
它正是：
game self-play RL → strategic ability → held-out games → downstream MAS reasoning transfer.

而且训练覆盖 competitive/cooperative 和 perfect/imperfect information games，并专门处理 multi-turn credit assignment。OpenReview
所以我们的 paper 不可能不 cite 它。
B. 也几乎一定要 cite：SPIRAL
SPIRAL: Self-Play on Zero-Sum Games Incentivizes Reasoning via Multi-Agent Multi-Turn Reinforcement Learning
它同样已经从 arXiv 升级成 ICLR 2026。ICLR
@inproceedings{liu2026spiral,
  author    = {Liu, Bo and Guertler, Leon and Yu, Simon and Liu, Zichen and Qi, Penghui and Balcells, Daniel and Liu, Mickel and Tan, Cheston and Shi, Weiyan and Lin, Min and Lee, Wee Sun and Jaques, Natasha},
  title     = {{SPIRAL}: Self-Play on Zero-Sum Games Incentivizes Reasoning via Multi-Agent Multi-Turn Reinforcement Learning},
  booktitle = {International Conference on Learning Representations},
  year      = {2026}
}
它通过 zero-sum game self-play 训练，并展示 reasoning transfer；multi-game training 用 Tic-Tac-Toe、Kuhn Poker、Simple Negotiation。arXiv
它和 MARSHAL 正好是我们最直接的：
game interaction training can induce transferable abilities

prior work。
我们的区别则是 training target 不再只是 generic reasoning / strategic ability，而是针对 general-sum, partial-information MAS 中的 partner belief + conditioned interaction planning。
C. TERMS-Bench
正式标题：
TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal Rate
目前还是 arXiv 2605.13909。官方 benchmark 页面自己给出的 citation 也是这个版本。TERMS-Bench
@misc{zhang2026termsbench,
  author        = {Zhang, Erica and Zhang, Fangzhao and Pappu, Aneesh and El, Batu and Blanchet, Jose and Athey, Susan and Liu, Jiashuo and Zou, James},
  title         = {{TERMS-Bench}: Diagnosing {LLM} Negotiation Agents Beyond Deal Rate},
  year          = {2026},
  eprint        = {2605.13909},
  archivePrefix = {arXiv},
  primaryClass  = {cs.GT}
}
这篇和我们 diagnostic design 的关系很直接：
- latent counterpart type；
- belief error；
- oracle-reference optimality；
- 分开判断 belief 和最终 negotiation performance；
- environment 本身做 verifier，而不是 LLM judge。arXiv
它非常适合支持我们为什么不只报 aggregate reward。
D. Theory of Mind Benchmarks are Broken
正式发表为 ICML 2025，一定不要再引 arXiv。Proceedings of Machine Learning Research
@inproceedings{riemer2025tom,
  author    = {Riemer, Matthew and Ashktorab, Zahra and Bouneffouf, Djallel and Das, Payel and Liu, Miao and Weisz, Justin D. and Campbell, Murray},
  title     = {Position: Theory of Mind Benchmarks are Broken for Large Language Models},
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {267},
  pages     = {82091--82130},
  publisher = {PMLR},
  year      = {2025}
}
这篇很适合我们，因为它区分：
- literal ToM：我能不能预测 partner；
- functional ToM：我有没有真的根据 partner 改变行为。
而它的核心 empirical observation 就是二者并不等价。Proceedings of Machine Learning Research
这实际上是我们：
\[
\text{belief quality} \neq \text{conditioned action quality}
\]最直接的 LLM-era conceptual reference 之一。
E. Why Do LLMs Struggle in Strategic Play?
这篇现在还是 arXiv 2605.00226 / under review，作者主页也明确标成 under review，所以不能写 conference。Jan Sobotka
@misc{sobotka2026strategic,
  author        = {Sobotka, Jan and Karabag, Mustafa O. and Topcu, Ufuk},
  title         = {Why Do {LLM}s Struggle in Strategic Play? Broken Links Between Observations, Beliefs, and Actions},
  year          = {2026},
  eprint        = {2605.00226},
  archivePrefix = {arXiv}
}
这篇几乎就是我们 claim 的近邻：
1. observation–belief gap
2. belief–action gap
尤其第二个：模型即使有较好的 belief，也未必会把它转换成好的 action。arXiv
所以 related work 里非常值得直接讨论，而不只是 citation dump。
F. Bayesian Partner Modelling
Bayesian Partner Modelling enables Adaptive Replanning for LLM Coordination
这是 2026 年 8 月的新 work，目前只有 arXiv 2608.18490。arXiv
@misc{goel2026bayesian,
  author        = {Goel, Harsh and Ellendula, Aditya Sai and Tadiparthi, Vaishnav and Pari, Ehsan Moradi and Mahjoub, Hossein Nourkhiz and Chinchali, Sandeep P.},
  title         = {Bayesian Partner Modelling Enables Adaptive Replanning for {LLM} Coordination},
  year          = {2026},
  eprint        = {2608.18490},
  archivePrefix = {arXiv}
}
它也是特别近的 work：
\[
\text{Bayesian partner tracking}
\rightarrow
\text{detect changed skill}
\rightarrow
\text{trigger replanning}.
\]甚至直接测一个 belief-action gap：partner estimate 已经正确，但执行的 skill 仍然与 partner 不互补。arXiv
因此它很适合在我们 related work 中明确区分：
existing work demonstrates belief-conditioned replanning in cooperative skill coordination; we study the more general strategic setting where latent partner incentives/information jointly determine interaction planning.

G. Hypothetical Minds
已经正式发表为 ICLR 2025。ICLR Proceedings
@inproceedings{cross2025hypothetical,
  author    = {Cross, Logan and Xiang, Violet and Bhatia, Agam and Yamins, Daniel L. K. and Haber, Nick},
  title     = {Hypothetical Minds: Scaffolding Theory of Mind for Multi-Agent Tasks with Large Language Models},
  booktitle = {International Conference on Learning Representations},
  year      = {2025}
}
它从 observations 生成关于 other agents' strategy 的 natural-language hypotheses，不断检验和更新，然后用这些 hypotheses scaffold hierarchical planning。测试包括 cooperative、competitive 和 mixed-motive Melting Pot domains。ICLR Proceedings
这是非常好的：
explicit partner model → planning

LLM reference。
H. Theory of Mind for Multi-Agent Collaboration via LLMs
这是 EMNLP 2023 正式论文。ACL Anthology
@inproceedings{li2023theory,
  author    = {Li, Huao and Chong, Yu Quan and Stepputtis, Simon and Campbell, Joseph and Hughes, Dana and Lewis, Michael and Sycara, Katia},
  title     = {Theory of Mind for Multi-Agent Collaboration via Large Language Models},
  booktitle = {Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing},
  pages     = {180--192},
  publisher = {Association for Computational Linguistics},
  year      = {2023},
  doi       = {10.18653/v1/2023.emnlp-main.13}
}
它发现 explicit belief-state representation 可以改善 ToM inference 和 collaborative task performance，同时指出 long-horizon planning/state tracking failure。ACL Anthology
属于比较早但很干净的 LLM MAS reference。
I. Adaptive Theory of Mind
这个之前我们也讨论过，而且现在已经是 AAAI 2026 正式版本，不要引用 arXiv。AAAI Publications
@article{mu2026adaptive,
  author  = {Mu, Chunjiang and Zeng, Ya and Zhang, Qiaosheng and Shao, Kun and Chu, Chen and Guo, Hao and Jia, Danyang and Wang, Zhen and Hu, Shuyue},
  title   = {Adaptive Theory of Mind for {LLM}-based Multi-Agent Coordination},
  journal = {Proceedings of the AAAI Conference on Artificial Intelligence},
  volume  = {40},
  number  = {35},
  pages   = {29608--29616},
  year    = {2026},
  doi     = {10.1609/aaai.v40i35.40204}
}
它从 prior interactions 推断 partner 的 ToM order，然后根据该估计预测 partner action，并改变 coordination behavior。AAAI Publications
相关，但我会把优先级放在 Hypothetical Minds / Functional ToM / Bayesian Partner Modelling 后面。
J. BAD：Bayesian Action Decoder
这篇是 ICML 2019，对我们的理论背景其实很有价值。Proceedings of Machine Learning Research
@inproceedings{foerster2019bad,
  author    = {Foerster, Jakob and Song, Francis and Hughes, Edward and Burch, Neil and Dunning, Iain and Whiteson, Shimon and Botvinick, Matthew and Bowling, Michael},
  title     = {Bayesian Action Decoder for Deep Multi-Agent Reinforcement Learning},
  booktitle = {Proceedings of the 36th International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {97},
  pages     = {1942--1951},
  publisher = {PMLR},
  year      = {2019}
}
它最关键的 conceptual point 是：
actions themselves provide evidence about private information.

即：
\[
a_j^t
\rightarrow
\text{Bayesian belief update}
\rightarrow
b^{t+1}.
\]而 agent 又可以选择 informative actions，利用“别人会从我的 action 更新 belief”这一事实。Proceedings of Machine Learning Research
如果我们 preliminaries 讨论 interaction 本身既利用 belief 又产生 evidence，BAD 很值得 cite。
K. Other-Play
正式 ICML 2020。Proceedings of Machine Learning Research
@inproceedings{hu2020otherplay,
  author    = {Hu, Hengyuan and Lerer, Adam and Peysakhovich, Alex and Foerster, Jakob},
  title     = {{Other-Play} for Zero-Shot Coordination},
  booktitle = {Proceedings of the 37th International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {119},
  pages     = {4399--4410},
  publisher = {PMLR},
  year      = {2020}
}
它是我们讨论“naive self-play 学到 convention，未必 transfer 到 unseen partners”时非常经典的 reference。Proceedings of Machine Learning Research
如果 reviewer 问：
为什么不直接认为 self-play 就会得到 transferable interaction strategies？

Other-Play 是早期非常重要的反例/动机。
L. Modeling Others' Minds as Code / ROTE
之前我们也叫过它 ROTE。它现在已经是 ICLR 2026，而且不是 preprint。ICLR Proceedings
@inproceedings{jha2026modeling,
  author    = {Jha, Kunal and Huang, Aydan and Ye, Eric and Jaques, Natasha and Kleiman-Weiner, Max},
  title     = {Modeling Others' Minds as Code},
  booktitle = {International Conference on Learning Representations},
  year      = {2026}
}
它把 other-agent behavioral model 表示成 behavioral programs/code hypotheses，然后对这些程序做 probabilistic inference。

2. Social-R1
Social-R1: Towards Human-like Social Reasoning in LLMs
截至现在仍然是 arXiv:2603.09249；作者的 Microsoft Research publication page 也仍标成 arXiv，没有找到正式 conference version。arXiv
@misc{wu2026socialr1,
  author        = {Wu, Jincenzi and Lei, Yuxuan and Lian, Jianxun and Huang, Yitian
                   and Zhou, Lexin and Li, Haotian and Xie, Xing and Meng, Helen},
  title         = {{Social-R1}: Towards Human-like Social Reasoning in {LLM}s},
  year          = {2026},
  eprint        = {2603.09249},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL}
}
它提出 ToMBench-Hard，然后用 multi-dimensional process rewards 对 social reasoning trajectory 做 RL，而不是只优化最终答案。arXiv
和我们的关系：中等偏强。
它非常适合 supporting：
social reasoning abilities can be explicitly post-trained with process-level supervision.

但它不是 multi-agent interaction training，也没有我们这种 partner belief → interaction planning → action → new evidence 的闭环。所以不要把它写成最直接的 prior。

From Passive Delegates to Strategic Negotiators: Reinforcing Social Reasoning in Small Language Models with SocialRL
目前是 arXiv:2608.13787，Microsoft 和作者主页也都仍标为 arXiv。arXiv
@misc{hua2026socialrl,
  author        = {Hua, Wenyue and Huang, Zachary and Payne, Tyler
                   and Yousefi, Safoora and Amershi, Saleema
                   and Celikyilmaz, Asli},
  title         = {From Passive Delegates to Strategic Negotiators:
                   Reinforcing Social Reasoning in Small Language Models with {SocialRL}},
  year          = {2026},
  eprint        = {2608.13787},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI}
}
这篇我认为现在是我们 最重要的近邻 work 之一。
它训练 4B model 做六类 principal-driven social/negotiation tasks，包括 Deal-or-No-Deal、CaSiNo、Marketplace、Calendar 等；同时系统研究 cross-domain transfer，并加入显式 ToM scaffold。尤其值得注意的是，他们报告 distilling ToM traces 比只 distill actions 更好，而且可以跨环境 generalize。

4. ToMA — 我认为必须加
Infusing Theory of Mind into Socially Intelligent LLM Agents
已经是 Findings of ACL 2026，不要再用 arXiv。ACL Anthology
@inproceedings{hwang2026infusing,
  author    = {Hwang, EunJeong and Yin, Yuwei and Carenini, Giuseppe
               and West, Peter and Shwartz, Vered},
  title     = {Infusing Theory of Mind into Socially Intelligent {LLM} Agents},
  booktitle = {Findings of the Association for Computational Linguistics: ACL 2026},
  pages     = {11327--11360},
  publisher = {Association for Computational Linguistics},
  year      = {2026},
  doi       = {10.18653/v1/2026.findings-acl.551}
}
这篇非常接近我们 conceptual claim，因为 ToMA 明确把 mental-state inference 和 dialogue lookahead 结合起来，目标不是让 ToM prediction 本身更准，而是产生对 downstream action 有用的 mental state。ACL Anthology
这几乎就是：
\[
B \text{ should be useful for } P
\]的 LLM-era direct reference。
5. LLM-Coordination — 也建议一定加
LLM-Coordination: Evaluating and Analyzing Multi-agent Coordination Abilities in Large Language Models
正式版本：Findings of NAACL 2025。ACL Anthology
@inproceedings{agashe2025llmcoordination,
  author    = {Agashe, Saaket and Fan, Yue and Reyna, Anthony and Wang, Xin Eric},
  title     = {{LLM}-Coordination: Evaluating and Analyzing Multi-agent
               Coordination Abilities in Large Language Models},
  booktitle = {Findings of the Association for Computational Linguistics: NAACL 2025},
  pages     = {8053--8072},
  publisher = {Association for Computational Linguistics},
  year      = {2025},
  doi       = {10.18653/v1/2025.findings-naacl.448}
}
它直接把能力拆成：
- environment comprehension；
- ToM reasoning；
- joint planning。
并观察到 partner beliefs / intentions 与 coordination planning 之间的联系。ACL Anthology
这和我们“partner belief + conditioned planning”非常接近，只是他们是 evaluation，而不是我们这样的能力训练。
6. GIFT — 强烈建议加
GIFT: Games as Informal Training for Generalizable LLMs
目前仍是 arXiv。arXiv
@misc{lyu2026gift,
  author        = {Lyu, Nuoyan and Xu, Bingbing and Meng, Weihao and Yuan, Yige
                   and Zhang, Yang and Huang, Zhiyong and Chua, Tat-Seng
                   and Shen, Huawei},
  title         = {{GIFT}: Games as Informal Training for Generalizable {LLM}s},
  year          = {2026},
  eprint        = {2601.05633},
  archivePrefix = {arXiv}
}
Matrix Games + Tic-Tac-Toe + Who's the Spy，用 GRPO game training，目标明确包含 strategic creativity 和 social reasoning，并报告跨 benchmark generalization。arXiv
现在我们 game-training related work 至少应该是：
SPIRAL + MARSHAL + GIFT + SocialRL + Social Gym/SPaRTan
这条线已经很完整。
7. Strat-Reasoner — 应该加
Strat-Reasoner: Reinforcing Strategic Reasoning of LLMs in Multi-Agent Games
这是 ICML 2026，不是 arXiv-only；作者主页已经明确列为 ICML 2026。Batman ZZMC
@inproceedings{he2026stratreasoner,
  author    = {He, Yidong and Lai, Yutao and Yang, Pengxu and Gan, Jiarui
               and Wang, Jiexin and Cai, Yi and Zhao, Mengchen},
  title     = {Strat-Reasoner: Reinforcing Strategic Reasoning of {LLM}s
               in Multi-Agent Games},
  booktitle = {Proceedings of the 43rd International Conference on Machine Learning},
  year      = {2026}
}
它处理 multi-agent game 中由于其他 agent 导致的 non-stationarity 和 reasoning credit assignment，并通过 centralized CoT comparison + hybrid advantage 来训练 strategic reasoning。arXiv
它和我们的差别很清楚：它优化 generic strategic reasoning；我们显式 target latent partner state 和 partner-conditioned planning。
8. Cross-Environment Cooperation — 很值得放 transfer 部分
Cross-environment Cooperation Enables Zero-shot Multi-agent Coordination
正式 ICML 2025。Proceedings of Machine Learning Research
@inproceedings{jha2025crossenvironment,
  author    = {Jha, Kunal and Carvalho, Wilka and Liang, Yancheng
               and Du, Simon Shaolei and Kleiman-Weiner, Max and Jaques, Natasha},
  title     = {Cross-environment Cooperation Enables Zero-shot Multi-agent Coordination},
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning},
  series    = {Proceedings of Machine Learning Research},
  volume    = {267},
  pages     = {27198--27220},
  publisher = {PMLR},
  year      = {2025}
}
这篇提供一个特别好的 prior：
在多个不同 cooperative environments 上训练，可以产生能迁移到 unseen tasks 和 unseen partners 的 general cooperative skills。

这正好支持我们为什么要看 ability transfer，而不是只看 BENAC-P in-domain reward。Proceedings of Machine Learning Research
9. POMCoP — 我觉得应该进 preliminaries/background
POMCoP: Belief Space Planning for Sidekicks in Cooperative Games
AIIDE 2012。AAAI Publications
@article{macindoe2012pomcop,
  author  = {Macindoe, Owen and Kaelbling, Leslie Pack and Lozano-P{\'e}rez, Tom{\'a}s},
  title   = {{POMCoP}: Belief Space Planning for Sidekicks in Cooperative Games},
  journal = {Proceedings of the AAAI Conference on Artificial Intelligence
             and Interactive Digital Entertainment},
  volume  = {8},
  number  = {1},
  pages   = {38--43},
  year    = {2012},
  doi     = {10.1609/aiide.v8i1.12510}
}
这篇其实非常漂亮：
agent 对 partner intention 有 uncertainty；
planning 不仅利用当前 belief，还会主动选择 reveal partner intentions 的 action。

即：
\[
B_t
\rightarrow P_t
\rightarrow a_t
\rightarrow o_{t+1}
\rightarrow B_{t+1}.
\]这和我们 Menu 的 conceptual justification 高度一致。AAAI Publications
10. Bayesian Delegation / Too Many Cooks
正式 journal version：
Too Many Cooks: Bayesian Inference for Coordinating Multi-Agent Collaboration, Topics in Cognitive Science, 2021。Wiley Online Library
@article{wu2021toomanycooks,
  author  = {Wu, Sarah A. and Wang, Rose E. and Evans, James A.
             and Tenenbaum, Joshua B. and Parkes, David C.
             and Kleiman-Weiner, Max},
  title   = {Too Many Cooks: Bayesian Inference for Coordinating
             Multi-Agent Collaboration},
  journal = {Topics in Cognitive Science},
  volume  = {13},
  number  = {2},
  pages   = {414--432},
  year    = {2021},
  doi     = {10.1111/tops.12525}
}
Bayesian Delegation：
\[
\text{infer others' latent intentions by inverse planning}
\rightarrow
\text{choose complementary task/action}.
\]这就是 classical partner belief → conditioned coordination precedent。Wiley Online Library
11. HBA — 也值得作为 classical opponent-model/planning lineage
A Game-Theoretic Model and Best-Response Learning Method for Ad Hoc Coordination in Multiagent Systems, AAMAS 2013。DOI
@inproceedings{albrecht2013hba,
  author    = {Albrecht, Stefano V. and Ramamoorthy, Subramanian},
  title     = {A Game-Theoretic Model and Best-Response Learning Method
               for Ad Hoc Coordination in Multiagent Systems},
  booktitle = {Proceedings of the 2013 International Conference on
               Autonomous Agents and Multi-Agent Systems},
  pages     = {1155--1156},
  year      = {2013}
}
它用 stochastic Bayesian game，把其他 player 的 behavior 表示成 latent type，根据 observed behavior 更新对 type 的 belief，再通过 Bellman-style best-response planning 选择 action。arXiv
所以我们的 classical chain 现在可以非常干净地写成：
Carmel & Markovitch → I-POMDP → HBA / POMCoP / Bayesian Delegation → HOP

而不是只拿 I-POMDP 一个 formalism 顶住整段。


1. Broad MAS failure taxonomy：MAST
这个我之前漏掉了，而且它其实应该是 MAS diagnosis 最核心的 citation 之一。
Why Do Multi-Agent LLM Systems Fail?
正式发表在 NeurIPS 2025 Datasets and Benchmarks Track。作者分析多个 MAS framework 的 execution traces，建立 MAST (Multi-Agent System Failure Taxonomy)，最终得到 14 类 failure，归入：
- system/specification design；
- inter-agent misalignment；
- task verification / termination。
这不是针对某一个 benchmark 的 failure，而是真正从大量真实 MAS traces 里归纳 failure taxonomy。NeurIPS Proceedings
@inproceedings{cemri2025multiagent,
  author    = {Cemri, Mert and Pan, Melissa Z. and Yang, Shuyi
               and Agrawal, Lakshya A. and Chopra, Bhavya and Tiwari, Rishabh
               and Keutzer, Kurt and Parameswaran, Aditya and Klein, Dan
               and Ramchandran, Kannan and Zaharia, Matei
               and Gonzalez, Joseph E. and Stoica, Ion},
  title     = {Why Do Multi-Agent {LLM} Systems Fail?},
  booktitle = {Advances in Neural Information Processing Systems},
  year      = {2025}
}
这篇我建议列为必加。
它可以直接 supporting：
Existing MAS failures are not reducible to single-agent reasoning errors; they also arise from inter-agent misalignment and interaction-level failures.

而我们的贡献就是从这个 broad failure landscape 中进一步提出：
很多 strategic interaction failures 可以追溯到两个更基础、相互依赖的能力：partner belief 和 conditioned interaction planning。

2. Distributed coordination diagnosis：SILO-BENCH
这个也非常值得加，而且已经是正式 ACL 2026 Long Paper：
SILO-BENCH: A Scalable Environment for Evaluating Distributed Coordination in Multi-Agent LLM Systems
它故意不给 preset roles，让 agents 在 information silos 下自己协调，并把任务按 communication complexity 分成 aggregation / mesh / global shuffle。
最关键的发现被他们叫作：
Communication-Reasoning Gap

即 agents 很积极地 communication，但不能把 communication 转换成有效 distributed computation；scale 增加以后 performance 迅速 collapse。ACL Anthology
@inproceedings{zhang2026silobench,
  author    = {Zhang, Yuzhe and Liu, Feiran and Shan, Yi and Huang, Xinyi
               and Yang, Xin and Zhu, Yueqi and Cheng, Xuxin and Liu, Cao
               and Zeng, Ke and Zhang, Terry Jingchen and Jiang, Wenyuan},
  title     = {{SILO-BENCH}: A Scalable Environment for Evaluating
               Distributed Coordination in Multi-Agent {LLM} Systems},
  booktitle = {Proceedings of the 64th Annual Meeting of the
               Association for Computational Linguistics (Volume 1: Long Papers)},
  pages     = {29379--29398},
  publisher = {Association for Computational Linguistics},
  year      = {2026},
  doi       = {10.18653/v1/2026.acl-long.1354}
}
官方 ACL metadata 已经完整，可以直接用。ACL Anthology
它和 HiddenBench 可以很好地区分：
- HiddenBench：不知道别人还有什么信息 → 没主动探索；
- SILO-BENCH：即使 agents 在通信，也不能有效做 distributed computation；
- 我们：不仅要更新 partner belief，还要让 belief 真正改变后续 interaction planning。
3. Coordination ability decomposition：LLM-Coordination
这个上一轮已经加入了，我现在会把它明确放在 MAS diagnosis 而不仅是 general benchmark：
LLM-Coordination: Evaluating and Analyzing Multi-agent Coordination Abilities in Large Language Models, Findings of NAACL 2025。
它非常适合我们的框架，因为直接把 coordination reasoning 分成：
1. Environment Comprehension
2. Theory of Mind
3. Joint Planning
并发现涉及 partner beliefs / intentions 的任务明显更困难。ACL Anthology
所以它其实已经很接近我们后来抽象出的：
\[
\text{partner belief}
\rightarrow
\text{conditioned planning}.
\]4. Broad benchmark：MultiAgentBench
这个我也建议加。
MultiAgentBench: Evaluating the Collaboration and Competition of LLM Agents
正式 ACL 2025 Long Paper。它覆盖 collaboration + competition，并比较 star / chain / tree / graph 等不同 communication topology，还有 group discussion 和 cognitive planning。ACL Anthology
@inproceedings{zhu2025multiagentbench,
  author    = {Zhu, Kunlun and Du, Hongyi and Hong, Zhaochen and Yang, Xiaocheng
               and Guo, Shuyi and Wang, Zhe and Wang, Zhenhailong
               and Qian, Cheng and Tang, Xiangru and Ji, Heng and You, Jiaxuan},
  title     = {{MultiAgentBench}: Evaluating the Collaboration and Competition
               of {LLM} Agents},
  booktitle = {Proceedings of the 63rd Annual Meeting of the
               Association for Computational Linguistics (Volume 1: Long Papers)},
  pages     = {8580--8622},
  publisher = {Association for Computational Linguistics},
  year      = {2025},
  doi       = {10.18653/v1/2025.acl-long.421}
}
它不如 HiddenBench / Talk is Cheap 那样有一个特别 sharp 的 failure claim，但适合 supporting：
MAS performance depends heavily on interaction structure and coordination protocol, not merely individual model capability.