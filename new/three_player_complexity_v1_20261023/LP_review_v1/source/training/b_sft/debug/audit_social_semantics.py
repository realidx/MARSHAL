"""Audit existing games against social-dependence controls; never emit training gold.

Replays current B checkpoints, checks native existing fixtures, and tests player
renaming at source roots. Success means consistency with a declared teacher,
not human realism, internal reasoning faithfulness, or generalization.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from training.b_sft.social_b_oracle import BeliefOracle, VERSION, canonical, forward_fixture
from training.b_sft.social_b_dataset import judgment, observer_belief
from training.b_sft.social_cases import bundle_fixture
from training.b_sft.social_cases_expand import compensated_fixture
from training.b_sft.debug.audit_social_b_weighted import exact_posterior
from training.b_sft.debug.audit_menu_information import direct_value


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def rename_action(action, mapping):
    out=deepcopy(action)
    for field in ('partner_id','proposer_id'):
        if field in out:out[field]=mapping[out[field]]
    if 'offers' in out:out['offers']=[rename_action(a,mapping) for a in out['offers']]
    return out


def rename(raw, prefix, mapping):
    """Only rename players; carry each player's actions, utilities and schedule."""
    out=deepcopy(raw);g=out['game'];n=g['n_players']
    out['ego']=mapping[raw['ego']]
    out['type_catalogues']={str(mapping[int(p)]):deepcopy(rows) for p,rows in raw['type_catalogues'].items()}
    for field in ('n_actions_per_player','forbidden_actions'):
        if g.get(field) is not None:
            old=g[field];g[field]=[None]*n
            for p in range(n):g[field][mapping[p]]=old[p]
    g['round_robin']=[mapping[p] for p in g['round_robin']]
    for goal in g['goals']:
        for action in goal['required_actions']:action['player_id']=mapping[action['player_id']]
    return out,[rename_action(a,mapping) for a in prefix]


def root_choices(oracle):
    p=oracle.rules.actor(oracle.node)
    return [oracle.choices(own) for own in dict.fromkeys(w[p] for w in oracle.worlds)]


def compare_roots(left,right,inverse):
    differences=[]
    for a,b in zip(left,right):
        assert a['own_type']==b['own_type']
        la={canonical(x):True for x in a['admissible_actions']}
        rb={canonical(rename_action(x,inverse)):True for x in b['admissible_actions']}
        lv={canonical(x['action']):[x['own'],x['others']] for x in a['values']}
        rv={canonical(rename_action(x['action'],inverse)):[x['own'],x['others']] for x in b['values']}
        assert lv.keys()==rv.keys()
        changed=[k for k in lv if not np.allclose(lv[k],rv[k],atol=1e-8,rtol=0)]
        if la!=rb or changed:
            differences.append(dict(own_type=a['own_type'],actions_changed=la!=rb,
                                    value_changes=changed,left=a,right=b))
    return differences


def fixture_audit():
    records={}
    for name,fn,kwargs,goal in (
        ('forward',forward_fixture,{},2),('deadline',forward_fixture,dict(deadline=True),2),
        ('bundle',bundle_fixture,{},0),('compensated',compensated_fixture,{},0)):
        raw,prefix=fn(**kwargs);o=BeliefOracle(raw,prefix)
        tree=o.solve();rows=root_choices(o)
        for row in rows:
            for ai,value in enumerate(row['values']):
                manual=direct_value(tree,tree.policy,row['actor'],row['own_type'],ai)
                assert np.allclose([manual[row['actor']],manual.sum()-manual[row['actor']]],
                                   [value['own'],value['others']],atol=1e-9,rtol=0)
        branches=[]
        for action in o.rules.actions(o.node):
            child=BeliefOracle(raw,prefix)
            try:
                child.observe(action.to_dict());exact_posterior(child)
                branches.append(dict(action=action.to_dict(),status='compatible',belief=child.belief(1,goal)))
            except ValueError as exc:
                if 'incompatible with every candidate' not in str(exc):raise
                branches.append(dict(action=action.to_dict(),status='impossible_under_teacher'))
        records[name]=dict(raw=raw,prefix=prefix,goal=goal,rows=rows,branches=branches,
            commitments=o.node.state.snapshot_commitments(),pending_offer=o.node.pending.to_dict(),
            independent_native_values_verified=True)
    # Existing opportunity contrast: same physical commitments and current offer.
    assert records['forward']['commitments']==records['deadline']['commitments']
    assert records['forward']['pending_offer']==records['deadline']['pending_offer']
    assert records['forward']['rows'][0]['admissible_actions']==[{'response':'REJECT'}]
    assert records['deadline']['rows'][0]['admissible_actions']==[{'response':'ACCEPT'}]
    # Existing compensation contrast changes other goal preferences, not target.
    assert records['bundle']['commitments']==records['compensated']['commitments']
    assert records['bundle']['pending_offer']==records['compensated']['pending_offer']
    assert records['bundle']['rows'][2]['admissible_actions']==[{'response':'REJECT'}]
    assert records['compensated']['rows'][2]['admissible_actions']==[{'response':'ACCEPT'}]
    raw,prefix=forward_fixture()
    raw['type_catalogues']['0']=[raw['own_preferences'],[1,0,-1,0,0]]
    other=deepcopy(raw);other['own_preferences']=other['type_catalogues']['0'][1]
    a=BeliefOracle(raw,prefix);b=BeliefOracle(other,prefix)
    assert root_choices(a)==root_choices(b)
    a.observe({'response':'REJECT'});b.observe({'response':'REJECT'})
    assert a.events==b.events
    records['private_visibility']=dict(partner_policy_invariant=True,
        public_belief=a.belief(0,2),observer_a=observer_belief(a,0,2),observer_b=observer_belief(b,0,2),
        limitation='Checks non-leakage and own-information conditioning; not fixed-preference private-observation counterfactuals.')
    return records


