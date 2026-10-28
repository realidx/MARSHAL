"""Package reviewed structures, temporal controls, and explicit supplements."""
from copy import deepcopy
import json
from pathlib import Path

from training.b_sft.social_rollout import build
from training.b_sft.assemble_dataset import record_id
from benac_p.endgame_diagnose import decode_action


def package(selection,audit_dir,output):
    if output.exists():raise ValueError('Use a new output file')
    selected=json.loads(selection.read_text());fixtures={};links=[];starts=[]
    def add(raw):
        key=record_id(raw)
        if key not in fixtures:fixtures[key]=deepcopy(raw)
        return fixtures[key]['id']
    for c in selected:
        for r in c['records']:
            if r['split']!='development':raise ValueError('Do not mine held-out fixtures')
            add(r['fixture'])
    for i,c in enumerate(selected,1):
        a=json.loads((audit_dir/f'audit-{i}.json').read_text());raw=a['fixture'];left=add(raw)
        start=dict(raw,id=raw['id']+'-start',history=[]);starts.append(add(start))
        # Earlier actual ego decisions, not teacher-chosen hidden query positions.
        s,node,_,_=build(start,3000)
        for j,action in enumerate(raw['history']):
            if s.actor(node)==s.ego:add(dict(raw,id=raw['id']+f'-prefix-{j}',history=raw['history'][:j]))
            node=s._apply(node,decode_action(action))
        # Keep all audited arms. They are correlated branches, never counted as
        # independent games, and every available native P action retains its Q.
        for ai,arm in enumerate(a['arms']):
            for bi,b in enumerate(arm['branches']):
                child=dict(raw,id=raw['id']+f'-arm-{ai}-branch-{bi}',history=b['history'])
                right=add(child)
                links.append(dict(kind='temporal',left=left,right=right,action=arm['action'],evidence=b['evidence'],
                    reference_branch_weight=b['weight'],root_regret=arm['regret'],
                    note='Weight and regret are teacher-side; branch samples are correlated.'))
    own_path=audit_dir/'own_goal_candidates.json'
    for pair in json.loads(own_path.read_text()):
        left=add(pair['left']);right=add(pair['right'])
        links.append(dict(kind='contrast',contrast_type='own_goal_switch',left=left,right=right,
            note='Same physical state/history and partner posterior; own row is also public to the reference partners, so this is not a covert preference intervention.'))
    result=dict(version='reviewed-fixture-pack-v1',split='development',fixtures=list(fixtures.values()),links=links,
                protocol_episode_starts=starts,training_ready=False,
                inputs=dict(selection=str(selection),audits=str(audit_dir),own_contrasts=str(own_path)))
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return dict(fixtures=len(fixtures),links=len(links),protocol_starts=len(starts))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--selection',type=Path,required=True);p.add_argument('--audit-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(package(a.selection,a.audit_dir,a.output)))
