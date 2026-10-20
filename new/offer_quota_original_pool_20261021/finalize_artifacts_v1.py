"""Close research-only game identities without promoting a training dataset."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

import numpy as np
import scipy


def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,value):
    with p.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    parents=json.loads((args.run/'parents.json').read_text())
    analysis=json.loads((args.analysis/'paired_analysis.json').read_text())
    assert len(parents)==100
    pairs={r['parent_id']:r for r in analysis['pairs']}
    assert set(pairs)=={p['id'] for p in parents}
    for name,expected in analysis['artifact_inputs'].items():assert digest(Path(name))==expected,name
    rule=dict(version='per-player-offer-quota1-on-proposal-v1',limit=1,
        scope='one per player per game',charge='immediately upon proposing before response',
        refund=False,response_consumes_own_quota=False,extra_utility_penalty=0,
        after_exhaustion='PASS, unused INVESTIGATE and response remain legal; OFFER prohibited',
        investigation='same as original: one per player per game; consumes proposal turn; public target/private answer',
        goals_prior_catalogue_schedule='unchanged original parent')
    entries=[];max_baseline_gain=max_quota_gain=0.
    pool=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4')
    for parent in parents:
        pid=parent['id'];pair=pairs[pid]
        identity=dict(base_parent_id=pid,base_raw=parent['raw'],additional_rule=rule)
        game_id=sha256(canonical(identity).encode()).hexdigest()[:24]
        baseline_file=args.run/f'{pid}_baseline.json'
        baseline=json.loads(baseline_file.read_text())
        assert baseline['identity_preserved']
        max_baseline_gain=max(max_baseline_gain,baseline['independent_certificate']['max_own_deviation_gain'])
        entry=dict(base_parent_id=pid,variant_game_id=game_id,split=parent['split'],players=parent['players'],
            base_raw_sha256=sha256(canonical(parent['raw']).encode()).hexdigest(),
            quota_binding=pair['binding'],completed_pair=pair['complete'],
            original_reference=dict(file=str(pool/baseline['original_reference_file']),
                sha256=baseline['original_reference_sha256'],policy_sha256=baseline['original_policy_sha256']),
            result_directory=pair['selected_result_directory'],retry_attempts=pair.get('retry_attempts',[]))
        if not pair['complete']:
            entry.update(reference_kind='unavailable-not-zero',reason=pair['reason'],training_compatible=False)
        else:
            folder=Path(pair['selected_result_directory']);quota=json.loads((folder/f'{pid}_quota.json').read_text())
            if pair['binding']:
                c=quota['certificate']
                assert c['remaining_game_terminal_scope'] and c['cutoff_leaves']==0
                assert c['response_only_social_ties_verified'] and c['local_own_support_verified']
                assert c['max_own_deviation_gain']<=1e-8
                assert quota['quota_audit']['verified'] and quota['native_audit']['all_values_match']
                reference=folder/f'{pid}_quota_reference.npz'
                assert digest(reference)==quota['reference_sha256']
                max_quota_gain=max(max_quota_gain,c['max_own_deviation_gain'])
                entry.update(reference_kind='new-certified-quota-profile',quota_reference_file=str(reference),
                    quota_reference_sha256=quota['reference_sha256'],quota_policy_sha256=c['policy_sha256'])
            else:
                assert quota['quota_solver_called'] is False
                assert quota['original_policy_sha256']==baseline['original_policy_sha256']
                entry.update(reference_kind='original-profile-reused-under-game-equivalence',equivalence_proof=quota['proof'])
        entries.append(entry)
    assert len({r['variant_game_id'] for r in entries})==100
    write(args.output/'VARIANT_MANIFEST.json',dict(version='original-100-offer-quota-research-identities-v1',
        status='research-only-not-training-dataset',training_compatible=False,
        base_parent_count=100,completed_pairs=sum(r['completed_pair'] for r in entries),
        additional_rule=rule,entries=entries,new_prompt=False,new_C_S_D=False,new_training=False,
        identity_note='Base parent ids preserved; quota game identity is distinct and includes the added rule. Equivalent references retain their original identity. No old candidate labels promoted.'))
    write(args.output/'VALIDATION.json',dict(all_original_parent_ids_preserved=True,variant_ids_unique=True,
        original_baselines_recertified=100,new_quota_profiles_certified=sum(r['completed_pair'] and r['quota_binding'] for r in entries),
        nonbinding_equivalences_verified=sum(not r['quota_binding'] for r in entries),
        unavailable=[r['base_parent_id'] for r in entries if not r['completed_pair']],
        max_baseline_deviation_gain=max_baseline_gain,max_quota_deviation_gain=max_quota_gain,
        epsilon=1e-8,response_tie_tolerance=1e-9,model_calls=0,gpu_used=False))
    write(args.output/'pipeline_snapshot.json',dict(status='completed-cpu-artifact-validation',
        actual_argv=sys.argv,resolved_config=dict(source_run=str(args.run),analysis=str(args.analysis),
            identities='original parent id + unchanged raw + explicit quota rule',promotion_to_training=False),
        source_sha256=digest(Path(__file__)),
        inputs={str(p):digest(p) for p in (args.run/'parents.json',args.analysis/'paired_analysis.json',args.analysis/'analysis_snapshot.json')},
        model_identity='none',sampling_reward_contract='deterministic identity/consistency checks only',
        runtime=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__),
        outputs={n:digest(args.output/n) for n in ('VARIANT_MANIFEST.json','VALIDATION.json')}))
    print(json.dumps(json.loads((args.output/'VALIDATION.json').read_text()),indent=2))


if __name__=='__main__':main()
