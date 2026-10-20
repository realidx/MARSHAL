# 9月与当前terminal：题面、工具及prompt排查

2026-10-17。仅离线核查输入与日志，不改正式训练代码、奖励、Oracle、数据或checkpoint。
使用 [audit_prompt_interface.py](../../audit_prompt_interface.py) 生成本目录材料。

结论：没有发现工具编号接错、模板强制直接调用、parser隐藏解释或同题评分冲突。
发现了明确的展示语义缺口，以及相较9月弱化的解释指令位置。
这些应优先修复；现有离线证据不能隔离每项对生成概率的独立因果贡献。

## 核查范围

- 本轮307次完成更新的50,232个回答，覆盖376种不同的messages/tools上下文。
- 对376种上下文，按父游戏从初始状态独立重放全部公开事件及pending offer，
  核对当前player、完整public_state、合法动作列表与每个action_index：全部一致。
  此过程只运行原生状态转换，不加载均衡树或求新Oracle。
- 相同可见prompt对应的Q/posterior在已访问上下文中无冲突；Q容差1e-9、posterior容差1e-10。
  重复的game/public_state公共字段无矛盾，未在模型请求里发现Q、teacher、world_index等私有评分字段。
- 9月26日D首批128个回答、9月SP保留的step10全部343个回答，直接从prompt IDs解码实际输入。
  同词表解码response IDs均与原始text完全一致。旧SP这里是续跑样本，不当作base。
- 同时检查9月22日归档source中的chat-template调用及SamplingParams，与当前native代码比对。
- 全量9月样本解释率另见 [此前统计](../september_explanation_comparison.json)。

详尽结果：[audit.json](audit.json)。词表解码仅用于审计，不生成任何模型回答。

## 1. 解释指令的位置明显改变

距离定义：最后一次“Briefly explain / Give brief reasoning”开始，至生成首个assistant token的位置；
按已记录prompt IDs对应的实际token边界计算，包含指令本身，未用字符数代替token数。

| 实际输入范围 | 指令距生成位置，tokens，中位数（最小–最大） |
| --- | ---: |
| 9月26日D首批128个请求 | 29（21–33） |
| 9月SP保留step10的343个请求 | 81（81–139） |
| 当前100道训练入口题 | 985（711–1,454） |

9月D在system里声明“reasoning question / briefly explain”，user末尾再次要求解释并明确
“Keep the explanation outside the tool arguments”。SP的user末尾也要求根据当前状态解释，
注明解释是私有的、放在工具参数之外。

当前common.request只在system规则段末尾放一句“Give brief reasoning, then call act…”。
之后chat template追加工具定义，再跟整段JSON用户题面；user末尾是public_state而非回答要求。
因此“brief explain仍在”不等于呈现方式与9月相同。位置差异是事实，不能单独由距离推断因果。

输入原文：[9月D](september_D_rendered_prompt.txt)、[9月SP](september_SP_rendered_prompt.txt)、
[当前terminal](terminal_first_rendered_prompt.txt)。

## 2. 原生0/1向量语义没有向模型解释完整

当前题面直接给出：

```json
{"commitments": [[0, 1], [1, 0]]}
```

引擎定义是：每个数组位置对应action ID，1表示已承诺，0表示未承诺。
因此P0已承诺action1，P1已承诺action0；它不是“各玩家承诺了列表里的action ID”。
单行动玩家的`[0]`表示没有承诺，并非承诺action0。
当前system/user没有明确解释这个编码规则。

更容易混淆的是OFFER的`proposer_action`、`partner_action`：它们是接受后的**完整目标向量**，
包含原有承诺，不是新增承诺列表。max_changes约束的是相对当前状态新增的1的数量。

已实际出现的例子（题`8d11ec07596937b541e80851`、node58218、当前player1）：

```json
{
  "commitments": [[0, 1], [1, 0]],
  "legal_action_1": {
    "action": "OFFER",
    "partner_id": 0,
    "proposer_action": [1, 0],
    "partner_action": [1, 1]
  }
}
```

真实含义：player1不新增自己的承诺，要求player0新增action0，同时保留player0原有action1。
9月展示层会把它转换成`self_commitments=[]`、`partner_commitments=[Cedar]`，
并明确OFFER只列新增承诺；当前模型需要自己猜测并比较二进制向量。

引擎逻辑是正确的，缺口在对模型的解释。即使最终只返回索引，也必须正确理解每个索引
对应的后果。核对依据是原生`GameState.validate_offer`与冻结`Names.action`的差分转换。
本例的 [原请求](terminal_existing_commitments_request.json) 和
[人工审计展开](terminal_existing_commitments_expanded_audit.json) 已保留。
展开文件只用于人审，没有用于模型输入。

## 3. 工具从语义动作改成了单一整数选择

