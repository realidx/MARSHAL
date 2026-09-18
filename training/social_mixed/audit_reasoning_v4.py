"""Summarize the candidate by structure, skill and scheduled exposure."""
from collections import Counter
import json
from training.social_mixed.prepare_reasoning_v4 import SOURCE,OUT,read
from training.social_mixed.distribution_sampling import select
from training.social_mixed.structure_coverage import geometry_id


def main():
    report={}
    for split in ('train','validation'):
        ts=read(OUT/('bp_'+split+'.jsonl'));old=read(SOURCE/('bp_'+split+'.jsonl'));original={t['id'] for t in old}
        added=[t for t in ts if t['id'] not in original];raw=[t for t in added if t['input'].get('belief_source')=='history']
        old_families={geometry_id(t['input']['game']) for t in old}
        report[split]=dict(total=len(ts),added=len(added),new_bp_geometries=len({geometry_id(t['input']['game']) for t in ts}-old_families),
            added_cells=dict(Counter(t['kernel']+'/'+t['skill']+'/'+t['completion_mode'] for t in added)),
            history_action_points=len(raw),history_sensitive_points=sum(bool(t['teacher'].get('history_changes_acceptable')) for t in raw),
            exact_posterior_pairs=sum(bool(t.get('oracle_pair_of')) for t in added),
            b3_update=sum(t['kernel']=='B3' and t['skill']=='update' for t in ts),
            b3_maintain=sum(t['kernel']=='B3' and t['skill']=='maintain' for t in ts),
            p4_result_use=sum(t['kernel']=='P4' and bool(t['input']['private_results']) for t in ts),
            periodic_panel=dict(Counter(t['task'] for t in ts if t.get('periodic_validation'))))
    train=read(OUT/'bp_train.jsonl');seen={t['id'] for step in range(194) for t in select(train,step,42)}
    report['schedule_194_updates']=dict(distinct_seen=len(seen),total=len(train),unseen_ids=[t['id'] for t in train if t['id'] not in seen],
        scope='Deterministic task schedule only; actual token exhaustion may stop earlier. Not a learning or repeated-exposure guarantee.')
    report['limitations']=['History-sensitive means the acceptable set changes; it need not become disjoint from the prior-only set.',
        'No on-policy OFFER-acquisition premium certified in the inspected P4 sources. Response-conditioned reasoning and query-result use are covered; strategic OFFER information acquisition remains open.',
        'SP geometries are native random full games with no outcome-based admission. Longer horizons do not certify useful information opportunities.',
        'Teacher assumptions and exact zero-likelihood fragility remain unchanged. Failed/cycling solves are logged and never labelled.',
        'Source-family split independence is checked; inherited historical test usage is not independently established.']
    (OUT/'coverage_report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
