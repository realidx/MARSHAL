# B/P 双 A100：步骤 1 完成，步骤 2 待远程执行

数据、配置、两步更新/恢复预检代码和上传包已准备；本地未执行 CUDA 训练，也未连接服务器。

## 本地证据

- `examples/social_bp/data_two_a100_v1`：411 题，train 280（B 152/P 128）、validation 67、test 64。
- train 来源：原题 247、非 L0 bridge 30、简化 L0 assisted 3；新增 validation L0 assisted 3。teacher 输入和答案沿用已核验数据；新合并题另作 solver/收益核验，旧 test 输入与标签不变。
- 每步 B 2 L0 + 3 bridge + 3 原行为题，P 8；16×8=128 回答，固定 30 步 ID schedule。
- 使用 `/private/tmp/bp-pilot-tokenizer` 检查全部 411 题，最长输入 1894 tokens，2048 输入预算足够。远程 export 仍校验 tokenizer template 哈希及原生工具 round-trip。
- 本地 32 项测试通过：`test_bp_two_gpu.py`、`test_social_bp_training.py`、`test_b_l0_isolated.py`、`test_b_response_bridges.py`。
- 正式、两步预检、恢复配置均通过真实 Hydra + RLVRConfig 解析；序列总长 3072，actor/infer/reference 各两个 worker，128 回答对应一次实际 optimizer update。
- 启动 shell 语法通过；roll 与 training/b_sft 共 369 个 Python 文件 AST 解析通过。
- 上传包 `/private/tmp/marshal-bp-two-a100-v1`：513 文件，8,487,825 bytes，逐文件 SHA256；不含模型和历史运行结果。

## 链路修正

- 两卡轮流承担采样、reference log-probs、actor 更新；vLLM graphs + sleep，ZeRO-2 actor 阶段切换卸载。
- actor/ref 显式映射当前 worker GPU，避免 provider 中 balanced/default cuda:0 导致放错卡；修复 HF offload 恢复时字符串设备被拼成 cuda:cuda:1。
- 新包每题每次回答显式设 seed，传至 SamplingParams；seed 纳入采样参数比较。
- preflight 读取真实 actor、reference、vLLM 模型张量的抽样指纹，核对 optimizer 计数和更新后生成。
- checkpoint-0（完成一次更新）可保存；保存/恢复 actor RNG，兼容 torch 2.6 的 RNG 文件读取，最终同步前卸载 actor。
- 独立本地 Ray 入口，不连接旧 Ray、不关闭其他进程。

## 仍需远程证明

显存峰值、训练依赖版本/API 兼容、实际参数变化、vLLM sleep/唤醒/权重同步、optimizer 与 checkpoint 恢复均尚未实测。预检两步加一次恢复续步，384 个训练回答 + 48 个 canary 回答，共 432；canary 不充当 held-out 评估。

成功标志是远程根目录 `PREFLIGHT_COMPLETE.json`。失败则下载同目录的日志与证据分析，不据此修改任务奖励/答案预算。正式 30 步和 self-play 均未启动。

执行说明：`examples/social_bp/TWO_A100_PREFLIGHT.md`。
