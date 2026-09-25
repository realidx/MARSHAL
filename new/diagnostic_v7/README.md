# Initial-state diagnostic v7：32题，干预组与控制组分开

可运行的开发诊断。旧v6和论文结果未替换；没有发送模型请求或提交GPU任务。

## 冻结配置

| 面板 | 数量 | 资格 |
|---|---:|---|
| repair_sensitive | 16 | 存在替代定性belief，其实际reward接受集合与gold下不相交 |
| action_control | 16 | 没有上述强条件；不是把这些题都宣称为完全行动无关 |

干预组：14道自然伙伴行为推断、2道私人反馈读取。favored分布want 7、avoid 5、undetermined 3、neutral 1。
控制组：5道行为推断、11道初始信息控制；单独报告，不用于夸大行为推断能力。

共binary 16、linear 16。30题为3–4目标，2道私人反馈题保留6目标。不是已实测容易：这些是结构规模。32个source parent对应10种geometry，不是32种独立结构。

14题为teacher-only生成的新自然历史；18题来自已用于监测的validation结构（含明确重新构造的反馈变体）。canonical-parent检查未发现与扫描的本地训练bank重合，但这不等于geometry隔离，也不保证未收集在其他未扫描来源。整套不能称为untouched held-out benchmark。几何重复和已使用的开发来源必须在论文中说明。

## 四次调用与真正的intervention

1. B：初始状态、可见历史与反馈 → 定性belief。
2. O：相同可见信息 → 原生行动。
3. P_gold：当前状态、正确定性belief → 原生行动。
4. P_model：与P_gold相同的上下文和生成seed，仅换成模型B输出。

P不包含历史、初始状态描述、私人反馈的原文或数值posterior。私有偏好只经supplied judgment传入。保留解释后tool call。

B无效或截断时阻止P_model，不伪造默认belief；缺失与格式失败分开报告。repair_gain使用同一真后验对两次行动评分。分开报告belief确实改变的配对，以及belief没变时的输出变化，后者不能解释为输入干预效果。support列表统一排序，避免只改枚举次序。

16题的repair_sensitive是任务级“修复可能影响正确行动”的资格，不保证模型B一定错，也不保证替换后模型一定改善。没有把B_with_partner_plan反向辅助混入本版。

## 初始状态与teacher

已有承诺是外生起点，不展示成伙伴被要求做过的行为。保留合法轮次结构，用起点索引定义剩余机会。teacher从该起点的先验独立求解；此后的自主行为必须有正参考策略似然。私人查询和反馈不能抹成初始承诺。

新自然历史题在伙伴提议和自己响应之后，还保留一次自己的决策。候选不是从模型成功/失败中筛选，生成seed固定，筛选仅用teacher与任务结构。

每题同时核验：

- B查询覆盖P所需的全部未知偏好；不能用一条局部B替代多个未知量。
- 定性belief区域的精确最优集合不变。
- 实际含0.1容差的接受集合不变；单独记录各偏好世界的reward集合。
- 从P当前状态、无历史、无私人结果重新求解，与原历史分支的逐世界后续价值一致。
- 原生状态转移与整棵树的终局价值回放通过。

每题资格、替代belief、答案分布和规模见case_inventory.csv；完整证书在cases.json。没有通过就不进入32题，也不会拿控制题补不足的干预组。

## 运行

在仓库根目录、模型服务已启动的训练环境中：

```bash
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
python -m new.diagnostic_v7.experiment \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL_NAME \
  --checkpoint-hash YOUR_CHECKPOINT_SHA256 \
  --output runs/diagnostic_v7/MODEL_NAME \
  --max-tokens 4096 --repeats 1 --concurrency 4
```

单模型一遍最多128调用；B失败时更少。固定temperature=0、top_p=1、top_k=-1、seed=42，无自动重试。所有模型使用相同服务/批次设置；temperature=0不保证batch invariant。需要重复时各模型统一设置--repeats 3，不能只为某个模型择优重跑。

输出protocol.json、calls.jsonl（含完整请求/输出）、results.json、summary.json与COMPLETE/INCOMPLETE标记。summary按干预资格、证据类别分别汇总正确率、有效率、regret与配对收益；不得只取总体准确率解释机制。

## 复现和测试

```bash
python -m new.diagnostic_v7.rebuild_candidates
python -m new.diagnostic_v7.feedback_candidates
python -m new.diagnostic_v7.interaction_candidates
python -m new.diagnostic_v7.build
python -m unittest new.diagnostic_v7.test_initial_state new.diagnostic_v7.test_suite -q
```

首次三个构造步骤是CPU teacher求解，不调用LLM。生成后manifest冻结题目与关键代码hash；改动后必须明确重建版本，不混用旧结果。测试覆盖逐题重认证、全部合法行动评分、gold回归、B截断阻断，以及模拟服务端完整128请求链路；不是实际Q0表现验收。

早期source_audit/rebuild_audit是来源过程记录，不是最终库存；最终以manifest和selection_audit为准。
