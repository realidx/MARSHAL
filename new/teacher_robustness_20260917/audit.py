"""Development-only teacher sensitivity audit; no production mutations."""
import hashlib,json,sys,time
from collections import Counter
from copy import deepcopy
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.preference_contract import belief,NAMES,VALUES
from training.b_sft.social_bp_curriculum import acceptable
from training.social_mixed.structure_coverage import geometry_id
OUT=Path(__file__).parent
VARIANTS=[('default',{}),('first',dict(initialization='first')),('last',dict(initialization='last')),('forward',dict(order='ascending_player_ids')),('reverse',dict(order='descending_player_ids'))]
EPS=[0,.001,.01,.05,.1]

def posterior(e,inp,epsilon):
    weights=e.tree.world_weights.copy();index=0
    for event in inp['voluntary_history']:
        entry=e.tree.entries[index];actions=[a.to_dict() for a in entry.actions];ai=actions.index(event)
        weights*= (1-epsilon)*e.tree.policy[index][ai]+epsilon/len(actions)
        index=entry.children[ai]
    own=tuple({'want':1,'neutral':0,'avoid':-1}[inp['own_preferences'][f'goal_{g}']] for g in range(len(inp['game']['goals'])))
    facts=inp['private_results']
    mask=np.array([w[inp['player']]==own and all(w[f['player']][f['goal']]==dict(zip(NAMES,VALUES))[f['preference']] for f in facts) for w in e.tree.worlds])
    weights*=mask
    evidence=float(weights.sum())
    if evidence==0:return None,index,evidence
    return weights/evidence,index,evidence

def label(e,t,weights,index):
    if t['task']=='B':
        q=t['input']['queries'][0]
        mass={n:float(sum(p for p,w in zip(weights,e.tree.worlds) if w[q['player']][q['goal']]==v)) for n,v in zip(NAMES,VALUES)}
        return dict(label=belief(mass),marginal=mass)
    entry=e.tree.entries[index];actions=[a.to_dict() for a in entry.actions]
    values=np.array([np.einsum('wp,w->p',e.tree.values[c],weights) for c in entry.children])
    chosen=acceptable(values,t['input']['player'],actions=actions)
    return dict(label=[actions[a] for a in chosen],action_values=values.tolist(),actions=actions)

def policy_digest(tree):
    # Reference hash includes solver metadata: use probabilities alone to compare strategies.
    h=hashlib.sha256()
    for p in tree.policy:
        if p is not None:h.update(p.tobytes())
    return h.hexdigest()

def main():
    source=ROOT/'examples/social_mixed/data_distribution_v2/bp_train.jsonl'
    rows=[json.loads(s) for s in source.read_text().splitlines()]
    pool=sorted((t for t in rows if t['background_profile']=='balanced'),key=lambda t:t['id'])
    chosen=[];seen=set();counts=Counter()
    for t in pool:
        k=t['kernel']
        if k in ('B1','B2'):
            role='full' if len(t['teacher']['gold']['possible_preferences'])==3 else 'reduced'
            cell=(k,role);family=geometry_id(t['input']['game'])
            if counts[cell]>=2 or (cell,family) in seen:continue
            counts[cell]+=1;seen.add((cell,family));chosen.append(t)
    for case in ('acquisition','deadline','target_selection','opportunity_cost','ordinary_alternative','answer_use'):
        candidates=[t for t in pool if t['kernel']=='P4' and t.get('p4_case')==case and t['completion_mode']=='binary']
        if candidates:chosen.append(candidates[0])
    freeze=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),ids=[t['id'] for t in chosen],variants=VARIANTS,epsilons=EPS,selection='balanced training only; up to two geometries per B1/B2 support role, one binary P4 per case; lexical ID order; no model outcomes')
    (OUT/'selection.json').write_text(json.dumps(freeze,indent=2)+'\n')
    results=[]
    with (OUT/'results.jsonl').open('w') as stream:
        for t in chosen:
            baseline=None;basepolicy=None
            for name,options in VARIANTS:
                start=time.monotonic();r=dict(id=t['id'],kernel=t['kernel'],case=t.get('p4_case'),structure_family=geometry_id(t['input']['game']),variant=name)
                try:
                    inp=deepcopy(t['input']);raw,_=reconstruct(inp);raw['background_prior']=inp['background_prior']
                    solver_options=dict(options)
                    order=solver_options.pop('order',None)
                    if order:solver_options['audit_update_order']=list(range(raw['game']['n_players']))[::(-1 if name=='reverse' else 1)]
                    e=PrivateEpisode(raw,inp['imposed_setup'],seconds=45,max_nodes=80000,max_sweeps=128,**solver_options)
                    r.update(status='solved',certificate=e.tree.certificate,native=audit_native(e.tree),policy_probabilities_sha256=policy_digest(e.tree))
                    w,index,ev=posterior(e,inp,0);r['history_evidence_mass']=ev
                    if w is None:r['history_status']='impossible'
                    else:
                        r['history_status']='reachable';r.update(label(e,t,w,index))
                        if name=='default':
                            expected=t['teacher']['gold'] if t['task']=='B' else t['teacher']['acceptable_actions']
                            if r['label']!=expected:raise ValueError('Baseline differs from production gold')
                            baseline=r['label'];basepolicy=r['policy_probabilities_sha256']
                        else:
                            r['label_changed']=r['label']!=baseline
                            r['policy_changed']=r['policy_probabilities_sha256']!=basepolicy
                    if name=='default' and t['task']=='B':
                        r['noise']=[]
                        for eps in EPS:
                            nw,ni,nev=posterior(e,inp,eps);item=dict(epsilon=eps,evidence_mass=nev,**label(e,t,nw,ni))
                            item['mass_excluded_by_default']=sum(p for n,p in item['marginal'].items() if n not in baseline['possible_preferences'])
                            item['label_changed']=item['label']!=baseline
                            r['noise'].append(item)
                except Exception as exc:r.update(status='failed',error=f'{type(exc).__name__}: {exc}')
                r['seconds']=round(time.monotonic()-start,3);results.append(r);stream.write(json.dumps(r)+'\n');stream.flush()
                print(json.dumps({k:v for k,v in r.items() if k in ('id','kernel','variant','status','history_status','label_changed','policy_changed','error','seconds')}),flush=True)
    summary=dict(tasks=len(chosen),structures=len({r['structure_family'] for r in results}),statuses=dict(Counter(r['status'] for r in results)),alternatives=[{k:r.get(k) for k in ('id','variant','status','history_status','label_changed','policy_changed','error')} for r in results if r['variant']!='default'])
    summary['noise']={str(eps):dict(cases=sum('noise' in r for r in results),changed=sum(n['label_changed'] for r in results for n in r.get('noise',[]) if n['epsilon']==eps),max_excluded_mass=max([n['mass_excluded_by_default'] for r in results for n in r.get('noise',[]) if n['epsilon']==eps],default=0)) for eps in EPS}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if __name__=='__main__':main()
