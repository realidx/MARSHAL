# 三人 H2 全批本地运行记录

用户2026-10-23要求“在本地先尝试跑一下”。这是已关闭研究版本
`three-player-complexity-study-v1` 的新运行记录，不覆盖其快照，不修改旧100或生产v8。

## 输入与运行合同

- 全部33个预先冻结的H2父游戏；不按结果筛选，不复用旧reference作为候选。
- 每人1承诺选项、2个分属不同玩家的隐藏偏好、9个world、2RR、调查1、提出即扣报价额度1。
- 原生terminal树、平局安全缩减、惯性BR后可选联合候选；完整私人信息BR/局部支持/response社会平局认证。
- 当前节点Q/S保持研究v1定义：逐条遗漏自己的调查答案或公共历史；保留基础事实；
  对手reference固定，自己重新优化到terminal。遗漏后剩余平局均匀；零counterfactual节点S缺失，不赋0。
- 本地单worker，数值库线程各1；macOS不施加Linux内存限制，`memory_gb=0`明确记录。
- 本地预算覆盖：候选求解120秒、认证180秒、Q/S 300秒、整局硬限720秒。
  构树/缩减各180秒、节点上限600000、最大512 sweeps、联合求解400 evaluations、修复最多8轮，
  epsilon=1e-8、tie tolerance=1e-9保持原设置。完整解析参数见实际snapshot。
- Python3.12.2、NumPy1.26.4、SciPy1.12.0；CPU验证，无模型、prompt、D或训练运行。

输入：[H2.jsonl](../../new/remote_three_player_bundle_20261023/final/three_player_remote_v1/data/H2.jsonl)，
SHA256 `ea55ccdf4e205cda88d5957c265e484d367e13b72c6d3f6ae67c424afa5a77f4`。
源文件464项通过原注册hash检查；注册SHA256
`d561f5f111c5182872ec4d718411ffe80b531b20953edf3bea85262cda0122c8`。

实际命令：

```bash
python -u -m new.three_player_complexity_v1_20261023.remote run \
  --jobs new/remote_three_player_bundle_20261023/final/three_player_remote_v1/data/H2.jsonl \
  --output new/three_player_complexity_v1_20261023/local_H2_33_v1 \
  --workers 1 --solve-seconds 120 --audit-seconds 180 \
  --metric-seconds 300 --case-seconds 720 --memory-gb 0
```

实际[完整pipeline_snapshot.json](../../new/three_player_complexity_v1_20261023/local_H2_33_v1/pipeline_snapshot.json)
包含CLI、解析配置、输入与源文件hash及环境；每个execution保存request/progress/result/log/reference。

## 状态

首次整批已完成：33次尝试、31局认证并测量，原46/76缺失，不计零信号。
较大预算重试、独立重载与信号诊断见[2026-10-24后续记录](LOCAL_THREE_PLAYER_FOLLOWUP_20261024.md)。
远端尚未执行；旧100、第25局挑战身份、生产active v8均保持原样。

## 前14次尝试的冻结回顾

用户在后台继续执行时要求先回顾前14局。以下仅包含研究index0—13，对应原池
3、7、10、12、17、19、21、22、27、28、34、35、43、46；后续进度不混入此表。
13局完整终局数值认证并测量，原46局没有可认证候选、Q/S缺失。本批保存后独立重载尚未执行。
认证为声明信念约定下的own-utility epsilon-Nash与局部支持/回应平局检查，不声称唯一或形式化序贯均衡。

对照严格使用同一组13个已测原游戏，单位均为父游戏数，非节点数：

| 指标 | 旧基线 | H2 |
|---|---:|---:|
| 任一种单条遗漏S>0 | 2 | 5 |
| 调查答案S>0 | 2 | 3 |
| 公共历史S>0 | 2 | 2 |
| 参考策略实际可达路径上有S>0 | 2 | 2 |
| 存在调查严格优于其他行动的节点 | 1 | 3 |

H2调查答案正S来自原3/7/43，历史正S来自22/35；参考路径上正S来自7/22。
旧基线正S来自17/35；扩展后17无正S、35失去调查答案S但仍有历史S。
8个已测游戏未发现单条遗漏正S：10、12、17、19、21、27、28、34。
这里的“无正S”不是无Q差异、不是无策略价值，也不代表已证明联合遗漏无影响。

### 暴露的问题与下一步

1. **候选搜索不完备。** 原34的BR循环由联合候选解决；原46构树成功，但BR及当前联合候选均未通过。
   联合残差接近零的若干候选仍有至少约1/9的局部收益偏离，拒绝是正确行为。
   46约53秒就返回`joint_unavailable`，不是720秒硬限或内存失败；当前候选路径耗尽与单纯超时需分开。
   后续应先诊断活跃支持/候选初始化与遗留偏离，不能把“再加时间”当作已验证的修复。
2. **信息价值没有单调增加。** 增加隐藏world、改变信息结构，以及可能选择不同reference均会改变Q/S。
   不能只汇报新增加的3/7/43，而忽略17/35原有调查答案S消失；尚未拆分机制和profile的影响。
3. **覆盖增加主要不等于参考路径覆盖增加。** 5个正S游戏中仅2个在reference实际路径上有正S。
   偏离路径本身可有slice价值，不应据此删除；reference路径也不是目标模型self-play路径。
   需要结合后续模型D与实际采样，才能判断是否形成有效训练信号。
4. **调查动作优势与答案信息收益不能混称。** 原35有2个调查严格优势节点，但调查答案S全为0。
   这可能涉及公开调查行为的信号、其他信息冗余或reference结构，当前未诊断归因；
   不能仅凭调查Q优势就宣称私人答案带来收益。

当前优先级：完成冻结整批覆盖和独立重载；定位46；解释上述信号消失/冗余案例，再决定是否扩大H3/A2H2。
新正S见证的独立LP/平局稳健性复核尚未做；既有预定小样LP通过不自动覆盖本批新节点。
不据这14次尝试改题、放宽认证或激活训练；模型D仍未测。

冻结证据：[REVIEW.json](../../new/three_player_complexity_v1_20261023/local_H2_first14_review_v1/REVIEW.json)、
[独立snapshot](../../new/three_player_complexity_v1_20261023/local_H2_first14_review_v1/pipeline_snapshot.json)、
[原始前14条结果副本](../../new/three_player_complexity_v1_20261023/local_H2_first14_review_v1/first14_results.json)。
报告脚本及每条不可变case结果的hash均已记录，后续后台进度不改变这次回顾。
