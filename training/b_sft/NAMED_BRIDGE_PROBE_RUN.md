# 具名 B/P、输出接口与短教学对照

本轮修复预检后的最终题包：`new/local_data/social_runs/bp_named_bridge_probe_v3/`。`bp_named_bridge_draft_*` 和 `bp_named_bridge_probe_v1` 是本地准备产物，不运行它们。

## 这轮修复的实际问题

正式游戏的 `Observation.to_agent_dict()` / `vllm_policy.py` 已使用具名新增承诺。无目录小测的 `prepare_no_catalogue_probe.view()` 却直接导出了 `public_game()` 和 `public_state()`，同时把原生完整承诺向量放进合法动作和提交 schema。它绕过了具名接口，重新引入 action_id / 0-1 bookkeeping；这是教学题面导出的回退，不应全部归因于模型能力。

新增 `social_named_probe.py`：用 Alex/Blair 等玩家名、Orchard/Harbor 等目标名、Cedar/Maple 等承诺名。OFFER 采用 `self_commitments` / `partner_commitments` **新增承诺**语义；接受后保留旧承诺，内部无损映射回原生状态与动作。模型看不到 action_id、完整 0/1 向量、目录、teacher 概率或动作价值。压缩重复状态，只保留一份目标规则、当前承诺与逐事件历史，明确每个动作的主人、setup/voluntary 来源、当前响应或提案阶段、剩余机会以及本人私有结果。

真实导出题面可直接审阅：`new/local_data/social_runs/bp_named_bridge_probe_v3/prompt_examples.md`。完整 API 请求在该目录 `bundle/requests.jsonl`，评分标签和映射在本地 `tasks.jsonl`，不在上传包中。教学对照中故意提供的已解例题及其答案属于模型可见教学材料；不能把它们当作被测题的盲测标签。

## 全集错误与输出不一致

上一轮 129 次全集提交的逐条分类已保存到 `bp_no_catalogue_remote_r1/full_set_audit.json`：82 次集合错误，14 次集合正确但 favored 错误，3 次集合内容符合被问题但提交了错误目标，30 次完整正确。82/129 的全集不该保留，99/129 的完整答案错误；不是所有全集都错误。

继续使用集合 + favored 的完整答案奖励，不增加“只要全集就扣分”的惩罚，也不从 reasoning 猜测正确答案后替换工具结果。短例成对展示：无关行为保留全集、自愿 ACCEPT 排除 avoid、自愿 REJECT 只留 avoid、真实私有揭示留下单元素、正确旧 belief 不因新增无关行为而丢失。重点检验是否用证据改变答案，防止换成无脑缩集合。

文字与工具不一致是已经观察到的现象；目前没有证据说明它必然由 tool call 架构导致。可能涉及字段含义、枚举模板惯性或输出阶段没有保持结论。原始 HTTP 日志也不包含服务端解析前的 token 流，因此不能只凭它完全排除解析环节的影响。本轮以相同题面/答案规则做 8 题的三个对照：

- `separate_tool`：普通文字解释，随后 native tool call。
- `joint_tool`：同一 tool call 内同时提交 reasoning 与 answer。
- `text`：不提供工具，同一纯文本 JSON 内提交 reasoning 与 answer。

joint tool 与 text 的答案结构相同；separate 与 joint 检验解释放置位置，joint 与 text 检验工具/文本提交形式。保持普通错误、格式错误、接口错误独立统计。结果出来以前不宣称移除 tool call 能解决问题。

## 新覆盖与核验

- 51 个基础检查点，包含上一轮 26 题的具名重呈现、3 个两人私有真值短题、14 个 qualitative P 题、8 个主动 investigate 链及反例检查点。
- likely 组只有两人、三个目标、一个未知偏好，内部保留完整 want/neutral/avoid 支持。同一物理局面只改变定性判断，覆盖 very likely、almost certain、likely、unlikely、impossible、certain、possible，每项两种措辞。certain 项同步从 unresolved 移到 known，避免题面自相矛盾。
- 12 个定性检查点通过宽区间 LP 核验；2 个仅有 possible 信息的检查点不能稳定确定动作，保留为诊断但不给隐藏单点最优标签，语义奖励为 None。宽区间是版本化的敏感性假设，不宣称英文词汇具有普适精确数值定义。数字区间不进入模型输入，未扩展成一般多回合定性 solver。
- investigate 正例是两人、三个目标、每人两个承诺、一个隐藏偏好。正常剩余轮转为 Alex → Blair → Alex。开始前 Blair 的一次 PASS 是明确独立于偏好的合法 setup，之后全部行为由同一固定 teacher 自主选择。查询、伙伴行动和下次自己的报价全部进入求解树，不使用末轮替代值。
- 该根节点 12 个合法动作中，唯一可接受动作是查询隐藏的 Orchard 偏好；按默认自身/利他容差各 0.1 仍成立。查询与最佳不查动作的自身期望收益均为 2/3，但伙伴收益从 1/3 提高到 2/3。它证明的是约定利他层上的信息价值，不是严格提高自身收益的正例。
- 私有答案为 want/neutral 时后续选择 Orchard；avoid 时选择 Library。保留一个每个真值下均有正概率的伙伴 PASS 路径作为检查点，明确标为 voluntary，不把它强制为策略。完整根树涵盖所有其他合法行为。
- 同一公共历史下的“去掉自己的答案”消融：自身收益仍为约 0.6471，伙伴收益从约 0.6765 降至 0.3235，差约 0.3529。后验不同于根先验，因为伙伴的自愿 PASS 也提供信息；报告和评分不假装其仍等权。这个消融固定末轮伙伴响应，重新优化不知道答案时的最佳动作，是独立于根动作比较的信息使用证据。
- 同结构末轮题中调查不再可接受；根节点另外两个已知偏好也作为合法错误查询目标保留。仍缺“多个隐藏目标中只有一个相关”的对照，以及调查严格提高自身收益的短正例；不阻塞已核验的教学链。
- 11 个有解释、经 solver 核验答案的短教学例，覆盖行为形成/维持、真值、favored 更新、目标达成/利他和 investigate。对照题保留同样重命名但不给例题的控制组；教学组每次只给 2–3 个相关例题。这里只测短教学能否立即帮助模型，不是参数训练，不声称独立结构泛化。

