"""Readable index and review queue for the per-case qualitative audit."""
import json
from collections import Counter
from training.social_mixed.reasoning_bank import PATH, sha


def write():
    payload=(PATH/'qualitative_case_audit.jsonl').read_bytes()
    rows=list(map(json.loads,payload.splitlines()))
    report=json.loads((PATH/'qualitative_case_audit_summary.json').read_text())
    assert sha(payload)==report['audit_sha256']
    labels={'reward_labels_invariant_in_envelope':'评分集合稳健',
            'reward_label_changes_witnessed':'已找到评分变化反例',
            'original_positive_labels_robust_negative_labels_unresolved':'正标签稳健，负标签待定',
            'unresolved_boundary_or_response_tie':'边界/平局待定'}
    text=['# 定性 P 逐题审计','',
          '检查497个局面。每题同时检查当前文字的宽泛含义（text_envelope）与B标签器内部规则（b_contract）。',
          '数值概率只存在于后台反例证据中，没有加回模型输入。', '',
          '## 结论范围','',
          '枚举定性规则的凸区域，用线性规划计算每个动作的最大自身regret及响应平局时的社会收益差；并检查负标签能否成为可接受动作。只在重新验证belief及原评分函数之后记录反例。',
          '稳健结论限于已有teacher世界集合、固定逐世界后续策略价值表和浮点求解容差；不保证替代分布可由原历史产生，也不代表重新求解未来伙伴策略后的全局认证。所有直接后继均终局的题另行标记，其价值不依赖未来行动。',
          'text_envelope不擅自给“更支持/不明确”规定隐藏的数字阈值；它是较宽的保守检查范围。b_contract使用现有标签器内部阈值，不将其输出给模型。', '',
          '## 汇总','', '| 检查范围 | 评分集合稳健 | 找到评分变化反例 | 其中与原集合不相交 | 其余待定 |',
          '| --- | ---: | ---: | ---: | ---: |']
    for mode in ('text_envelope','b_contract'):
        s=report['summaries'][mode];status=s['statuses'];good=status.get('reward_labels_invariant_in_envelope',0);bad=status.get('reward_label_changes_witnessed',0)
        text.append(f"| {mode} | {good} | {bad} | {s['disjoint_witness_cases']} | {len(rows)-good-bad} |")
    text+=['','“评分变化”包括原来被判错的动作变得可接受，或原来正确的动作变得不可接受；“不相交”是更严重的两个分布下没有共同可接受动作。二者不能混为一谈。',
           '', '## 处理清单','',
           '`qualitative_review_queue.json`列出需要复核的题号及原因，不自动删除题目或更改动作标签。优先处理b_contract下的不相交反例，其次处理其余评分变化，再处理仅在宽范围下出现的问题。',
           '建议对问题题组修订局面/奖励接口或隔离；不要只凭同一prompt未出现冲突就恢复训练。',
           '', '## 逐题索引','',
           '完整数值证据在`qualitative_case_audit.jsonl`，以完整canonical_id查找；原始世界和teacher表位于`cases.jsonl`。下面的动作编号均为该题legal_actions的零起始索引。', '',
           '| canonical_id | split | 所有直接后继终局 | 文字范围 | B规则范围 | B规则下通用可接受动作 | B规则下不相交反例 |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    queue=[]
    for r in rows:
        broad=r['text_envelope'];b=r['b_contract']
        text.append(f"| {r['canonical_id']} | {r['split']} | {'是' if r['all_immediate_actions_terminal'] else '否'} | {labels[broad['status']]} | {labels[b['status']]} | {b['universally_acceptable_indices']} | {'有' if b['disjoint_action_witness'] else '无'} |")
        if broad['status']!='reward_labels_invariant_in_envelope':
            priority=1 if b['disjoint_action_witness'] else 2 if b['witnesses'] else 3
            queue.append(dict(canonical_id=r['canonical_id'],split=r['split'],family=r['family'],priority=priority,
                              text_status=broad['status'],b_contract_status=b['status']))
    (PATH/'QUALITATIVE_CASE_AUDIT.md').write_text('\n'.join(text)+'\n')
    (PATH/'qualitative_review_queue.json').write_text(json.dumps(sorted(queue,key=lambda r:(r['priority'],r['split'],r['canonical_id'])),indent=2)+'\n')
    print(json.dumps(dict(review_cases=len(queue),priorities=dict(Counter(r['priority'] for r in queue)),
                         immediate_terminal_cases=sum(r['all_immediate_actions_terminal'] for r in rows)),indent=2))

if __name__=='__main__':write()
