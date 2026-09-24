# Hidden Profile 原生本地模型适配

入口：`examples.final_evaluation.hidden_profile_local`。直接调用固定版本 `third_party/CollabSim` 的原生CLI，不另写prompt、规则、动作解析器或任务执行器。

## 固定协议

- 官方baseline：3人A/B/C，角色planner/analyst/planner，原版persona与私有材料。
- 初始投票→讨论→最终投票；message/decide/do_nothing。
- 原生seed=42、temperature=0.2，原配置的步数、300秒讨论参数、探测与终止机制全部保留。不要把它标为temperature=0或固定次数行动评测。
- 不增加collaboration指导、解题提示、材料替换或答案轮换。
- 唯一运行差异：模型provider/name/api_base及日志目录。每次三个席位使用同一被测模型。
- 官方材料只有一个候选人案例，正确答案Candidate C。重复运行不是新题，不能把N次运行当成N个独立泛化案例。

## 准备与运行

从MARSHAL根目录，用满足官方pyproject.toml依赖的Python执行。可先在third_party/CollabSim中`uv sync --locked`，再从根目录用`third_party/CollabSim/.venv/bin/python`替代下面的python。

只生成配置和校验，不请求模型：

```sh
python -m examples.final_evaluation.hidden_profile_local \
  --model YOUR_SERVED_MODEL \
  --base-url http://127.0.0.1:8000/v1 \
  --checkpoint-id Q0 \
  --output runs/hidden_profile/q0-preflight
```

真实评测（使用新的输出目录）：

```sh
python -m examples.final_evaluation.hidden_profile_local \
  --model YOUR_SERVED_MODEL \
  --base-url http://127.0.0.1:8000/v1 \
  --checkpoint-id Q0 \
  --repeats 3 --run \
  --output runs/hidden_profile/q0-native
```

旧BP99、新D分别切换服务实际加载的模型，再用不同checkpoint-id和输出目录执行相同命令。checkpoint-id只是操作者提供的来源记录，脚本不能验证远端权重hash。服务需事先启动；此入口不加载或提交GPU模型任务。

凭证使用LITELLM_API_KEY，配置不写密钥。拒绝COLLABSIM_MODEL_*环境变量静默覆盖配置。重复运行沿用同一原生seed和材料，测量的是固定场景重跑，不承诺响应互相独立。

## 产物和解释

外层manifest记录来源版本、校验和、模型来源标签及配置逐项差异；每局目录保存原生事件、探测、指标等产物。每局另有stdout日志和exit_code。所有原生CLI成功退出后写COMPLETE，这不是正确投票或阶段完整性的认证，解读结果前仍须查最终投票是否实际发生。

优先检查初始→最终投票、私有信息是否分享、伙伴信息是否进入后续判断、非法动作及传输错误。最终投票正确不单独证明伙伴belief推断或B/P组合。保留原版指标，不另用新评分器重新定义任务成功。

已完成：逐文件原生完整性检查、原生schema校验、测试确保材料/提示/规则/角色/温度不变。尚未调用真实模型；远端完整依赖、探测服务请求和完整运行需在那里验收。
