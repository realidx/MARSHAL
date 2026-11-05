"""Re-solve frozen pilot labels from visible rules; check native legality and tokens."""
import argparse
from collections import Counter
from copy import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from training.b_sft.debug.audit_readable_pretraining import (
    reconstruct, independent_backward, independent_final_actions, VALUES)
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, observed_slots
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_p_qualitative import robust_actions
from training.b_sft.social_bp_grpo import read, validate_tasks
from training.b_sft.build_bp_pilot import favored_update, nonredundant_favored, quotas


def audit(tasks, tokenizer_path=None):
    checks = validate_tasks(tasks); cache = {}; results = []
    for number, t in enumerate(tasks):
        inp = t['input']; gold = t['teacher']; raw, own = reconstruct(inp)
        key = json.dumps([raw, inp['imposed_setup']], sort_keys=True)
        if key not in cache:
            e = PrivateEpisode(raw, inp['imposed_setup'], seconds=30, max_nodes=100000)
            cache[key] = e, audit_native(e.tree), independent_backward(e.tree)
        root, native, independent = cache[key]; e = copy(root)
        for event in inp['voluntary_history']: e.observe(event)
        node = e.tree.entries[e.index].node
        assert node.state.public_state() == inp['current_state'], t['id']
        assert (None if node.pending is None else node.pending.to_dict()) == inp['pending_offer']
        facts = [(f['player'], f['goal'], VALUES[f['preference']]) for f in inp['private_results']]
        row = dict(id=t['id'], split=t['split'], native=native, independent_backward=independent,
                   selected_policy_sha256=e.tree.certificate['policy_sha256'])
        assert row['selected_policy_sha256'] == gold['policy_sha256'], t['id']
        if t['task'] == 'B':
            q = inp['queries'][0]
            b = e.belief(q['player'], q['goal'], observer=inp['observer'], own=own, private_results=facts)
            assert {k: b[k] for k in gold['gold']} == gold['gold'], t['id']
            np.testing.assert_allclose([b['preference_weights'][v] for v in VALUES],
                [gold['preference_weights'][v] for v in VALUES], atol=1e-9, rtol=0)
            if 'previous_belief' in inp:
                old = copy(root)
                if inp.get('new_history'):
                    for event in inp['voluntary_history'][:-len(inp['new_history'])]: old.observe(event)
                    slots = observed_slots(old.tree.entries[old.index].node, inp['observer'])
                    prev = old.belief(q['player'], q['goal'], observer=inp['observer'], own=own,
                        private_results=[f for f in facts if f[:2] in slots])
                else:
                    assert not inp['voluntary_history'] and inp['imposed_setup'][-1]['action'] == 'INVESTIGATE'
                    assert inp['imposed_setup'][-1]['player'] == q['player'] and inp['imposed_setup'][-1]['goal'] == q['goal']
                    # This is the supplied belief immediately before receipt.
                    weights = e.tree.world_weights*np.array([w[inp['observer']]==own for w in e.tree.worlds])
                    weights /= weights.sum()
                    marginal = {name:sum(p for p,w in zip(weights,e.tree.worlds) if w[q['player']][q['goal']]==v) for name,v in VALUES.items()}
                    possible = [name for name,p in marginal.items() if p>0]
                    leaders = [name for name in possible if marginal[name]>=max(marginal.values())-1e-9]
                    prev = dict(possible_preferences=possible,favored=leaders[0] if len(leaders)==1 else 'undetermined')
                assert {k: prev[k] for k in inp['previous_belief']} == inp['previous_belief'], t['id']
                row['previous_belief_checked'] = True
        else:
            choices = e.choices(own, facts)
            assert choices['actions'] == inp['legal_actions'], t['id']
            manual = independent_final_actions(e)
            if manual is not None:
                np.testing.assert_allclose(manual, [e.tree.values[c] for c in e.tree.entries[e.index].children], atol=1e-9, rtol=0)
            row['independent_final_values'] = manual is not None
            if 'qualitative_certificate' in gold:
                payoffs = np.array([e.tree.values[c] for c in e.tree.entries[e.index].children])
                np.testing.assert_allclose(payoffs, gold['per_world_payoffs'], atol=1e-9, rtol=0)
                assert [list(map(list, w)) for w in e.tree.worlds] == gold['worlds']
                cert = robust_actions(payoffs, inp['player'], e.tree.worlds, gold['claims'], own_tolerance=.1,
                                      social_tolerance=.1, envelopes=gold['audit_envelopes'], offer_response=node.pending is not None)
                assert cert['status'] == 'certified'; accepted = cert['acceptable']
            else:
                np.testing.assert_allclose(choices['values'], gold['action_values'], atol=1e-9, rtol=0)
                accepted = acceptable(choices['values'], inp['player'], actions=choices['actions'])
            assert [choices['actions'][i] for i in accepted] == gold['acceptable_actions'], t['id']
            if t.get('information_positive'):
                queries = [i for i,a in enumerate(choices['actions']) if a.get('action') == 'INVESTIGATE']
                margin = max(choices['values'][i][0] for i in queries)-max(v[0] for i,v in enumerate(choices['values']) if i not in queries)
                assert abs(margin-gold['own_query_margin']) < 1e-9
                if 'answer_use_ablation' in gold:
                    ab = gold['answer_use_ablation']; branch = copy(e); branch.observe(ab['public_history'][0])
                    en = branch.tree.entries[branch.index]; assert en.actor == 0
                    weights = branch.weights/branch.weights.sum()
                    informed = np.average(branch.tree.values[branch.index], axis=0, weights=weights)
                    av = np.array([branch.tree.values[c] for c in en.children])
                    blind = np.einsum('awp,w->ap', av, weights)[:,0].max()
                    np.testing.assert_allclose(informed, ab['informed_value'], atol=1e-9, rtol=0)
                    assert abs(blind-ab['best_blind_own']) < 1e-9
                    row['answer_use_own_gain'] = float(informed[0]-blind)
        results.append(row)
        if number % 32 == 0: print(json.dumps(dict(checked=number+1, roots=len(cache))), flush=True)
    summary = dict(checks, native_roots=len(cache), independent_backward=sum(r['independent_backward'] for r in results),
                   independent_final_values=sum(r.get('independent_final_values',False) for r in results),
                   previous_beliefs=sum(r.get('previous_belief_checked',False) for r in results), splits={})
    for split, expected in (('train',256),('validation',64),('test',64)):
        rs = [t for t in tasks if t['split'] == split]; assert len(rs) == expected
        assert Counter((t['pool'], t['stage']) for t in rs) == Counter(quotas(split))
        info = [t for t in rs if t['pool']=='information']; b = [t for t in rs if t['task']=='B']
        counts = dict(favored_only_updates=sum(favored_update(t) for t in b),
            nonredundant_favored=sum(nonredundant_favored(t) for t in b),
            own_information_positives=sum(t.get('information_positive',False) and t['teacher'].get('own_query_margin',0)>.10000001 for t in info),
            future_information_negatives=sum(t.get('information_negative_kind')=='future_opportunity_remains' for t in info))
        assert all(counts.values()), (split, counts)
        assert sum(t.get('information_positive',False) for t in info)*2 == len(info)
        counts.update(tasks=len(rs), families=len({t['family'] for t in rs}),
            b_set_sizes=dict(Counter(len(t['teacher']['gold']['possible_preferences']) for t in b)),
            b_direct=sum(t['direct_answer'] for t in b), qualitative=sum(bool(t.get('qualitative_level')) for t in rs))
        summary['splits'][split] = counts
    if tokenizer_path:
        from transformers import AutoTokenizer
        from training.b_sft.social_named_probe import request
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
        lengths = []
        for t in tasks:
            req = request(t, 'action_tools', t['name_variant'])
            args = dict(tools=req['tools'], add_generation_prompt=True)
            text = tokenizer.apply_chat_template(req['messages'], tokenize=False, **args)
            ids = tokenizer(text, add_special_tokens=False)['input_ids']
            assert ids == tokenizer.apply_chat_template(req['messages'], tokenize=True, return_dict=True, **args)['input_ids']
            assert len(ids)<=4096, (t['id'],len(ids)); lengths.append(len(ids))
        summary['tokenizer'] = dict(path=tokenizer_path, max_prompt_tokens=max(lengths), min_prompt_tokens=min(lengths),
            median_prompt_tokens=float(np.median(lengths)), template_sha256=hashlib.sha256(str(tokenizer.chat_template).encode()).hexdigest(),
            source_model='Qwen/Qwen3-4B-Instruct-2507', revision='cdbee75f17c01a7cc42f958dc650907174af0554')
    summary['scope'] = 'Labels conditional on reproducible selected partner strategy; no uniqueness or convergence claim. Native legality checked. Independent payoff checks only where information-compatible. Qualitative labels robust within recorded word-meaning envelopes.'
    return dict(summary=summary, tasks=results)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--tasks', required=True); p.add_argument('--out', required=True); p.add_argument('--tokenizer')
    a = p.parse_args(); result = audit(read(a.tasks), a.tokenizer)
    result['tasks_sha256'] = hashlib.sha256(Path(a.tasks).read_bytes()).hexdigest()
    Path(a.out).write_text(json.dumps(result, indent=2)+'\n'); print(json.dumps(result['summary'], indent=2))