9月工具包括OFFER、ACCEPT、REJECT、INVESTIGATE等，并带有动作含义的description和具名参数。
当前只有`act(action_index)`，description为“Execute the indexed legal action”，具体语义移到JSON菜单。

这减少了输出结构复杂度，也把所有回答压成非常相似的token串。响应节点固定0=REJECT、1=ACCEPT；
后期几乎总选ACCEPT与此前日志相符。但是本次376种题面都验证了编号映射正确，不能把
采样偏好当作接口接反。使用索引本身不证明有缺陷；它与可读性、提示位置、任务变化共同发生。

9月自然语言题面明确区分规则、目标要求、偏好事实、时间线、当前决策和输出要求。
当前JSON还把同一goals、max_changes、round_robin等分别放在game和public_state里，
没有当前动作后果的文字展开，也没有9月“现在必须响应pending offer”等明确阶段提示。
重复字段实测一致，但会增加理解和对照负担。

## 4. 参考策略、先验与时序的说明也需要补全

这些是语义待明确项，不能由展示层自行换成9月科学设定：

- 当前`background_prior.weights`的实际规则是：对公开catalogue允许的每个joint world，
  乘上所有player-goal偏好对应的背景权重，再对允许支持归一化；它不是goal utility权重。
  prompt只有“Background weights apply jointly over this support”，没有给出明确构造说明。
  9月题面把偏好生成规则与utility分别说明。恢复可读性时应表述当前catalogue条件分布，
  不能直接复制9月的生成条件。
- 当前只说“Other players and you after this window follow the fixed reference policy”。
  模型没有得到该profile的策略表或明确的选择机制描述；9月B/P通常明确描述对手如何选择，
  SP则说明对手行为不保证最优。究竟是在已知公共对手机制下解题，还是通过RL学习固定但未知的
  对手，属于任务定义，需要明确；这本身不证明现有RL目标无效，也不能靠补一句话改变Oracle。
- JSON给了turn_index/round_robin，但没有像9月那样明确解释一次proposal及其response共同
  消耗一次proposal机会。窗口只注明proposals/responses都算受控decision，二者关系需要清楚。
- 当前focal标签按own-Q的所有1e-7内并列动作计正确；9月存在0.1容差和响应并列利他说明。
  不能为了恢复旧prompt而复制这些旧目标、容差或并列规则，造成题面与评分不一致。

## 5. 模板、生成、解析层的排除结果

- 两时期保存的实际prompt均以`<|im_start|>assistant\n`结束，没有预填`<tool_call>`或JSON回答。
  没有发现先生成解释、却因解析被删掉的证据。
- 当前checkpoint保存的chat_template与已有tokenizer配置逐字一致，hash见audit.json。
  9月保存的实际prompt外层格式一致；没有旧模板文件hash就不声称两时期Jinja文件逐字相同。
- 9月归档source与当前native生成都使用temperature=1、top_p=1、top_k=-1、
  repetition_penalty=1、max_tokens=1024、EOS停止；request没有强制tool-only模式。
  NativeStream也没有配置grammar/guided decoding。tool_choice=auto用于接口请求，
  原生生成实际接收的是rendered prompt IDs和SamplingParams。
- resolved_config里仍有通用max_length=512，但native入口显式传max_tokens=1024；
  实际存在1024-token输出，512不是本次20-token回答的截断来源。
- 当前Hermes解析保留content和工具调用。合法性检查只要求一次合法动作，两时期相关训练路径
  都没有把缺少解释列为失败；这并非已经隔离出的两时期差异原因。
- GPU/TP/vLLM运行环境有变化，本轮离线排查不能完全排除数值执行差异；这里只核对实际输入、
  原生传入参数和保存输出，不声称完成了新GPU对照推理。

## 建议的最小展示修复顺序

1. 把当前游戏事实转换成清楚的规则/状态/历史/当前决策/合法动作段落；显式展示已承诺项、
   offer新增项及接受后的状态，保留当前完整公共支持、先验、私有信息边界和终局目标。
2. 在user末尾恢复明确的“简短解释在前、一次工具调用在后、解释放在参数外”要求。
   这一步是落实既有输出要求，不需要给解释内容增加Oracle标签或长度奖励。
3. 优先让现有索引菜单具备可读动作描述。若进一步恢复具名工具，必须逐动作验证无损映射，
   并处理新prompt/source与已有checkpoint合同的关系。
4. 在正式运行记录解释存在率、解释tokens、纯工具调用率和截断率，避免再次只看平均长度。

这份排查没有把某一项确认为唯一根因，也没有自动修改训练protocol。
尤其是“公开参考策略如何对模型说明”需要与论文任务口径一起确定。

复现命令（仓库根目录，已有numpy环境）：

```bash
PYTHONPATH=. /opt/anaconda3/bin/python new/terminal_node_v6_training_960070/audit_prompt_interface.py
```
