"""Freeze the first 14 completed case records, independent of later progress."""
import json
from pathlib import Path

from new.three_player_complexity_v1_20261023.common import (
    ROOT, identity, sha, snapshot, write,
)


def main():
    run = ROOT / 'new/three_player_complexity_v1_20261023/local_H2_33_v1'
    out = ROOT / 'new/three_player_complexity_v1_20261023/local_H2_first14_review_v1'
    baseline_path = ROOT / 'new/remote_three_player_bundle_20261023/final/three_player_remote_v1/data/baseline_three_player.json'
    paths = [run / 'cases' / str(i) / 'execution-0000/result.json' for i in range(14)]
    rows = [json.loads(p.read_text()) for p in paths]
    baseline = {r['original_index']: r for r in json.loads(baseline_path.read_text())['games']}
    measured = [r for r in rows if r.get('labels') == 'MEASURED']
    inputs = {str(i): identity(p) for i, p in enumerate(paths)}
    inputs.update(report_script=identity(__file__), baseline=identity(baseline_path),
                  run_snapshot=identity(run / 'pipeline_snapshot.json'))
    snapshot(out, dict(operation='Read-only frozen first14 review; no solver/label changes',
        study_indices=list(range(14)), denominator='13 measured of14 attempted; failed remains missing',
        threshold='existing stored positive counts at1e-8; no new selection threshold',
        comparison='old baseline on exactly the same measured originals',
        independent_reload='NOT_YET_RUN_FOR_THIS_BATCH',
        ongoing_full_run='Continues separately; this review never reads later results'), inputs)
    write(out / 'first14_results.json', rows)
    scopes = {}
    for scope in ('counterfactual', 'on_reference'):
        scopes[scope] = {}
        for name, group in (('H2', measured), ('baseline', [baseline[r['original_index']] for r in measured])):
            s = {}
            for metric in ('private_S_positive', 'history_S_positive', 'query_strictly_better'):
                s[metric] = [r['original_index'] for r in group if r['summary'][scope][metric] > 0]
            s['any_S_positive'] = sorted(set(s['private_S_positive']) | set(s['history_S_positive']))
            scopes[scope][name] = s
    report = dict(attempted=14, certified=13, measured=len(measured),
        failed_original_indices=[r['original_index'] for r in rows if r.get('labels') != 'MEASURED'],
        scopes=scopes, no_single_item_positive_S=[r['original_index'] for r in measured
            if not any(r['summary']['counterfactual'][k] for k in ('private_S_positive', 'history_S_positive'))],
        independent_reload='NOT_YET_RUN_FOR_THIS_BATCH', D='NOT_MEASURED',
        warning='Reference-path reach is not model self-play reach. Added worlds and possible profile changes confound causal attribution.')
    write(out / 'REVIEW.json', report)
    write(out / 'COMPLETE.json', dict(review_sha256=sha(out / 'REVIEW.json'),
        frozen_results_sha256=sha(out / 'first14_results.json'),
        pipeline_snapshot_sha256=sha(out / 'pipeline_snapshot.json')))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
