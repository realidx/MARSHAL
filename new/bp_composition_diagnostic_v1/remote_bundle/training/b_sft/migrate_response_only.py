"""Re-label existing B/P instances under response-only altruism; preserve splits.

Never reuse old labels on solver failure. Failed rows remain in the migration
ledger and block publication of a training-ready pack. No model calls.
"""
import argparse
from collections import Counter
from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np
from training.b_sft.decision_policy import VERSION
from training.b_sft.debug.audit_private_teaching import POLICY
from training.b_sft.debug.audit_readable_pretraining import reconstruct, independent_backward, VALUES
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native, observed_slots
from training.b_sft.social_bp_curriculum import acceptable, digest
from training.b_sft.social_p_qualitative import robust_actions
from training.b_sft.social_bp_training import reward, native_completion
from training.b_sft.social_named_probe import request, present
from training.b_sft.bp_semantics import semantic_id


def migrate(task, cache):
    t=deepcopy(task);inp=t['input'];old=deepcopy(t['teacher'])
    raw,own=reconstruct(inp)
    key=json.dumps([raw,inp['imposed_setup']],sort_keys=True)
    if key not in cache:
        root=PrivateEpisode(raw,inp['imposed_setup'],seconds=30,max_nodes=100000)
        cache[key]=(root,audit_native(root.tree),independent_backward(root.tree))
    root,native,independent=cache[key];e=copy(root)
    e.events=[]
    for event in inp['voluntary_history']:e.observe(event)
    node=e.tree.entries[e.index].node
    assert node.state.public_state()==inp['current_state']
    facts=[(f['player'],f['goal'],VALUES[f['preference']]) for f in inp['private_results']]
    teacher=dict(policy_sha256=e.tree.certificate['policy_sha256'],native=native,
                 objective_version=VERSION)
    if t['task']=='B':
        q=inp['queries'][0]
        b=e.belief(q['player'],q['goal'],observer=inp['observer'],own=own,private_results=facts)
        teacher.update(gold={k:b[k] for k in ('possible_preferences','favored')},preference_weights=b['preference_weights'])
        if 'previous_belief' in inp:
            before=copy(root);before.events=[]
            if inp.get('new_history'):
                for event in inp['voluntary_history'][:-len(inp['new_history'])]:before.observe(event)
                slots=observed_slots(before.tree.entries[before.index].node,inp['observer'])
                previous=before.belief(q['player'],q['goal'],observer=inp['observer'],own=own,
                                      private_results=[f for f in facts if f[:2] in slots])
            else:
                for event in inp['voluntary_history']:before.observe(event)
                weights=before.weights*np.array([w[inp['observer']]==own for w in before.tree.worlds]);weights/=weights.sum()
                marginal={name:sum(p for p,w in zip(weights,before.tree.worlds) if w[q['player']][q['goal']]==v) for name,v in VALUES.items()}
                possible=[v for v,p in marginal.items() if p>0]
                leaders=[v for v in possible if marginal[v]>=max(marginal.values())-1e-9]
                previous=dict(possible_preferences=possible,favored=leaders[0] if len(leaders)==1 else 'undetermined')
            inp['previous_belief']={k:previous[k] for k in ('possible_preferences','favored')}
        if 'response_certificate' in old:
            from training.b_sft.build_b_response_bridges import response_certificate
            teacher['response_certificate']=response_certificate(root,inp['voluntary_history'][0]['response'])
    else:
        choices=e.choices(own,facts)
        assert choices['actions']==inp['legal_actions']
        if 'qualitative_certificate' in old:
            payoffs=np.array([e.tree.values[c] for c in e.tree.entries[e.index].children])
            cert=robust_actions(payoffs,inp['player'],e.tree.worlds,old['claims'],own_tolerance=.1,
                social_tolerance=.1,envelopes=old['audit_envelopes'],offer_response=node.pending is not None)
            accepted=cert['acceptable']
            teacher.update(qualitative_certificate=cert,per_world_payoffs=payoffs.tolist(),
                           claims=old['claims'],audit_envelopes=old['audit_envelopes'],
                           worlds=[[list(row) for row in w] for w in e.tree.worlds])
        else:accepted=acceptable(choices['values'],inp['player'],actions=choices['actions'])
        if not accepted:raise ValueError('No certified P answer under new policy')
        teacher.update(acceptable_actions=[choices['actions'][i] for i in accepted],action_values=choices['values'],
                       all_legal_accepted=len(accepted)==len(choices['actions']))
        if 'information_positive' in t:
            teacher_query=all(a.get('action')=='INVESTIGATE' for a in teacher['acceptable_actions'])
            t['information_positive']=teacher_query
            queries=[i for i,a in enumerate(choices['actions']) if a.get('action')=='INVESTIGATE']
            ordinary=[i for i in range(len(choices['actions'])) if i not in queries]
            if queries and ordinary:
                teacher['own_query_margin']=max(choices['values'][i][inp['player']] for i in queries)-max(choices['values'][i][inp['player']] for i in ordinary)
    inp['partner_policy']=POLICY
    if 'instruction' in inp and t['task']=='P':
        from training.b_sft.decision_policy import DESCRIPTION
        inp['instruction']='Use the supplied current belief directly. '+DESCRIPTION+' Explain briefly and make one legal action tool call.'
    t['teacher']=teacher;t['training_ready']=False;t['objective_version']=VERSION;t['previous_task_id']=task['id']
    t['id']=digest((VERSION,task['id'],inp));t['native_task_id']=t['id'];t['semantic_id']=semantic_id(t)
    t['answer_signature']=json.dumps(teacher.get('gold',teacher.get('acceptable_actions')),sort_keys=True)
    t['migration_requires_curriculum_review']=bool(teacher.get('all_legal_accepted'))
    assert reward(t,native_completion(t))['reward']==1
    req=request(t,'action_tools',t.get('name_variant',0))
    if t.get('diagnostic_group'):
        from training.b_sft.b_chronological_prompt import render
        req['messages'][1]['content']=render(present(t,t.get('name_variant',0)))
    changed=old.get('gold',old.get('acceptable_actions'))!=teacher.get('gold',teacher.get('acceptable_actions'))
    return t,req,dict(id=t['id'],previous_id=task['id'],kind=t['task'],label_changed=changed,
                     prior_changed=inp.get('previous_belief')!=task['input'].get('previous_belief'),
                     independent_backward=independent,all_legal_accepted=teacher.get('all_legal_accepted',False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    tasks=[json.loads(s) for s in args.source.read_text().splitlines() if s.strip()]
    cache={};checks=[];failed=[];fresh=[];requests=[]
    for i,t in enumerate(tasks):
        try:
            row,req,check=migrate(t,cache);fresh.append(row);checks.append(check)
            requests.append(dict(task_id=row['id'],condition='chronological_tables' if row.get('diagnostic_group') else VERSION,request=req))
        except Exception as ex:
            failed.append(dict(id=t['id'],kind=t['task'],error=type(ex).__name__+': '+str(ex)))
        print(json.dumps(dict(processed=i+1,total=len(tasks),failed=len(failed))),flush=True)
    def write(name,rows):
        p=args.output/name;p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows));return hashlib.sha256(p.read_bytes()).hexdigest()
    files={'tasks.jsonl':write('tasks.jsonl',fresh),'requests.jsonl':write('requests.jsonl',requests)}
    summary=dict(objective_version=VERSION,source=str(args.source),source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                 source_count=len(tasks),migrated=len(fresh),failures=failed,files=files,checks=checks,
                 label_changes=dict(Counter(r['kind'] for r in checks if r['label_changed'])),
                 all_legal_accepted=sum(r['all_legal_accepted'] for r in checks),training_ready=False,
                 note='Recomputed labels only. Curriculum must be reviewed; failures cannot be silently omitted.')
    (args.output/'migration.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('checks','failures','files')}))
    if failed:raise SystemExit('Migration has unresolved rows; inspect migration.json')

if __name__=='__main__':main()
