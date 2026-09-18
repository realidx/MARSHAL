"""Recompute linear additions and audit actual bounded task scheduling."""
from collections import Counter
from copy import copy
import json
import numpy as np
from training.social_mixed.prepare_reasoning_v5 import OUT,SOURCE,read
from training.social_mixed.curriculum_sampling import select
from training.social_mixed.distribution_sampling import select as old
from training.social_mixed.prepare_reasoning_v4 import root_episode,stable,task_at
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.social_mixed.audit_zero_signal import interface_check
from training.social_mixed.reasoning_requests import request
from training.social_mixed.structure_coverage import geometry_id


def main():
    report={'linear':{}}
    for split in ('train','validation'):
        rows=read(OUT/('bp_'+split+'.jsonl'));by={t['id']:t for t in rows};checks=[]
        for t in rows:
            if not t.get('linear_history_addition') or t['task']!='P' or t.get('oracle_pair_of'):continue
            inp=t['input'];raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior']
            root,native=root_episode(stable([raw,inp['imposed_setup']]))
            e=copy(root);e.weights=root.weights.copy()
            for event in inp['voluntary_history']:e.observe(event)
            rebuilt=task_at(t,e,inp['imposed_setup'],inp['voluntary_history'],[],'P')
            assert rebuilt['teacher']['acceptable_actions']==t['teacher']['acceptable_actions']
            assert rebuilt['teacher']['prior_acceptable_actions']==t['teacher']['prior_acceptable_actions']
            np.testing.assert_allclose(rebuilt['teacher']['action_values'],t['teacher']['action_values'],atol=1e-9)
            assert rebuilt['teacher']['history_changes_acceptable']
            b=by[t['linked_b_id']];q=b['input']['queries'][0]
            rebuilt_b=task_at(b,e,inp['imposed_setup'],inp['voluntary_history'],[],'B',(q['player'],q['goal']))
            assert rebuilt_b['teacher']['gold']==b['teacher']['gold']
            oracle=next(o for o in rows if o.get('oracle_pair_of')==t['id'])
            assert oracle['teacher']==t['teacher']
            actual=oracle['input']['supplied_belief']['joint_distribution']
            assert abs(sum(float(r['probability']) for r in actual)-1)<1e-9
            for member in (t,b,oracle):assert interface_check(member,request_builder=request)['all_passed']
            gold={stable(a) for a in t['teacher']['acceptable_actions']};prior={stable(a) for a in t['teacher']['prior_acceptable_actions']}
            checks.append(dict(id=t['id'],geometry=geometry_id(inp['game']),native=native,disjoint_from_prior=not(gold&prior),gold=t['teacher']['acceptable_actions'],prior_gold=t['teacher']['prior_acceptable_actions']))
        report['linear'][split]={'points':len(checks),'geometries':len({r['geometry'] for r in checks}),'disjoint':sum(r['disjoint_from_prior'] for r in checks),'checks':checks}
    rows=read(OUT/'bp_train.jsonl');baseline=read(SOURCE/'bp_train.jsonl')
    for horizon in (50,194,512):
        exposure=Counter();used=budget=0
        for s in range(horizon):
            batch=select(rows,s,42);cap=len(old(baseline,s,42))
            assert len(batch)<=cap
            used+=len(batch);budget+=cap;exposure.update(t['id'] for t in batch)
        report[str(horizon)]=dict(task_groups=used,v4_task_group_cap=budget,distinct=len(exposure),total=len(rows),practice={})
        for role in ('bridge','history','reduced','result'):
            ts=[t for t in rows if role in t['practice_units']]
            report[str(horizon)]['practice'][role]=dict(tasks=len(ts),min_groups=min(exposure[t['id']] for t in ts),max_groups=max(exposure[t['id']] for t in ts))
    assert report['512']['distinct']==len(rows)
    report['scope']='Native teacher and scheduled task groups only; no model calls. Per-step group cap does not imply identical completion token usage.'
    (OUT/'exposure_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:({s:{kk:vv for kk,vv in v.items() if kk!='checks'} for s,v in val.items()} if k=='linear' else val) for k,val in report.items()},indent=2))

if __name__=='__main__':main()
