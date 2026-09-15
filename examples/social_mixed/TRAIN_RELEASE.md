# 训练冻结包 train-release-v4

本包整合 e1430bb SoC vLLM 0.28 适配、data_distribution_v1、多GPU显存配置和批处理优化。不是git分支切换，不包括模型/Conda环境/论文文件。

启动：`bash examples/social_mixed/start_training.sh h100-96 mixed`（纯 self-play 将末尾改为 `selfplay`）。也支持 h100-47 / h200-141。该命令使用既有 marshal-vllm09 环境，完成CPU依赖与包完整性检查后仅提交指定的一个作业。它不安装依赖，不直接启动HTTP服务。再次执行会再次提交作业。

固定 seed42、学习率1e-6、KL .01、clip .2、总生成token预算6553600/arm、每步软目标65536、B/P8重复、SP4重复、输出1024。mixed损失权重B/P/SP=.25/.25/.5，纯selfplay为1。题库BP442/248、SP144/48（train/validation），test不进入训练。快速验证为固定子集，不是全验证集。

作业内检查所选 profile 的 CUDA/NCCL，然后直接进入初始化、采样、优化、checkpoint。首步和终止边界保存，每10步验证/保存，保留最近两份完整checkpoint。初始化/训练日志在 runs/social_mixed/<arm>-seed42-<jobid>/，Slurm输出在runtime根目录。

H100-47/MIG无法通过可见性与NCCL检查时退出，不静默降级单卡。H200使用gpu分区三小时时限，提前请求保存，后续由用户以submit_soc.sh第三参数显式续训。

本地24项CPU测试和包独立解压核验通过不等于远程CUDA训练通过。当前base rollout已证实P和SP存在训练信号，B缩集正反馈仍弱；本次按用户决定不再以改题阻塞训练。

上传文件：/private/tmp/marshal-social-train-release-v4.tar.gz 和同名 .tar.sha256。始终解压到新目录，以免影响已有作业。

修复v1阻断：不再用通用RLVR set_max_steps换算自定义SocialPipeline的optimizer步数；三种microbatch下actor max_steps固定1000。新test_configuration实际构造三GPU×两实验配置及resume配置；start_training在提交前执行此检查。

单卡 H200：submit_soc.sh h200-141 申请 gpu:h200-141:1，actor TP=1/SP关闭、一个 vLLM replica、一个 reference worker，microbatch=2、full重算，训练状态分阶段卸载。H100保持双卡。单卡配置已通过本地真实配置构造；未在 H200 实测，不能保证显存峰值。原生续训要求 TP/world size 一致。
