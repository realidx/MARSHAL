"""Explain sparse S without changing the game, reference or production labels."""
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_k]='1'

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import numpy as np
import scipy

from new.three_player_complexity_v1_20261023.common import ROOT, write, sha, identity, stable
from new.three_player_complexity_v1_20261023.worker import tree_for, load
from new.node_qs_audit_v1_20261023.metrics import Observations, forest_response, EPS
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.b_sft.social_private_teacher import observed_slots

VERSION='H2-sparse-S-causes-v1'
REG=ROOT/'examples/strategic_slices/versions/H2_sparse_S_causes_v1_20261024/SNAPSHOT.json'
RUN=ROOT/'new/three_player_complexity_v1_20261023/local_H2_33_v1'


def snapshot(out, config, inputs):
    reg=json.loads(REG.read_text())
    assert reg['version']==VERSION
    for p,h in reg['source_hashes'].items():assert sha(ROOT/p)==h,p
    out.mkdir(parents=True,exist_ok=False)
    for p in reg['source_hashes']:
        target=out/'source'/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,target)
    shutil.copyfile(REG,out/'registered_snapshot_at_start.json')
    write(out/'pipeline_snapshot.json',dict(version=VERSION,actual_argv=sys.argv,resolved_config=config,
        registration_sha256=sha(REG),source_hashes=reg['source_hashes'],inputs=inputs,
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,scipy=scipy.__version__,
            platform=platform.platform(),threads={k:os.environ.get(k,'NOT_RECORDED')for k in
                ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        model='NOT_USED',D='NOT_MEASURED',prompt='NOT_CHANGED',training='NOT_RUN',
        production_active='terminal-node-regret-grpo-readable-v8'))


def inputs_and_results():
    results=[r for r in json.loads((RUN/'results.json').read_text())if r.get('labels')=='MEASURED']
    jobs={j['index']:j for j in json.loads((RUN/'jobs.json').read_text())}
    inputs={name:identity(RUN/name)for name in ('results.json','jobs.json','pipeline_snapshot.json')}
    for r in results:
        folder=RUN/Path(r['result_path']).parent
        for name,h in [('labels.jsonl.gz',r['labels_sha256']),('reference.npz',r['reference_sha256'])]:
            assert sha(folder/name)==h
            inputs[f"{r['index']}:{name}"]=identity(folder/name)
    return results,jobs,inputs


def read_rows(result):
    folder=RUN/Path(result['result_path']).parent
    with gzip.open(folder/'labels.jsonl.gz','rt')as stream:return list(map(json.loads,stream))


def single_positive(row):return max(row['S_private'],row['S_history'])>EPS


def private_groups(rows):
    groups=defaultdict(list)
    for row in rows:
        for item in row['S_items']:
            if item['omitted'][0]!='private':continue
            mask=tuple(item['omitted']);others=tuple(tuple(a)for a in row['private_answers']if tuple(a[:2])!=mask[1:])
            key=(row['actor'],row['node'],tuple(row['own_type']),others,mask)
            groups[key].append((row,item))
    for members in groups.values():
        assert all(item['full_contexts']==len(members)for _,item in members),'Private grouping differs from recorded omission forest'
    return groups


def labels(args):
    results,jobs,inputs=inputs_and_results()
    snapshot(args.output,dict(operation='All31 stored-label causal triage, no solver or label changes',
        epsilon=EPS,denominator='Current node/information cell; also report eligible subsets',
        singleton='Full observed context uniquely recoverable among positive-CF contexts after this omission',
        private_grouping='Same public node, own type, other answers, omitted cell; checked against stored full_contexts'),inputs)
    total={s:Counter()for s in ('all','on_reference')};items=defaultdict(Counter);buckets=defaultdict(Counter)
    groups_total=Counter();per_game=[];positive_values=[];examples=defaultdict(list)
    for result in results:
        rows=read_rows(result);local=Counter()
        for row in rows:
            eligible=bool(row['S_items']);ambiguous=any(i['full_contexts']>1 for i in row['S_items'])
            positive=single_positive(row);flat=row['span']<=EPS
            reason=('no_omittable_item'if not eligible else 'all_single_omissions_recoverable'if not ambiguous
                else 'ambiguous_positive_S'if positive else 'ambiguous_zero_S')
            local[reason]+=1
            for scope in ('all','on_reference'):
                if scope=='on_reference'and row['reference_mass']<=0:continue
                c=total[scope];c['contexts']+=1;c[reason]+=1;c['own_action_Q_flat']+=flat
                c['ambiguous_and_Q_nonflat']+=ambiguous and not flat
                c['positive_S_and_Q_nonflat']+=positive and not flat
                c['positive_S_and_Q_flat']+=positive and flat
                buckets[f'{scope}:{row["phase"]}:turn{row["turn"]}'][reason]+=1
            if len(examples[reason])<3:examples[reason].append(dict(original=result['original_index'],node=row['node'],cell=row['cell'],span=row['span']))
            for item in row['S_items']:
                channel=item['omitted'][0];c=items[channel];c['items']+=1
                c['singleton']+=item['full_contexts']==1;c['ambiguous']+=item['full_contexts']>1
                c['ambiguous_positive']+=item['full_contexts']>1 and item['S']>EPS
                c['ambiguous_zero']+=item['full_contexts']>1 and item['S']<=EPS
                value=item['S']
                c['exact_zero']+=value==0;c['roundoff_0_to_1e12']+=0<value<=1e-12
                c['between_1e12_and_EPS']+=1e-12<value<=EPS
                if value>EPS:positive_values.append(value)
        pg=Counter()
        for members in private_groups(rows).values():
            if len(members)==1:pg['answer_recoverable_singleton']+=1;continue
            positives=sum(item['S']>EPS for _,item in members)
            common=set(range(len(members[0][0]['actions'])))
            for row,_ in members:
                common&={i for i,q in enumerate(row['Q'])if max(row['Q'])-q<=EPS}
            kind=('ambiguous_all_zero'if positives==0 else 'ambiguous_all_positive'if positives==len(members)else 'ambiguous_mixed')
            pg[kind]+=1;pg[kind+':common_current_optimal']+=bool(common)
            pg[kind+':contexts']+=len(members)
        groups_total.update(pg)
        per_game.append(dict(index=result['index'],original_index=result['original_index'],goals=len(jobs[result['index']]['raw']['game']['goals']),
            private_positive=result['summary']['counterfactual']['private_S_positive'],history_positive=result['summary']['counterfactual']['history_S_positive'],
            contexts=len(rows),reasons=dict(local),private_groups=dict(pg)))
    # Prespecified coverage of positive/zero parents, goal counts and known signal control.
    roles=defaultdict(list)
    for goals in (3,4):
        positive=[g for g in per_game if g['goals']==goals and g['private_positive']>0]
        zeros=[g for g in per_game if g['goals']==goals and g['private_positive']==g['history_positive']==0]
        for g in positive[:1]:roles[g['index']].append(f'first_private_positive_{goals}_goals')
        for g in zeros[:1 if goals==3 else 2]:roles[g['index']].append(f'first_zero_S_{goals}_goals')
    for g in per_game:
        if g['original_index']==35:roles[g['index']].append('known_signalling_control')
    sample=[dict(index=i,original_index=jobs[i]['original_index'],roles=roles[i])for i in sorted(roles)]
    report=dict(measured=31,missing_original_indices=[46,76],counts=total,item_counts=items,stage_counts=buckets,
        private_group_counts=groups_total,minimum_S_above_EPS=min(positive_values),maximum_S=max(positive_values),
        per_game=per_game,examples=examples,D='NOT_MEASURED',interpretation='Singleton recovery is relative to retained observations and frozen-reference support, not universal logical inference.')
    write(args.output/'LABEL_AUDIT.json',report);write(args.output/'SAMPLE_JOBS.json',sample)
    write(args.output/'COMPLETE.json',dict(audit_sha256=sha(args.output/'LABEL_AUDIT.json'),sample_sha256=sha(args.output/'SAMPLE_JOBS.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps({k:report[k]for k in ('counts','item_counts','private_group_counts','minimum_S_above_EPS')},ensure_ascii=False,indent=2));print('probe_sample',sample)


class EntryOmissions(Observations):
    """Drop only evidence present before entry; keep future observations."""
    def key(self,index,wi,omitted=None):
        if omitted is None or omitted[0]in ('private','history'):return super().key(index,wi,omitted)
        mode,cutoff=omitted;cache=(index,omitted)
        if cache not in self.base:
            entry=self.tree.entries[index];state=entry.node.state
            events=[e.to_dict()for e in state.transcript]
            history=[e for e in events if e['turn_index']>=cutoff]
            old_answers={(e['player'],e['goal'])for e in events if e['turn_index']<cutoff
                and e['proposer_id']==self.focal and e['action']=='INVESTIGATE'}
            self.base[cache]=stable(dict(turn=state.turn_index,commitments=state.snapshot_commitments(),
                query_used=state.query_used,offer_used=state.offer_used,
                pending=None if entry.node.pending is None else entry.node.pending.to_dict(),
                legal=[a.to_dict()for a in entry.actions],history=history))
            self.slots[cache]=tuple(slot for slot in observed_slots(entry.node,self.focal)
                if mode=='all_entry_history'or slot not in old_answers)
        world=self.tree.worlds[wi]
        return self.base[cache],world[self.focal],tuple((p,g,world[p][g])for p,g in self.slots[cache])


def roots_for(tree,members):
    roots={}
    for row in members:roots.setdefault(row['node'],np.zeros(tree.w))[row['world_ids']]=row['counterfactual_mass']*np.array(row['posterior'])
    return roots


def control_bounds(tree,focal,deadline):
    lo=np.empty((len(tree.entries),tree.w));hi=np.empty_like(lo)
    for i in reversed(range(len(tree.entries))):
        if i%512==0 and time.monotonic()>deadline:raise TimeoutError('control-bound soft budget')
        entry=tree.entries[i]
        if entry.actor is None:lo[i]=hi[i]=entry.payoff[:,focal]
        elif entry.actor==focal:
            lo[i]=lo[list(entry.children)].min(axis=0);hi[i]=hi[list(entry.children)].max(axis=0)
        else:
            lo[i]=np.einsum('aw,aw->w',tree.policy[i],lo[list(entry.children)]);hi[i]=np.einsum('aw,aw->w',tree.policy[i],hi[list(entry.children)])
    return lo,hi


def probe_case(result,job,folder,seconds):
    start=time.monotonic();request=json.loads((RUN/Path(result['result_path']).parent/'request.json').read_text())
    def progress(phase):write(folder/'progress.json',dict(phase=phase,elapsed_seconds=time.monotonic()-start))
    progress('construct');tree=tree_for(job,request['config']);assert not tree.cutoff_leaves
    load(tree,RUN/result['reference_path']);tree.deadline=float('inf');rows=read_rows(result)
    deadline=time.monotonic()+seconds;counts=Counter();composites={};witnesses=[];lp_checks=[];invariants=0
    for focal in range(tree.n):
        progress(f'control_bounds_player{focal}');lo,hi=control_bounds(tree,focal,deadline)
        local=[r for r in rows if r['actor']==focal];obs=EntryOmissions(tree,focal);original=Observations(tree,focal)
        for row in local:
            width=float(np.array(row['posterior'])@(hi[row['node'],row['world_ids']]-lo[row['node'],row['world_ids']]))
            counts['contexts']+=1;counts['no_future_own_payoff_control']+=width<=EPS
            counts['ambiguous_and_no_future_control']+=width<=EPS and any(i['full_contexts']>1 for i in row['S_items'])
        del lo,hi
        # Cutoff0 must erase nothing, including answers obtained after entry.
        for i in range(0,len(tree.entries),257):
            for mode in ('all_entry_history','all_entry_allowed'):
                assert obs.key(i,0,(mode,0))==original.key(i,0,None)
                invariants+=1
        for mode in ('all_entry_history','all_entry_allowed'):
            progress(f'{mode}_player{focal}');groups=defaultdict(list);stats=composites.setdefault(mode,Counter());best=None
            for row in local:
                mask=(mode,row['turn']);key=obs.key(row['node'],row['world_ids'][0],mask)
                groups[(mask,key)].append(row)
            for (mask,key),members in groups.items():
                if time.monotonic()>deadline:raise TimeoutError('composite-omission soft budget')
                stats['groups']+=1;stats['contexts']+=len(members)
                if len(members)==1:stats['singleton_groups']+=1;continue
                roots=roots_for(tree,members);solved=forest_response(tree,focal,roots,omitted=mask,observations=obs)
                losses=[]
                for row in members:
                    value=float(np.array(row['posterior'])@solved['values'][row['node']][row['world_ids'],focal])
                    loss=max(row['Q'])-value;assert loss>=-1e-7
                    loss=max(0.,loss);stats['positive_contexts']+=loss>EPS
                    stats['new_positive_over_single_item_S']+=loss>EPS and not single_positive(row)
                    losses.append(loss)
                score=max(losses)
                if score>EPS and (best is None or score>best[0]):best=(score,members,mask,roots,solved,losses)
            if best is not None:
                score,members,mask,roots,solved,losses=best;chosen=members[int(np.argmax(losses))]
                weights=sum(m.sum()for m in roots.values())
                dp=sum(float(m@solved['values'][i][:,focal])for i,m in roots.items())/weights
                lp=sequence_lp(tree,focal,roots,omitted=mask,observations=obs)
                assert abs(lp['V_omitted_LP']-dp)<1e-7
                lp_checks.append(dict(mode=mode,focal=focal,LP_matches=True,dp=dp,**lp))
                wi=chosen['world_ids'][int(np.flatnonzero(np.array(chosen['posterior'])>0)[0])]
                probs=solved['root_policy'][chosen['node']][:,wi]
                witnesses.append(dict(mode=mode,actor=focal,node=chosen['node'],cell=chosen['cell'],
                    S_diagnostic=score,single_item_S=max(chosen['S_private'],chosen['S_history']),
                    entry_action_regret=max(0.,max(chosen['Q'])-float(probs@chosen['Q'])),
                    own_type=chosen['own_type'],private_answers=chosen['private_answers'],Q=chosen['Q'],actions=chosen['actions'],
                    history=[e.to_dict()for e in tree.entries[chosen['node']].node.state.transcript],
                    retained_commitments=tree.entries[chosen['node']].node.state.snapshot_commitments(),
                    reference_mass=chosen['reference_mass'],merged_contexts=len(members)))
        del obs,original
    # Independent check of one challenging recorded zero: ambiguity + nonflat Q.
    candidates=[members for members in private_groups(rows).values()if len(members)>1
        and all(item['S']<=EPS for _,item in members)and max(r['span']for r,_ in members)>EPS]
    if candidates:
        members=max(candidates,key=lambda ms:(max(r['span']for r,_ in ms),max(r['reference_mass']for r,_ in ms),-ms[0][0]['node']))
        records=[r for r,_ in members];focal=records[0]['actor'];mask=tuple(members[0][1]['omitted']);obs=Observations(tree,focal)
        key=obs.key(records[0]['node'],records[0]['world_ids'][0],mask)
        assert all(obs.key(r['node'],r['world_ids'][0],mask)==key for r in records)
        roots=roots_for(tree,records);total=sum(m.sum()for m in roots.values())
        full=sum(r['counterfactual_mass']*max(r['Q'])for r in records)/total
        lp=sequence_lp(tree,focal,roots,omitted=mask,observations=obs)
        assert abs(lp['V_omitted_LP']-full)<1e-7
        lp_checks.append(dict(mode='recorded_ambiguous_zero_private_S',focal=focal,node=records[0]['node'],
            LP_matches=True,full_information_value=full,**lp))
    return dict(index=result['index'],original_index=result['original_index'],status='COMPLETED',counts=counts,
        composites=composites,witnesses=witnesses,LP_checks=lp_checks,future_observation_invariants=invariants,
        elapsed_seconds=time.monotonic()-start)


def probes(args):
    results,jobs,inputs=inputs_and_results();by_index={r['index']:r for r in results}
    sample_path=args.audit/'SAMPLE_JOBS.json';sample=json.loads(sample_path.read_text());inputs['sample']=identity(sample_path)
    if args.indices!='all':
        chosen=set(map(int,args.indices.split(',')));sample=[s for s in sample if s['index']in chosen]
        assert len(sample)==len(chosen)
    snapshot(args.output,dict(operation='Prespecified full-parent sparse-S mechanism probes',sample=sample,
        probe_soft_seconds_per_case=args.seconds,construct_seconds=180,workers=1,
        diagnostic_only='Jointly omit entry-time evidence; retain all new post-entry history/answers and physical facts',
        control_bound='Perfect-information per-world focal max/min under fixed opponents, to certify no own payoff control',
        LP='Independent own-payoff sequence LP; conservative social relaxation; existing60-second LP limits',
        S_contract='Original single-item S preserved; composite values never substituted as labels'),inputs)
    output=[]
    for selected in sample:
        folder=args.output/'cases'/str(selected['index']);folder.mkdir(parents=True)
        try:result=probe_case(by_index[selected['index']],jobs[selected['index']],folder,args.seconds)
        except Exception as exc:
            import traceback
            result=dict(index=selected['index'],original_index=selected['original_index'],status='FAILED',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
        write(folder/'RESULT.json',result);output.append(result);write(args.output/'RESULTS.json',output)
        print(dict(index=result['index'],original=result['original_index'],status=result['status'],counts=result.get('counts'),composites=result.get('composites'),error=result.get('error')),flush=True)
    write(args.output/'COMPLETE.json',dict(requested=len(sample),completed=sum(r['status']=='COMPLETED'for r in output),
        failed=[r['original_index']for r in output if r['status']!='COMPLETED'],results_sha256=sha(args.output/'RESULTS.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['labels','probe']);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--audit',type=Path);parser.add_argument('--indices',default='all');parser.add_argument('--seconds',type=float,default=300.)
    args=parser.parse_args()
    if args.operation=='labels':labels(args)
    else:
        assert args.audit is not None and args.seconds>0
        probes(args)


if __name__=='__main__':main()