def checkpoint_audit(tasks,sources):
    reports=[];cache={};unique_events={}
    for index,t in enumerate(tasks):
        key=(t['source'],canonical(t['input']['history']))
        try:
            if key not in cache:
                source=sources[t['source']];prefix=source['prefix']
                assert t['input']['history'][:len(prefix)]==prefix
                events=[dict(action=a,kind='setup' if i<len(prefix) else 'partner')
                        for i,a in enumerate(t['input']['history'])]
                cache[key]=BeliefOracle.replay(source['raw'],events,max_nodes=3000,seconds=2)
                exact_posterior(cache[key])
            o=cache[key];q=t['input']['queries'][0]
            assert t['input']['player']==o.raw['ego']
            assert t['input']['own_preferences']==o.raw['own_preferences']
            actual=observer_belief(o,q['player'],q['goal'])
            assert judgment(actual)==judgment(t['gold']['judgments'][0])
            # Candidate uncertainty remaining to this observer, not public alone.
            worlds=o.joint_belief(observer=o.raw['ego'],own=o.raw['own_preferences'])
            reasons=Counter();changed_events=0
            for i,e in enumerate(o.events):
                if e['kind']!='partner':continue
                reasons.update(c['evidence_reason'] for c in e['comparisons'] if not c['observed_action_compatible'])
                before=e['information_before']['public_world_weights'];after=e['public_world_weights_after']
                changed_events+=len(before)!=len(after) or not np.allclose(before,after,atol=1e-9,rtol=0)
                unique_events[(t['source'],canonical(o.history[:i+1]))]=e
            reports.append(dict(id=t['id'],source=t['source'],split=t['split'],status='verified',
                bucket=t['curriculum']['bucket'],observer_worlds=len(worlds),target_is_observer=q['player']==o.raw['ego'],
                gold=judgment(actual),history_exclusion_reasons=dict(reasons),weight_changing_events=changed_events,
                limitation='History reasons may concern other hidden slots; not causal attribution to this query.'))
        except Exception as exc:
            reports.append(dict(id=t['id'],source=t['source'],status='failed',error=type(exc).__name__,detail=str(exc)))
        if (index+1)%40==0:print(json.dumps(dict(progress='checkpoints',completed=index+1)),flush=True)
    reason_counts=Counter();likelihood_only=0
    for e in unique_events.values():
        reason_counts.update(c['evidence_reason'] for c in e['comparisons'] if not c['observed_action_compatible'])
        before=e['information_before']['public_world_weights'];after=e['public_world_weights_after']
        likelihood_only+=len(before)==len(after) and not np.allclose(before,after,atol=1e-9,rtol=0)
    return reports,dict(unique_autonomous_events=len(unique_events),excluded_type_reasons=dict(reason_counts),
                        support_unchanged_weight_changes=likelihood_only)


