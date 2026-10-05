"""Package calibrated terminal entry sets for review, not the single-root trainer."""
import argparse,json,shutil
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from examples.strategic_slices.check_entry_information import restore
from training.strategic_slices.build import structural_family
from training.strategic_slices.common import digest,file_hash,write_json,write_rows
from training.strategic_slices.values import window_values


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_native_entry_search_v1'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--extra-source',type=Path,action='append',default=[])
    a=p.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=True);(out/'references').mkdir(exist_ok=True)
    sources=[a.source,*a.extra_source];parents=[];candidates=[];ledger=[];seen_parents=set()
    source_records=[(source,record) for source in sources for record in json.loads((source/'summary.json').read_text())['results']]
    for source,record in source_records:
        index=record['index']
        if record['status']!='verified':ledger.append(dict(source=str(source),index=index,status=record['status'],oracle_label=None));continue
        raw=json.loads((source/f'raw_{index}.json').read_text());pid=digest(raw)[:24]
        if pid in seen_parents:
            ledger.append(dict(source=str(source),index=index,status='duplicate_parent',parent_id=pid));continue
        seen_parents.add(pid)
        tree=restore(dict(raw=raw),dict(full_certificate=record['certificate']),source/f'reference_{index}.npz')
        family=structural_family(raw['game']);ref=f'references/{pid}.npz'
        shutil.copy(source/f'reference_{index}.npz',out/ref)
        parents.append(dict(id=pid,family=family,raw=raw,source_seed=record.get('seed',2026100600+index),players=raw['game']['n_players'],source=str(source),
            origin=record.get('origin',dict(kind='native-random')),
            reference_file=ref,reference_sha256=file_hash(out/ref),certificate=record['certificate'],native_audit=record['audit']))
        groups=defaultdict(list)
        for row in record['rows']:
            group_id=digest((pid,row['ego'],row['inputs']))[:24];groups[group_id].append(row)
        accepted=[]
        for group_id,rows in groups.items():
            previous_c=previous_s=0.
            for row in sorted(rows,key=lambda r:r['k']):
                total=sum(sum(e['world_masses']) for e in row['inputs']);members=[];vmax=vmin=0.
                for e in row['inputs']:
                    m=np.array(e['world_masses']);p_h=float(m.sum()/total)
                    metric=window_values(tree,row['ego'],e['root_index'],m,row['k'])
                    vmax+=p_h*metric['V_star'];vmin+=p_h*metric['V_min']
                    details=next(d for d in row['details'] if d['index']==e['root_index'])
                    members.append(dict(root_index=e['root_index'],history=details['history'],probability=p_h,
                        world_weights=(m/m.sum()).tolist(),joint_world_masses=(m/total).tolist(),
                        remaining_proposals=len(tree.rules.spec.round_robin)-tree.entries[e['root_index']].node.state.turn_index,
                        **metric))
                c=vmax-vmin;s=row['S'];assert abs(vmax-row['V_full'])<1e-7
                eligible=c>.1 and (row['k']==1 or c-previous_c>.05 or s-previous_s>.05)
                previous_c=c
                if c>.1:previous_s=s
                if eligible:
                    accepted.append(dict(id=digest((group_id,row['k']))[:24],entry_set_id=group_id,parent_id=pid,family=family,
                        ego=row['ego'],k=row['k'],C_span=c,V_star=vmax,V_min=vmin,S_entry_history=s,
                        S_query=None,S_future_history=None,information_positive=s>.05,detectable_information_value=s>1e-6,
                        information_metric_version='entry-and-future-public-history-v1',group_reach_probability=total,
                        physical_observation=row['physical_observation'],members=members,
                        nonquery_evidence=all(not any(x.get('action')=='INVESTIGATE' for x in d['history']) for d in row['details'])))
        # Explicit convenience priority for review; do not claim unbiased yield.
        accepted.sort(key=lambda r:(-round(r['S_entry_history'],8),r['k'],r['id']))
        selected=accepted[:8];candidates.extend(selected)
        ledger.append(dict(source=str(source),index=index,status='certified',entry_sets=len(groups),eligible_before_cap=len(accepted),retained=len(selected)))
    active_parents={r['parent_id'] for r in candidates}
    for parent in parents:
        if parent['id'] not in active_parents:
            ledger.append(dict(parent_id=parent['id'],status='no_retained_candidate'))
    parents=[r for r in parents if r['id'] in active_parents]
    calibration=json.loads(Path('examples/strategic_slices/fixtures/public_history_information.json').read_text())
    calibration_parent=digest(calibration['raw'])[:24]
    by_family=defaultdict(list)
    for parent in parents:by_family[parent['family']].append(parent['id'])
    kept=set()
    for family,ids in by_family.items():
        ordered_ids=sorted(ids,key=lambda pid:(pid!=calibration_parent,pid))
        kept.update(ordered_ids[:8])
        for pid in ordered_ids[8:]:ledger.append(dict(parent_id=pid,status='family_parent_cap'))
    parents=[r for r in parents if r['id'] in kept]
    candidates=[r for r in candidates if r['parent_id'] in kept]
    for path in (out/'references').glob('*.npz'):
        if path.stem not in kept:path.unlink()
    families=defaultdict(list)
    for parent in parents:families[parent['family']].append(parent['id'])
    calibration_family=structural_family(calibration['raw']['game'])
    calibration_families={calibration_family}|{r['family'] for r in parents if r['origin']['kind']=='public-history-calibration-variant'}
    ordered=sorted(families,key=lambda f:(-len(families[f]),digest((20261004,f))))
    targets=dict(train=len(parents)*.625,validation=len(parents)*.125,test=len(parents)*.25)
    assigned=Counter();mapping={}
    for family in ordered:
        if family in calibration_families:
            mapping[family]='train';assigned['train']+=len(families[family])
    for family in ordered:
        if family in mapping:continue
        split=max(targets,key=lambda s:targets[s]-assigned[s])
        mapping[family]=split;assigned[split]+=len(families[family])
    for row in parents+candidates:
        row['split']=mapping[row['family']]
        row['calibration_family']=row['family'] in calibration_families
    for split in ('train','validation','test'):
        write_rows(out/f'{split}_parents.jsonl',[r for r in parents if r['split']==split])
        write_rows(out/f'{split}_entry_sets.jsonl',[r for r in candidates if r['split']==split])
    for row in candidates:
        assert 1<=min(m['remaining_proposals'] for m in row['members'])<=3
        assert max(m['remaining_proposals'] for m in row['members'])<=3
        assert abs(sum(m['probability'] for m in row['members'])-1)<1e-9
        assert all(abs(sum(m['world_weights'])-1)<1e-9 for m in row['members'])
        assert row['C_span']>.1
    assert max(Counter(r['parent_id'] for r in candidates).values(),default=0)<=8
    assert len({r['id'] for r in candidates})==len(candidates)
    write_json(out/'ledger.json',ledger)
    manifest=dict(version='terminal-entry-sets-review-v1',status='candidate-review-only',training_compatible=False,
        source_summary_sha256={str(source):file_hash(source/'summary.json') for source in sources},script_sha256=file_hash(__file__),
        scope='Certified parents from recorded random-parent search batches. Full initial-state terminal references; entry sets with <=3 remaining proposals. Channel S is collective, not a per-history label. Unmeasured channels are null.',
        selection=dict(min_C=.1,min_increment=.05,min_S=.05,max_per_parent=8,max_parents_per_family=8,order='descending entry S, shortest k, stable id'),
        parents=len(parents),families=len(families),entry_sets=len(candidates),
        information_positive=sum(r['information_positive'] for r in candidates),detectable_information_value=sum(r['detectable_information_value'] for r in candidates),
        players=dict(Counter(r['players'] for r in parents)),split_policy='family-greedy-100:20:40-calibration-train-v1',
        splits={split:dict(parents=sum(r['split']==split for r in parents),entry_sets=sum(r['split']==split for r in candidates)) for split in ('train','validation','test')},
        validation=dict(no_family_overlap=True,unique_ids=True,parent_cap=True,joint_masses_normalized=True,native_terminal_only=True),
        files={str(path.relative_to(out)):file_hash(path) for path in sorted(out.rglob('*')) if path.is_file() and path.name!='manifest.json'})
    write_json(out/'manifest.json',manifest);print({k:v for k,v in manifest.items() if k not in ('files','scope')})

if __name__=='__main__':main()
