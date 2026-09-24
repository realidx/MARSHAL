# ShapeFactory Lite：原生运行器，小规模配置

官方仓库完整源码保存在 `third_party/CollabSim`，固定 commit：
`08ed0ed1cefb2edf1ea389b20ba8355815a7c8d0`。
来自 GitHub 完整源码压缩包；对提交到 Git 的156个文件逐个校验SHA256，不含Git历史、`.DS_Store`和3张未提交的生成图。保留LICENSE、README、源码、提示、配置、文档和uv.lock。`third_party/CollabSim.source.json`记录逐文件SHA256；启动前核验。没有修改上游文件。

入口：`python -m examples.final_evaluation.shapefactory_lite`。不再导入旧的固定周期Factory、Lite v2引导提示或旧JSON规范化器。通过独立子进程在官方仓库目录调用 `python -m src.cli`，沿用原生提示组合、persona、对话历史、状态格式、解析、反馈、控制器和探测。

## 只调整规模及运行连接

- 2人（A/B）、2种形状，每人1个订单项。
- 两个互换专长配置 × private/dashboard，共4局；都是同一个模型控制全部席位。
- 原版经济参数、生产上限3、900秒真实时长、10秒触发、30秒生产延迟、并发上限6及终止条件不变。
- 原版配置每5次行动进行一次probe；原样保留，不启用额外collaboration提示。
- provider/model/api_base与输出目录按本地服务调整。模型temperature继承原生0。
- 不覆盖订单状态：上游初始化按shape_options的索引分配订单，并没有自动排除专长。通过配置形状顺序与专长，让双方自然获得非专长订单。此处按实际固定源码执行，不假装源码完全等于论文描述。

上游baseline引用的 `prompts/system_instructions.md` 在该版本中不存在，原生factory使用自己的默认system文本；未自行补写。上游return-format中的具体示例ID和形状也原样保留，没有针对模型表现改写。

## 使用

从MARSHAL根目录执行，Python环境需要满足上游`pyproject.toml`依赖（尤其PyYAML、litellm）。可以在`third_party/CollabSim`中用`uv sync --locked`创建其环境，再从根目录用该环境的Python运行本入口。

只生成4份配置并用原生schema检查，无模型请求：

```sh
python -m examples.final_evaluation.shapefactory_lite \
  --model YOUR_SERVED_MODEL \
  --base-url http://127.0.0.1:8000/v1 \
  --output runs/shapefactory_native_lite/preflight
```

实际运行时使用新输出目录并加`--run`。私有服务凭证通过`LITELLM_API_KEY`传入，不写入配置。四局依次执行，使用原生真实时钟，不承诺固定调用次数或准确60分钟完成。

产物：配置、manifest逐项before/after差异、每局原生日志、stdout日志及exit_code；四局原生CLI全部正常退出才写外层COMPLETE。它表示运行完成，不代表订单成功。旧`launch_shapefactory_local.py`仍是旧24局适配，不会自动切到本入口。

## 已检查与限制

- 156个已提交原生文件SHA256一致。
- 四配置通过原生schema校验。
- 测试确保prompts/protocol/probe/controls/action_space与对应原配置完全相同。
- 原生经济状态转换测试：非专长生产再履约，余额220。该测试直接验证经济动作，不冒充控制器真实30秒计时验收。
- 2026-09-24 已收到远端原生运行证据，见下节；本地测试本身不执行模型请求。
- 2人2形状是基础理解诊断，双方订单结构很简单；不能据此声称测量了丰富的私有信息推断。也不能与旧Lite v1/v2或论文规模的分数直接比较。

## 原生 Lite 实测后的测试改进（2026-09-24）

证据包：`new/shapefactory_native_lite_20260924`。重新读取原生 summary 得到：Q0 32K 完成 2/8 个订单、0/4 局双方完成、人均余额 188.75；旧 B/P 96K 完成 5/8、1/4、人均余额 194.375。旧 B/P 32K 中断运行不进入完整比较。两模型上下文配置不同，四局又只是两种身份映射乘可见性条件，不能据此宣称显著泛化提升。

- Slurm 启动器默认上下文从 32768 改为 98304（96K），沿用已成功运行的旧 B/P 服务设置；Q0、旧 B/P、新模型必须用相同服务配置重新比较。仍允许显式设置 `SHAPEFACTORY_MAX_MODEL_LEN`，但不能混用不同上限作正式比较。96K 不是永不溢出的保证，仍需审查请求长度、服务错误和 probe 超时。
- 游戏规模、规则、提示词、真实时间调度、probe、生产延迟、输出协议均不改。服务容量调整不是历史裁剪，不自动总结或删除历史。
- 每局结束后写 `evaluation_summary.json`，分别记录进程退出、结果是否齐全、原生 complete、实际订单完成、余额和成交。部分失败时不生成仅针对成功运行的 aggregate。
- 原生 `shapefactory_step` 的 complete 表示达到 target_steps；本次 target_steps=100000。它不代表订单是否履约，不能用它直接计算任务成功率。外层 COMPLETE 也只表示 CLI 运行结束。
- 旧日志可运行 `python -m examples.final_evaluation.shapefactory_native_summary PATH_TO_GAMES` 重新汇总。`infrastructure_valid` 只核查退出码和结果存在，不保证没有被内部处理的服务/probe 错误。

现阶段保留四局作基础能力诊断，不因为出现非零履约就立即扩规模。下一次首先统一 96K 配置；在同配置下重复这四局可检查运行波动，但重复不是新增独立任务。履约与余额并列报告：当前虽能完成部分订单，人均余额仍低于起始 200，不能把履约次数直接解释为经济协调效率改善。
