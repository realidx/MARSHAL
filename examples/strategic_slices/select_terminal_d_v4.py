"""Select 100 train-only windows from verified full-trajectory D evidence.

Protect active acquisition windows and complete train entry-answer relations.
D is a noisy ranking feature, not a sign filter; failures retain null rewards.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from training.strategic_slices.common import file_hash, write_json, write_rows
from training.strategic_slices.terminal_d import load_dataset
from training.strategic_slices.terminal_analysis import require


def allocate(counts, total=100):
    scaled={k:total*v/sum(counts.values()) for k,v in counts.items()}
    result={k:int(v) for k,v in scaled.items()}
    for k in sorted(result,key=lambda k:(-(scaled[k]-result[k]),str(k)))[:total-sum(result.values())]:result[k]+=1
    return result


def choose(data, metrics, measured):
    train=[r for r in data.candidates if r['split']=='train']
    relations=[r for r in data.entry_answer_relations if r['split']=='train']
    protected={r['id'] for r in train if (r['information_channels'].get('query_answer') or 0)>.05}
    protected.update(cid for group in relations for cid in group['candidate_ids'])
    eligible=[r for r in train if r['id'] in protected or (metrics[r['id']]['completed']>0 and (
        metrics[r['id']]['decision_gap_or_completion_contrast'] or metrics[r['id']]['any_step_value_contrast']))]
    eligible.sort(key=lambda r:r['id'])
    require(len(eligible)>=100,'Fewer than 100 train questions meet the observed-signal rule')
    pids=sorted({r['parent_id'] for r in eligible});families=sorted({r['family'] for r in eligible})
    protected_families=Counter(r['family'] for r in eligible if r['id'] in protected)
    family_caps={family:max(8,protected_families[family]) for family in families}
    dimensions={
        'k':lambda r:str(r['k']),
        'players':lambda r:str(data.parents[r['parent_id']]['players']),
        'decision_kind':lambda r:r['decision_kind']}
    targets={name:allocate(Counter(fn(r) for r in train)) for name,fn in dimensions.items()}
    categories=[(name,value,target) for name,values in targets.items() for value,target in values.items()]
    n=len(eligible);p_offset=n;f_offset=n+len(pids);s_offset=f_offset+len(families);size=s_offset+2*len(categories)
    objective=np.zeros(size);integrality=np.zeros(size);integrality[:s_offset]=1
    lower=np.zeros(size);upper=np.full(size,np.inf);upper[:s_offset]=1
    rank=[]
    for i,r in enumerate(eligible):
        m=metrics[r['id']];d=measured[r['id']]['D_completed_only']['mean'];c=r['C_span']
        parts=dict(any_step_contrast=4.*m['any_step_value_contrast'],
                   mixed_completion=.25*m['mixed_completion'],
                   normalized_gap_spread=min(1.,(m['decision_gap_span_completed'] or 0)/c),
                   normalized_D=.5*float(np.clip((d or 0)/c,-1,1)))
        rank.append(dict(slice_id=r['id'],components=parts,score=sum(parts.values())))
        objective[i]=-sum(parts.values())+i*1e-8
        if r['id'] in protected:lower[i]=1
    objective[p_offset:f_offset]=-3 # reward distinct parents
    objective[f_offset:s_offset]=-10 # reward distinct structural families
    objective[s_offset:]=2 # soft balance targets, absolute count deviation
    constraints=[]
    def add(coeff,lo,hi):constraints.append((coeff,lo,hi))
    add({i:1 for i in range(n)},100,100)
    for offset,labels,key,cap in ((p_offset,pids,'parent_id',4),(f_offset,families,'family',8)):
        for j,label in enumerate(labels):
            inds=[i for i,r in enumerate(eligible) if r[key]==label];y=offset+j
            limit=family_caps[label] if key=='family' else cap
            add({**{i:1 for i in inds},y:-limit},-np.inf,0)
            add({**{i:-1 for i in inds},y:1},-np.inf,0)
    for j,(dimension,value,target) in enumerate(categories):
        coeff={i:1 for i,r in enumerate(eligible) if dimensions[dimension](r)==value}
        coeff[s_offset+2*j]=-1;coeff[s_offset+2*j+1]=1
        add(coeff,target,target)
    matrix=lil_matrix((len(constraints),size))
    for j,(coeff,_,_) in enumerate(constraints):
        for i,v in coeff.items():matrix[j,i]=v
    result=milp(objective,integrality=integrality,bounds=Bounds(lower,upper),
        constraints=LinearConstraint(matrix.tocsr(),[x[1] for x in constraints],[x[2] for x in constraints]),
        options=dict(time_limit=60,mip_rel_gap=0))
    require(result.success,'Selection optimizer did not certify an optimum: '+result.message)
    selected=[r for i,r in enumerate(eligible) if result.x[i]>.5]
    ids={r['id'] for r in selected}
    require(len(ids)==100 and protected<=ids,'Missing selected/protected questions')
    require(all(r['split']=='train' for r in selected),'Held-out selection leakage')
    require(max(Counter(r['parent_id'] for r in selected).values())<=4,'Parent cap exceeded')
    require(all(n<=family_caps[f] for f,n in Counter(r['family'] for r in selected).items()),'Family cap exceeded')
    return selected,dict(eligible=len(eligible),protected=len(protected),protected_ids=sorted(protected),
        targets=targets,actual={name:dict(Counter(fn(r) for r in selected)) for name,fn in dimensions.items()},
        selected_parents=len({r['parent_id'] for r in selected}),selected_families=len({r['family'] for r in selected}),
        family_cap_exceptions={f:n for f,n in family_caps.items() if n>8},
        entry_answer_groups=len(relations),strong_acquisition_slices=sum(metrics[r['id']]['strong_acquisition'] for r in selected),
        optimizer_status=result.message,objective=float(result.fun),relative_optimality_gap=float(result.mip_gap),
        rule='Train only; protect all S_query>.05 windows and every member of train entry-answer groups. Others need observed full-window decision-gap spread, same-prompt any-step contrast or mixed completion, with at least one completion. Max four per parent; family cap is max(8, mandatory protected members), with exceptions recorded. Objective: 10 per family + 3 per parent + recorded signal/D components, minus 2 per absolute quota deviation. Quotas follow train candidate metadata. ID order provides a tiny deterministic preference. No D-sign or all-eight-complete filter.',
        source_metrics='D_completed_only is used explicitly for incomplete questions; no failed utility is imputed. Decision gap sums are separate diagnostics, not redefinitions of D/C/S.',
        scores=[r for r in rank if r['slice_id'] in ids])


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4'))
    cli.add_argument('--analysis',type=Path,default=Path('new/local_data/strategic_slices_terminal_d_v4_analysis'))
    cli.add_argument('--output',type=Path,default=Path('new/local_data/strategic_slices_terminal_selected_v4'))
    args=cli.parse_args();require(not args.output.exists(),'Use a new selection output directory')
    proof=json.loads((args.analysis/'COMPLETE.json').read_text())
    for name,sha in proof['files'].items():require(file_hash(args.analysis/name)==sha,'Analysis evidence changed')
    data=load_dataset(args.data)
    merge=json.loads((args.analysis/'MERGE.json').read_text())
    require(merge['dataset_sha256']==file_hash(args.data/'manifest.json'),'Dataset/analysis mismatch')
    metrics={r['slice_id']:r for r in map(json.loads,(args.analysis/'trajectory_metrics.jsonl').read_text().splitlines())}
    measured={r['slice_id']:r for r in map(json.loads,(args.analysis/'merged_slices.jsonl').read_text().splitlines())}
    selected,report=choose(data,metrics,measured)
    args.output.mkdir(parents=True)
    write_rows(args.output/'candidates.jsonl',selected)
    ids={r['id'] for r in selected};pids={r['parent_id'] for r in selected}
    write_rows(args.output/'metrics.jsonl',[dict(measurement=measured[r['id']],trajectory=metrics[r['id']]) for r in selected])
    write_rows(args.output/'entry_answer_relations.jsonl',[r for r in data.entry_answer_relations if set(r['candidate_ids'])<=ids])
    write_json(args.output/'SELECTION.json',dict(report,dataset_path=str(args.data),
        dataset_sha256=merge['dataset_sha256'],analysis_path=str(args.analysis),analysis_complete_sha256=file_hash(args.analysis/'COMPLETE.json'),
        script_sha256=file_hash(Path(__file__)),reference_files={data.references[r['reference_id']]['file']:file_hash(args.data/data.references[r['reference_id']]['file']) for r in selected},
        parent_ids=sorted(pids),training_run_performed=False,new_model_calls=0,
        artifact_scope='Selected candidate records plus evidence; references remain in the frozen v4 pool. Not a generated supervision corpus or training-runtime export.'))
    write_json(args.output/'COMPLETE.json',dict(files={p.name:file_hash(p) for p in args.output.iterdir() if p.is_file()}))
    print(json.dumps({k:v for k,v in report.items() if k not in ('scores','protected_ids')},indent=2))


if __name__=='__main__':main()