总计 91 个请求条件，每条件采样 8 次，即 **728 次正式采样 + 6 次接口预检**。被测题的标签、solver、数值证书均留本地；上传包只含请求与标准库采样脚本。固定基础模型，无 optimizer、无训练。后续训练仍按每 10 步分层验证的约定，分别跟踪集合错误、favored、推理与答案一致性和真正有价值的 P 行动。

## 本地上传

```bash
cd /Users/bruce/MARSHAL
scp -i /Users/bruce/.ssh/id_rsa_dgx2 -P 2201 \
  new/local_data/social_runs/bp_named_bridge_probe_v3/visible_probe.tar.gz \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/outputs/bp_named_bridge_probe_r2.tar.gz
```

## 服务器执行

复用上一轮 8000–8007 的 `social-base` 服务，不重启、不关闭服务。脚本先校验文件与全部 endpoint，再并行预检 B/P 的三种输出接口（6 个请求，最多同时使用 6 个服务）；若请求或响应封装失败会停止。模型格式错误照常记录，不阻止正式测试。正式阶段使用全部 8 个服务，日志记录 worker 与 endpoint。

```bash
cd /raid/chenjiahao/mas
mkdir -p outputs/bp_named_bridge_probe_r2
tar -xzf outputs/bp_named_bridge_probe_r2.tar.gz -C outputs/bp_named_bridge_probe_r2
nohup bash outputs/bp_named_bridge_probe_r2/bundle/run_probe.sh \
  outputs/bp_named_bridge_probe_r2/results \
  > outputs/bp_named_bridge_probe_r2/run.log 2>&1 < /dev/null &
```

```bash
tail -f /raid/chenjiahao/mas/outputs/bp_named_bridge_probe_r2/run.log
```

默认结果目录必须不存在；重跑换新目录。脚本 Complete 表示采样完成，不代表答题正确。用户运行完成后，助手下载 `outputs/bp_named_bridge_probe_r2/results/`，按本地同题包分别评分和阅读三个接口的解释。

## 本地重建与评分

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.prepare_named_bridge_probe \
  --out new/local_data/social_runs/bp_named_bridge_rebuild
```

下载以后评分（这里给出预定本地存放路径，尚未产生新远端结果）：

```bash
/private/tmp/social_native_tools_venv/bin/python -m training.b_sft.prepare_named_bridge_probe \
  --data new/local_data/social_runs/bp_named_bridge_probe_v3 \
  --score-samples new/local_data/social_runs/bp_named_bridge_remote_r2/probe/samples.jsonl \
  --out new/local_data/social_runs/bp_named_bridge_remote_r2/local_scoring
```

scorer 校验请求与采样脚本哈希、任务 ID、采样索引；按 B/P、能力、输出接口、名称变体和教学条件分别统计。格式失败不修复，含糊信息题不强制计错，不以案例复用后的成绩宣称泛化。本轮助手没有执行上述上传或服务器命令。

## r1 预检中止与 r2 修复

r1 的 6 条原始响应已下载到 `new/local_data/social_runs/bp_named_bridge_preflight_remote_r1/`。6 条 HTTP 请求全部完成，没有 token 截断；3 条符合提交协议，另外 3 条是模型输出格式失败：

- B joint_tool：文本含 `<tool_call>`，但其中 JSON 少了一个闭合大括号，不能解析；API `tool_calls` 为空。不能凭此归咎于服务端 parser。
- B text：`answer` 写成 judgments 列表，缺少对象层。
- P text：`answer` 写成字符串，动作字段散落到外层。

本地严格评分为 1 条正确、2 条合法但错误、3 条格式失败；这仅涉及 2 个题目、各接口一次采样，不能据此判断接口优劣或可训练性。逐条结果见 `local_diagnosis.json`。

原脚本错误地要求预检全部格式正确，导致正式测试未启动。旧 wrapper 指定 8007（物理 GPU 2）执行全部预检，所以该阶段仅 GPU 2 活跃。新版改为服务/响应封装可用性门槛，格式失败与截断保留作测量结果；不修复答案、不重试，语义评分规则不变。网络错误、HTTP 错误和损坏的 API 响应仍中止预检。预检使用所有配置的 endpoint 并行领取 6 个任务；正式 728 条使用 8 个 endpoint。summary 另记录每个 worker 的样本数、基础设施失败数和非协议提交数。

使用独立远端目录 r2 保留 r1 失败记录。v3 的请求题面和本地标签与 v2 逐字节相同，只更新 sampler、wrapper 和对应 manifest。无需重启 vLLM。
