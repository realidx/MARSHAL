# 逐题配置审查

历史首次/末次均为一次8回答曝光，不是固定Q0正确率；各题曝光范围不等。有效组计数来自原学习审计，不代表优化因果收益。

|ID|域/操作|历史曝光|有效组|首次→末次正确/8|标签或接受动作数|
|---|---|---:|---:|---|---|
|02cde86e8e815de10e44|P/result_use|6|5|2→7|{"acceptable_actions": 3}|
|254f16a04a517c3e2f51|P/information|53|51|3→7|{"acceptable_actions": 1}|
|2e823c8a4e5d931f8f2d|P/result_use|6|5|1→8|{"acceptable_actions": 2}|
|49f3fa0b572bcd3eb992|P/history_planning|6|6|2→6|{"acceptable_actions": 2}|
|74407320050e50ff134a|P/complete|16|14|2→8|{"acceptable_actions": 1}|
|a3394ad3c9ba94e5c651|P/complete|15|8|3→7|{"acceptable_actions": 1}|
|ccfdaad025312b83044f|P/complete|11|8|3→7|{"acceptable_actions": 1}|
|daf34a5dbee3aa87bfcc|P/complete|16|10|1→8|{"acceptable_actions": 1}|
|e3126ec00963b34311ed-O|O/action|9|9|3→5|{"acceptable_actions": 2}|
|fdfe18407b6a6b382606-O|O/action|8|2|5→8|{"acceptable_actions": 6}|
|3a799590f157770c74eb-O|O/action|9|7|5→7|{"acceptable_actions": 3}|
|1f64ed25993e73276ecf-O|O/action|9|8|4→4|{"acceptable_actions": 2}|
|c119e0ae7c41f47b394c-O|O/action|9|9|3→4|{"acceptable_actions": 5}|
|5e9d1a1118542341eb39-O|O/action|9|8|2→6|{"acceptable_actions": 5}|
|c446e23c1db418492227-O|O/action|9|4|5→8|{"acceptable_actions": 3}|
|55815e1977097e8344fc-O|O/action|9|9|3→6|{"acceptable_actions": 2}|
|6723c813877e1f9c28c8-B|B/insufficient|6|3|2→6|{"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}|
|ebeb09c155c1d096d5f2-B|B/insufficient|31|13|3→6|{"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}|
|c6be10e40e97777214f6|B/exclude|5|4|0→2|{"possible_preferences": ["want", "neutral"], "favored": "want"}|
|a61c495e88207d9ff764|B/exclude|3|3|1→2|{"possible_preferences": ["neutral", "avoid"], "favored": "avoid"}|
|f89382b9233063e37cc1|B/favored|3|3|2→2|{"possible_preferences": ["want", "neutral", "avoid"], "favored": "want"}|
|68798975a57a43ce9c11|B/favored|3|3|4→1|{"possible_preferences": ["want", "neutral", "avoid"], "favored": "avoid"}|
|c119e0ae7c41f47b394c-B|B/revealed|3|2|5→8|{"possible_preferences": ["neutral"], "favored": "neutral"}|
|55815e1977097e8344fc-B|B/revealed|2|2|5→4|{"possible_preferences": ["want"], "favored": "want"}|

## 人工检查说明

- c6be：三方最终提议，在已绑定第三方承诺下，由伙伴主动提出一组承诺，推断排除avoid；保留完整三方约束。不是直读调查结果。
- a61c：终局REJECT，需结合另一个未公开目标的共同收益排除want，保留neutral/avoid。
- f893：相近的双目标终局ACCEPT，保留三个可能但偏向want；和a61c的背景分布也不同，不称单变量对照。
- 6879：接受实现已知目标的提议并未排除未知目标的三种偏好；非均匀公开背景使avoid领先。此题练习避免将接受行为过度解读；不是新行为强行改变倾向。历史4/8→1/8，明确不是已证明可持续学习的题。
- 6723/ebeb：没有相关证据时保留全部可能和undetermined；不是全库统一答案。
- c119/55815：可见私人调查明确揭示被问目标为neutral/want；具有对应O场景。
- 旧update三题的previous belief来自原接口，三个最终标签均与其不同；历史请求不被静默重写。

## 候选淘汰

- 1f432…O虽能组成binary must-change，但历史18次曝光、144回答无正确，0有效组；未纳入。
- 没有为了凑齐binary对照选择同样长期全错的b578/9906等题。
- B directional/subset仍是弱学习证据；新库解决答案单一，不能宣称已经解决困难B的可学习性。

## 冻结内容

全部24题原始请求在 PROMPTS.md；正确/错误历史样本在 examples.jsonl。P八题与旧24版逐字段保留。关系清单在relations.jsonl。
