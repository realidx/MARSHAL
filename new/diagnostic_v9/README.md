# v9：小结构基础检查＋保留难题对照

本版22题、88次调用，保留B/O/P_gold/P_model。12道新基础题使用2–3个二元目标，不再把六目标规划放在“直接反馈”基础层；另保留10道v8难题，避免用简单控制题取代真正的行为推断挑战。没有使用模型输赢选题。

| 层次 | 基础题 | 保留难题 |
|---|---:|---:|
| 直接反馈 | 6 | 0 |
| 一步排除 | 3 | 3 |
| 一步有歧义 | 3 | 3 |
| 多步更新 | 0 | 4 |

repair-sensitive 9题、action-control 13题。基础题中3道直接反馈题有经过实际reward容差核验的不相交正确动作集合；其余基础题用于规则、集合表达及简单推断检查。多步仍为control，不把它作为belief→行动迁移的证据。分别报告basic/challenge、四层及repair-sensitive/control，整体不是唯一主结论。

## 实质修改

- 新增两目标小场景，以及三目标取舍场景：同一高收益方案满足两个目标，另有较低收益备选。未改原生收益、合法动作或评分规则。
- 直接反馈来自实际合法的自身INVESTIGATE转移。该查询作为自身已执行动作的干预，不要求它是teacher最优动作，也不把它当伙伴偏好的行为证据。原生查询结果进入可见偏好表；没有虚构伙伴历史。
- B补充通用集合语义：possible_preferences不是枚举所有允许标签；真实调查只留下揭露值；解释和提交应表达同一判断。保留先解释再工具提交，不改评分为宽松匹配。
- P仍直接调用标准训练渲染器，不提供历史或数字posterior。
- 循环或无法认证的teacher实例排除；每题重验定性belief充分性、reward容差接受集合、移除历史后的continuation、全部合法动作评分。`CASE_AUDIT.md`保存审计用证据链和反事实集合，不给模型看。

不能将“结构更小”宣称为模型已能解决。本地通过的是规则和实现检查，尚无新模型结果。

## 运行

```bash
python -m unittest new.diagnostic_v9.test_suite
python -m new.diagnostic_v9.experiment \
  --base-url http://localhost:8000/v1 --model MODEL \
  --checkpoint-hash HASH --output runs/diagnostic_v9/MODEL \
  --max-tokens 4096 --concurrency 4 --repeats 1 --seed 42
```

使用相同batch-invariant服务配置。无需先跑七个模型；可以先跑Q0与待比较checkpoint，查看基础层输出是否按预期测到了理解与集合表达。旧版本不覆盖。
