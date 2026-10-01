# 4B 混训 / 纯 self-play：SoC 提交准备

本次准备完成统一训练代码、两个配置、上传包、恢复和 A100 固定对手评估入口；没有登录或操作服务器，没有执行真实 CUDA 训练。

- 入口：`training/social_mixed/run.py`，循环：`pipeline.py`，原生采样/损失：`workers.py`，游戏和分组：`core.py`。
- 复用 ROLL Megatron TP=2 训练、vLLM 参数同步、native checkpoint。没有单独 B/P 预训练阶段。
- 主实验 loss 权重 B=.25 / P=.25 / self-play=.50；对照只有 self-play。
- 4B-Instruct-2507，BF16 全参，microbatch=1；固定 LR=1e-6，clip=.2，KL=.01，单 epoch。
- 每次回复 1024，context 4096；temperature=1 / top_p=1，直接保存 sampled-token log-probs。真实生成 IDs 进入训练，HTTP 数据只用于评估。
- 每臂目标 6,553,600 个进入训练的输出 tokens；每次至少 65,536，整组采完后更新，记录超出量。不是先停在 30 步再人工决定是否继续。
- 第一次更新、每 10 次更新、结束/截止信号时保存。保留最近两个完整 native 恢复点及全部日志；可提高 `SOCIAL_KEEP_CHECKPOINTS`。
- 每 10 步固定小验证只记录结果；固定 base 对手的完整验证可在 A100 独立执行。

准备的数据：训练 B152/P128/self-play60；验证 B33/P32/self-play12；不含 test。Self-play 仍来自现有少量模板，不能声称 60 个独立策略场景。无收敛或模型成功率筛选。

失败处理：B/P 无额外 retry、无 length penalty。Self-play 每次无效/截断记 -.1，至多一次 retry。失败局 terminal utility 保持 null；含不完整局的 reset/player 分组禁用 outcome advantage，仅保留实际协议回报的组内信号。这与给失败局填零收益不同，两臂采用同一规则。

本地验证：

- 19 项 CPU 单元/接口检查通过，包括 72 个真实初始局随机合法回放、独立终局收益复算、调查私有性、重试、分组、混训权重。
- 使用真实 TensorDict/DataProto 及 PyTorch autograd 检查 token 原值、因果 mask、梯度方向、microbatch 累积；native worker 的 token/log-prob 边界用模拟引擎验证。
- 两个 Hydra/dacite 配置实际解析通过。
- 现有 4B tokenizer 检查 1182 个输入，最大 prompt=1894，均满足 4096-1024。
- 上传包曾在独立临时目录解压，通过来源校验和输入回放，未依赖工作区的 ignored 数据文件。
- Bash 语法、Python 编译通过。GPU 显存峰值、Megatron CUDA 更新、分布式保存恢复与 HF 导出尚未在本次远程环境实测；不能承诺绝不报错。

最终上传包 `/private/tmp/marshal-social-mixed-v1.tar.gz`，578 个来源文件，约 1.46 MiB。
SHA256：`999f31330ba8dd553520f6132b9b2a65dbcc98145505e712e2303b9338cf97b4`。

上传、两个 sbatch、续跑、导出和 A100 评估命令见 `examples/social_mixed/README.md`。