def shortcut_audit(tasks):
    def action_key(t):
        setup=len(t['input']['public_setup']['intervention_prefix'])
        h=t['input']['history'][setup:]
        return (h[-1].get('response') or h[-1].get('action')) if h else 'NO_AUTONOMOUS_EVENT'
    train=[t for t in tasks if t['split']=='train'];counts=defaultdict(Counter);total=Counter()
    for t in train:
        answer=canonical(judgment(t['gold']['judgments'][0]))
        counts[action_key(t)][answer]+=1;total[answer]+=1
    fallback=total.most_common(1)[0][0]
    lookup={k:c.most_common(1)[0][0] for k,c in counts.items()}
    result={}
    for split in ('train','validation','test'):
        rows=[t for t in tasks if t['split']==split]
        result[split]={}
        for bucket in ('all','behavior_short','behavior_long','control'):
            subset=rows if bucket=='all' else [t for t in rows if t['curriculum']['bucket']==bucket]
            correct=sum(lookup.get(action_key(t),fallback)==canonical(judgment(t['gold']['judgments'][0])) for t in subset)
            result[split][bucket]=dict(correct=correct,total=len(subset),accuracy=correct/len(subset) if subset else None)
    return dict(rule='Predict training-majority label per last autonomous action kind, ignoring player/goal/history content.',
                lookup={k:json.loads(v) for k,v in lookup.items()},results=result)


def run(source_dir,task_dir,out):
    if out.exists():raise ValueError('Use a new output directory')
    sources={s['id']:s for s in read(source_dir/'sources.jsonl')};tasks=read(task_dir/'tasks.jsonl')
    fixtures=fixture_audit();reports,events=checkpoint_audit(tasks,sources)
    roots=[]
    for index,s in enumerate(sources.values()):
        raw=s['raw'];n=raw['game']['n_players'];mapping={p:n-1-p for p in range(n)}
        r,prefix=rename(raw,s['prefix'],mapping)
        record=dict(source=s['id'],mapping=mapping)
        for name,rr,pp in (('original',raw,s['prefix']),('renamed',r,prefix)):
            try:
                o=BeliefOracle(rr,pp,max_nodes=3000,seconds=2)
                record[name]=dict(status='verified',rows=root_choices(o),nodes=len(o.solve().entries))
            except Exception as exc:
                record[name]=dict(status='failed',error=type(exc).__name__,detail=str(exc))
        if all(record[k]['status']=='verified' for k in ('original','renamed')):
            diffs=compare_roots(record['original']['rows'],record['renamed']['rows'],{v:k for k,v in mapping.items()})
            record.update(status='different' if diffs else 'invariant',differences=diffs)
        else:record['status']='inconclusive_solver_failure'
        roots.append(record)
        if (index+1)%10==0:print(json.dumps(dict(progress='root_renaming',completed=index+1)),flush=True)
    counts=Counter(r['status'] for r in reports)
    summary=dict(oracle=VERSION,actual_LM=False,training_ready=False,
        checkpoints=dict(counts),events=events,root_renaming=dict(Counter(r['status'] for r in roots)),
        checkpoint_buckets=dict(Counter(t['curriculum']['bucket'] for t in tasks)),
        perfect_information_checkpoints=sum(r.get('observer_worlds')==1 for r in reports),
        multi_possible_favored_checkpoints=sum(len(r.get('gold',{}).get('possible_preferences',[]))>1 and r['gold']['favored']!='undetermined' for r in reports),
        shortcuts=shortcut_audit(tasks),
        limits=['Existing inspected development sample; no natural frequency or transfer claim.',
                'Reverse player renaming checks source roots only, not every history or all permutations.',
                'Private information is currently own preference; no independent private observation channel.',
                'Labels remain conditional on initial prior, rationality, social ties, and window policy.'])
    paths=[Path(__file__),Path('training/b_sft/social_b_oracle.py'),Path('training/b_sft/social_b_random_window.py'),
           Path('training/b_sft/shared_teacher.py'),source_dir/'sources.jsonl',task_dir/'tasks.jsonl']
    summary['hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    out.mkdir(parents=True)
    for name,obj in (('summary.json',summary),('fixture_witnesses.json',fixtures)):
        (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    for name,rows in (('checkpoint_audit.jsonl',reports),('root_renaming.jsonl',roots)):
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',type=Path,default=Path('new/local_data/social_runs/b_weighted_v4_reviewed'))
    p.add_argument('--tasks',type=Path,default=Path('new/local_data/social_runs/b_behavior_curriculum_v2'))
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.sources,a.tasks,a.out)
