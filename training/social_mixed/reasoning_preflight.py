"""Offline package/label validation; optional exact local-tokenizer context audit."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import numpy as np
from training.social_mixed.reasoning_bank import load, PATH, panel, sha, stable
from training.social_mixed.paired_requests import request


def audit(tokenizer=None):
    manifest=json.loads((PATH/'manifest.json').read_text())
    for name,info in manifest['files'].items():
        if sha((PATH/name).read_bytes())!=info['sha256']:raise ValueError('Artifact changed: '+name)
    if manifest.get('active_recipe')!='audited-tristate-v1':raise ValueError('Apply audited role policy before training')
    bindings=json.loads((PATH/'policy_audit_bindings.json').read_text())
    if manifest.get('training_plan_sha256'):
        if sha((PATH/'training_plan.json').read_bytes())!=manifest['training_plan_sha256']:raise ValueError('Training plan changed')
        if sha((PATH/'policy_audit_bindings.json').read_bytes())!=manifest['policy_audit_bindings_sha256']:raise ValueError('Audit binding changed')
    counts={}; packages=defaultdict(set); families=defaultdict(set); lengths=[]; p_prompts={}; p_count=0
    for split in ('train','validation'):
        tasks=load(split); cases={r['canonical_id']:r for r in load(split,'cases.jsonl')}
        views=defaultdict(dict)
        for t in tasks:
            views[t['canonical_id']][t['paired_view']]=t
            packages[t['package_id']].add(split);families[t['family']].add(split)
            if t['input'].get('previous_belief'):
                raise ValueError('Raw B must not receive the previous gold belief')
            req=request(t,'action_tools',t.get('name_variant',0))
            if t['paired_view']=='O' and 'SUPPLIED BELIEF' in req['messages'][1]['content']:
                raise ValueError('Belief leaked into O')
            if t['paired_view']=='Pplus':
                p_count += 1
                if 'p_supervision' in t:
                    states=t['p_supervision']['action_states']
                    if len(states)!=len(t['input']['legal_actions']):raise ValueError('Action supervision length changed')
                    if not set(states)<={'positive','negative','masked'}:raise ValueError('Unknown semantic state')
                    if t['p_train_eligible'] != ('positive' in states and 'negative' in states):raise ValueError('P eligibility mismatch')
                    if t['p_pool_status']=='quarantined' and set(states)!={'masked'}:raise ValueError('Uncertified P has semantic labels')
                if not t.get('p_information_contract'): raise ValueError('P missing history-free contract')
                text=req['messages'][1]['content']
                if any(marker in text for marker in ('EVENTS IN ORDER','PREFERENCE CONDITIONS','Observed player choice','Preset event:')):
                    raise ValueError('Historical evidence rendered in P')
                belief_text=text.split('SUPPLIED BELIEF',1)[1].split('RESPONSE INSTRUCTIONS',1)[0]
                if any(c.isdigit() for c in belief_text): raise ValueError('Numerical belief rendered in P')
                signature=json.dumps(req,sort_keys=True)
                acceptable={json.dumps(a,sort_keys=True) for a in t['teacher']['acceptable_actions']}
                if signature in p_prompts and p_prompts[signature] != acceptable:
                    raise ValueError('Identical history-free P prompts have inconsistent reward targets')
                p_prompts[signature]=acceptable
            if tokenizer is not None:
                rendered=tokenizer.apply_chat_template(
                    req['messages'],tools=req['tools'],tokenize=True,
                    add_generation_prompt=True,return_dict=True)
                ids=rendered['input_ids']
                if (not isinstance(ids,list) or not ids or
                        any(not isinstance(token_id,int) for token_id in ids)):
                    raise TypeError('Tokenizer must return one unbatched input_ids list')
                lengths.append(dict(id=t['id'],tokens=len(ids)))
        for cid,v in views.items():
            if set(v)!= {'O','B','Pplus'}:raise ValueError('Incomplete canonical views')
            if v['O']['teacher']!=v['Pplus']['teacher']:raise ValueError('O/Pplus targets differ')
            lab=cases[cid]['labels'];actor=v['O']['input']['player']
            digest=sha(stable({k:lab[k] for k in ('worlds','posterior','per_world_payoffs','action_values','acceptable_actions','query_candidates')}).encode())
            if bindings[cid]!=digest:raise ValueError('Value/belief labels changed after semantic audit')
            supplied=v['Pplus']['input']['supplied_belief']
            expected=[dict(player=q['player'],goal=q['goal'],**q['gold']) for q in lab['query_candidates']]
            if supplied['semantic_beliefs']!=expected: raise ValueError('P/B qualitative beliefs differ')
            if 'joint_distribution' in supplied: raise ValueError('Numerical belief retained in P')
            values=np.einsum('awp,w->ap',np.asarray(lab['per_world_payoffs']),np.asarray(lab['posterior']))
            if not np.allclose(values,lab['action_values'],atol=1e-8,rtol=0):raise ValueError('Value label mismatch')
            regret=values[:,actor].max()-values[:,actor]
            if not np.allclose(regret,lab['own_regret'],atol=1e-8,rtol=0):raise ValueError('Regret label mismatch')
            if lab['query']['gold']!=v['B']['teacher']['gold']:raise ValueError('B target mismatch')
        for relation in load(split,'relations.jsonl'):
            a,b=(cases[relation[k]]['labels'] for k in ('left','right'))
            sa,sb=set(a['exact_own_optimal_indices']),set(b['exact_own_optimal_indices'])
            expected='must_change' if sa.isdisjoint(sb) else 'same_optimal_set' if sa==sb else 'overlapping_optima'
            if expected!=relation['relation']:raise ValueError('Counterfactual relation mismatch')
        counts[split]=dict(cases=len(cases),views=len(tasks))
    if any(len(v)>1 for v in packages.values()):raise ValueError('Parent split leakage')
    if any(len(v)>1 for v in families.values()):raise ValueError('Source-family split leakage')
    if not any(r['relation']=='must_change' for r in load('validation','relations.jsonl')):
        raise ValueError('Validation lost all action-changing contrasts')
    if manifest.get('active_recipe')=='audited-tristate-v1':
        chosen={t['canonical_id'] for t in panel()}
        anchor_pairs=[r for r in load('validation','relations.jsonl') if r.get('isolated_B_action_pair')]
        if not anchor_pairs:raise ValueError('Missing B-to-action validation')
        if any(not {r['left'],r['right']}<=chosen or not r['same_B_query'] or not r['semantic_B_changed'] for r in anchor_pairs):
            raise ValueError('Validation panel lost isolated B contrasts')
    # Check the actual compact training pool too, including newly constructed scenes.
    from training.social_mixed.compact_bank import load as compact_load
    compact_tasks,_,compact_sha=compact_load()
    for t in compact_tasks:
        req=request(t,'action_tools',t.get('name_variant',0))
        if tokenizer is not None:
            ids=tokenizer.apply_chat_template(req['messages'],tools=req['tools'],tokenize=True,
                add_generation_prompt=True,return_dict=True)['input_ids']
            if not isinstance(ids,list) or not ids or any(not isinstance(x,int) for x in ids):
                raise TypeError('Tokenizer must return one unbatched input_ids list')
            lengths.append(dict(id=t['id'],pool='compact-200',tokens=len(ids)))
    failures=[r for r in lengths if r['tokens']>3072]
    return dict(compact_training_views=len(compact_tasks),compact_bank_sha256=compact_sha,counts=counts,parent_split_disjoint=True,source_family_split_disjoint=True,
                panel_cases=len({t['canonical_id'] for t in panel()}),
                history_free_P_checked=p_count, identical_P_prompt_targets_consistent=True,
                active_P_roles=dict(Counter(t['split']+':'+t.get('p_pool_status','legacy') for split in ('train','validation') for t in load(split) if t['paired_view']=='Pplus')),
                isolated_B_validation_pairs=sum(r.get('isolated_B_action_pair',False) for r in load('validation','relations.jsonl')),
                context_checked=tokenizer is not None,context_failures=failures,
                max_prompt_tokens=max((r['tokens'] for r in lengths),default=None),
                passed=not failures, GPU_acceptance='not performed')


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--tokenizer');cli.add_argument('--output',required=True)
    args=cli.parse_args();tokenizer=None
    if args.tokenizer:
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(args.tokenizer,local_files_only=True)
    result=audit(tokenizer)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
