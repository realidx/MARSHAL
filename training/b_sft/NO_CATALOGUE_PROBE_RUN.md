# 不公开偏好目录的服务器小测

本轮采用 `new/local_data/social_runs/bp_no_catalogue_probe_v4/`。v1–v3 是本地准备过程的中间产物，运行只用 v4。

用户已明确要求先隐藏目录并重算标签，再采样。新题面没有 `public_type_catalogues`、完整 type rows 或 joint-world 列表；仅给已公开具体偏好、自身偏好、本人私有调查结果、公共历史、生成规则和 P 所需当前 belief。生成规则是教学阶段的等可能独立抽样并拒绝非法配置（每玩家至少一个 want、每 goal 至少一个非 neutral）；不是修改 self-play 生成分布。不能一边不告诉模型排除理由、一边按原来的任意小目录给标签。

26 题（18 B、8 P），每题 8 次，temperature 0.8、1024 总输出 token、无 retry；正式 208 次，另有 2 次接口预检，无参数更新。17 题的内部支持比旧目录扩大。全部标签重新求解、原生重放核验、gold 原生工具提交得分 1；最长树 29 节点。删除目录后一个旧 favored 更新题变成维持，任务类别也已修正。新补完整三值支持下的 favored 正例，以及双隐藏偏好下 favored 消失/维持。三个原新测试加一个联合约束测试均通过；已有私有机制和课程相关回归已通过。

P 直接给当前已知偏好和剩余不确定项，声明是生成分布条件于当前已知事实的 belief；不用隐含精确权重，也不要求从旧历史重新做 B。该渲染仅用于此批 setup-only P 题，不能宣称已实现一般 likely 自然语言多回合输入。

上传包只有模型可见请求、独立采样脚本、启动/运行脚本及校验 manifest。solver、gold、逐动作价值保留本地；服务器本轮无需更新完整训练仓库。

## 本机上传

```bash
cd /Users/bruce/MARSHAL
scp -i /Users/bruce/.ssh/id_rsa_dgx2 -P 2201 \
  new/local_data/social_runs/bp_no_catalogue_probe_v4/visible_probe.tar.gz \
  chenjiahao@36.102.215.18:/raid/chenjiahao/mas/outputs/bp_no_catalogue_probe_r1.tar.gz
```

## 服务器解包并启动物理 GPU 2

```bash
cd /raid/chenjiahao/mas
mkdir -p outputs/bp_no_catalogue_probe_r1
tar -xzf outputs/bp_no_catalogue_probe_r1.tar.gz -C outputs/bp_no_catalogue_probe_r1
bash outputs/bp_no_catalogue_probe_r1/bundle/start_probe_gpu2.sh
```

沿用已验证的 mas Python、Qwen3-4B-Instruct-2507、vLLM 0.8.5 V0/XFORMERS/Hermes、16384 context、单请求、0.35 显存比例。新服务绑定物理 GPU 2 / 端口 8007，等待 `/v1/models` 就绪；不关闭其他服务。端口已占用则停止启动并提示检查，不擅自杀进程。

原服务记录为物理 GPU 0、1、3、4、5、6、7 对应端口 8000–8006。不要把端口后缀当作物理 GPU 编号。启动日志：`outputs/bp_no_catalogue_probe_r1/logs/vllm_gpu2_port8007.log`。

## 服务器运行测试

```bash
cd /raid/chenjiahao/mas
nohup bash outputs/bp_no_catalogue_probe_r1/bundle/run_no_catalogue_probe.sh \
  outputs/bp_no_catalogue_probe_r1/results \
  > outputs/bp_no_catalogue_probe_r1/run.log 2>&1 < /dev/null &
```

```bash
tail -f /raid/chenjiahao/mas/outputs/bp_no_catalogue_probe_r1/run.log
```

脚本先校验包、检查 8 个 endpoint 的 social-base，再在 8007 做 B/P 各一次原生调用预检，之后用全部 8 个服务采样。预检只检查原生提交是否完整，不把答案正确作为运行门槛。旧 endpoint 不可用会明确报错，不静默少用卡；可显式传入可用 endpoint 列表，例如仅新服务：

```bash
bash outputs/bp_no_catalogue_probe_r1/bundle/run_no_catalogue_probe.sh \
  outputs/bp_no_catalogue_probe_r1/results_single \
  http://127.0.0.1:8007/v1
```

结果目录必须不存在，重跑使用新目录。运行完成后告知助手，由助手下载 `outputs/bp_no_catalogue_probe_r1/results/`，在本地用同包 `tasks.jsonl` 评分。日志显示 Complete 表示采集结束，不表示语义全对；完整 raw_message、工具调用、usage、finish_reason 和失败信息均保留。

## 分析目标

- 分能力看语义正确率、格式错误、每题 8 次的成功分布，不只看总体成绩。
- 阅读 B 简短解释：是否用行为区分偏好、是否把有可能误判成确定、是否维持/改变 favored、是否遵守生成约束导致的联合关系。
- 对照未收到私有答案者与调查者，检查是否混淆“自己知道”和“其他玩家知道”。
- 结合 reasoning 决定后续 likely 表述与联合/私有信息题面的修改；本轮不是已经证明这些接口正确或可迁移。
- 继续检查默认全集、want、PASS、INVESTIGATE 等模式，但不把基础模型当前偏置解释成 GRPO 不可训练。

操作仍由用户执行；助手本轮没有启动服务器、上传或远程采样。
