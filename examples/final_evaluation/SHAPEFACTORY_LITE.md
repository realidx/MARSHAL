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
- 尚未调用模型或验收远端完整依赖与900秒执行。
- 2人2形状是基础理解诊断，双方订单结构很简单；不能据此声称测量了丰富的私有信息推断。也不能与旧Lite v1/v2或论文规模的分数直接比较。
