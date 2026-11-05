"""Review B data for history dependence and reference-selection sensitivity."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from training.b_sft.social_b_dataset import digest
from training.b_sft.social_b_oracle import BeliefOracle
from training.b_sft.shared_teacher import SearchLimit


def audit(folder):
    def read(name):
        return [json.loads(line) for line in (folder/name).read_text().splitlines()]
    sources = {s['id']: s for s in read('sources.jsonl')}
    records = {r['id']: r for r in read('B_inputs.jsonl')}
    labels = {r['id']: r['answer'] for r in read('B_labels.jsonl')}
    pairs = read('pairs.jsonl')
    by_state = defaultdict(list)
    sensitivity, examples = [], []
    for rid, r in records.items():
        inp = r['input']; source = sources[r['source']]
        query = inp['queries'][0]
        # Remove both representations of history. Keep actual commitments,
        # pending, remaining schedule, catalogues and observer information.
        state = deepcopy(inp)
        state.pop('history'); state['public_state'].pop('transcript', None)
        by_state[(r['source'], digest(state))].append(rid)
        events = [dict(action=a, kind='setup' if i < len(source['prefix']) else 'partner')
                  for i,a in enumerate(inp['history'])]
        try:
            reverse = BeliefOracle.replay(source['raw'], events, turns=2,
                                          max_nodes=3000, seconds=2, reverse_actions=True)
            answer = reverse.belief(query['player'], query['goal'])
            sensitivity.append(dict(id=rid, status='same' if answer == labels[rid] else 'different',
                                    reverse_answer=answer))
        except (SearchLimit, ValueError) as exc:
            sensitivity.append(dict(id=rid, status='unresolved', error=type(exc).__name__, detail=str(exc)))
    matched = []
    for (source, _), ids in by_state.items():
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                if labels[a] != labels[b]:
                    matched.append(dict(source=source, left=a, right=b))
    for pair in pairs:
        if pair['category'] != 'update': continue
        source = sources[pair['source']]; record = records[pair['after']]
        query = record['input']['queries'][0]
        o = BeliefOracle(source['raw'], source['prefix'])
        timeline = []
        for action in record['input']['history'][len(source['prefix']):]:
            before = o.belief(query['player'], query['goal'])
            o.observe(action)
            after = o.belief(query['player'], query['goal'])
            timeline.append(dict(actor=o.events[-1]['actor'], action=action,
                before=before['possible_preferences'], after=after['possible_preferences'],
                reasons=[dict(own_type=c['own_type'], reason=c['evidence_reason'])
                         for c in o.events[-1]['comparisons']]))
        # Keep the exact current physical state but erase earlier preference
        # evidence by declaring the preceding history an exogenous setup.
        # This is a diagnostic counterfactual, never a replacement training label.
        history = record['input']['history']
        try:
            last_only = BeliefOracle(source['raw'], history[:-1], max_nodes=3000, seconds=2)
            last_only.observe(history[-1])
            answer = last_only.belief(query['player'], query['goal'])
            ablation = dict(status='checked', answer=answer,
                            earlier_evidence_needed=answer != labels[pair['after']])
        except (SearchLimit, ValueError) as exc:
            ablation = dict(status='unresolved', detail=str(exc))
        examples.append(dict(id=pair['after'], source=pair['source'], query=query, timeline=timeline,
                             last_action_only=ablation))
    status = {x['id']: x['status'] for x in sensitivity}
    history_needed = {e['id'] for e in examples if e['last_action_only'].get('earlier_evidence_needed')}
    order_passed = [p for p in pairs if status[p['before']] == status[p['after']] == 'same']
    screened = [p for p in order_passed if p['category'] != 'update' or p['after'] in history_needed]
    ids = {p[k] for p in screened for k in ('before', 'after')}
    for name, rows in [('screened_pairs.jsonl', screened),
                       ('screened_B_inputs.jsonl', [records[i] for i in sorted(ids)]),
                       ('screened_B_labels.jsonl', [dict(id=i, answer=labels[i]) for i in sorted(ids)])]:
        (folder/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    joint_inputs, joint_labels, joint_evidence = {}, {}, {}
    for rid in sorted(ids):
        record = records[rid]; source = sources[record['source']]
        queries = source.get('queries', [])
        if len(queries) != 2: continue
        inp = deepcopy(record['input'])
        inp['queries'] = queries
        inp['instruction'] = ('Infer both queried partner preferences from public history and your own preferences. '
                              'Provide one judgment per query with possible_preferences and favored. Do not choose an action or calculate utilities.')
        jid = digest(inp)
        if jid in joint_inputs: continue
        events = [dict(action=a, kind='setup' if i<len(source['prefix']) else 'partner')
                  for i,a in enumerate(inp['history'])]
        o = BeliefOracle.replay(source['raw'], events, max_nodes=3000, seconds=2)
        reverse = BeliefOracle.replay(source['raw'], events, max_nodes=3000, seconds=2, reverse_actions=True)
        assert set(o.worlds) == set(reverse.worlds), 'Joint support changed under action-order reversal'
        answers = []
        for query in queries:
            b = o.belief(query['player'], query['goal'])
            answers.append(dict(**query, possible_preferences=b['possible_preferences'], favored=b['favored']))
        tuples = sorted({tuple(w[q['player']][q['goal']] for q in queries) for w in o.worlds})
        marginal_product = len({t[0] for t in tuples}) * len({t[1] for t in tuples})
        joint_inputs[jid] = dict(id=jid, source=record['source'], input=inp)
        # This is the existing SUBMIT_BELIEFS argument shape, not a new tool.
        joint_labels[jid] = dict(id=jid, answer=dict(judgments=answers))
        joint_evidence[jid] = dict(id=jid, queries=queries, remaining_joint_preferences=tuples,
                                  correlated=len(tuples)<marginal_product)
    for name, rows in [('joint_B_inputs.jsonl', joint_inputs.values()),
                       ('joint_B_labels.jsonl', joint_labels.values()),
                       ('joint_support_audit.jsonl', joint_evidence.values())]:
        (folder/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    result = dict(same_state_different_history_pairs=matched,
        reverse_action_order=sensitivity, multiple_update_examples=examples,
        summary=dict(same_state_pairs=len(matched), same_state_sources=len({p['source'] for p in matched}),
            reverse_action_order=dict(Counter(x['status'] for x in sensitivity)),
            order_passed_pairs=len(order_passed),
            screened_pairs=len(screened), screened_questions=len(ids),
            screened_categories=dict(Counter(p['category'] for p in screened)),
            received_offer_categories=dict(Counter(p['category'] for p in screened if p.get('received_offer',False))),
            joint_questions=len(joint_inputs),
            joint_response_decisions=sum(r['input']['assessment']['phase']=='response' and
                                        r['input']['assessment']['observer_to_act'] for r in joint_inputs.values()),
            correlated_joint_questions=sum(r['correlated'] for r in joint_evidence.values()),
            update_history_ablation=dict(Counter(
                'needs_earlier_evidence' if e['last_action_only'].get('earlier_evidence_needed') else
                'same_answer_from_last_action' if e['last_action_only']['status']=='checked' else 'unresolved'
                for e in examples)),
            update_sources=len({p['source'] for p in pairs if p['category']=='update'})),
        scope='Reversing all legal-action ordering tests sensitivity to the chosen reference solution; '
              'differences are review flags, not labels silently replaced by a new mechanism. '
              'Screened pairs match at both endpoints for these two orderings only; update pairs additionally '
              'require earlier evidence in the last-action-only ablation. No general robustness claim.')
    (folder/'quality_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    audit(parser.parse_args().folder)
