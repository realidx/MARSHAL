"""Report remote coverage against all33 baselines, never count missing as0."""
import argparse
import json
from pathlib import Path

from .common import identity,snapshot,write,sha


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();baseline=json.loads(args.baseline.read_text())
    rows=json.loads((args.run/'results.json').read_text());jobs=json.loads((args.run/'jobs.json').read_text())
    snapshot(args.output,dict(operation='Coverage-aware remote paired report; no selection or D',
        run=str(args.run),denominator='all requested original33 per arm; unmeasured cases remain missing',
        baseline_version=baseline['version']),{'run_results':identity(args.run/'results.json'),'baseline':identity(args.baseline)})
    base={r['original_index']:r for r in baseline['games']};report={}
    for arm in sorted({j['arm'] for j in jobs}):
        selected=[r for r in rows if r.get('arm')==arm];measured=[r for r in selected if r.get('labels')=='MEASURED']
        output=dict(requested=sum(j['arm']==arm for j in jobs),resolved=len(selected),
            certified=sum(r.get('reference_accepted',False) for r in selected),measured=len(measured),
            missing_original_indices=[j['original_index'] for j in jobs if j['arm']==arm and
                j['original_index'] not in {r['original_index'] for r in measured}],comparisons={})
        for scope in ('counterfactual','on_reference'):
            output['comparisons'][scope]={}
            for metric in ('private_S_positive','history_S_positive','query_strictly_better'):
                new_positive=[r['original_index'] for r in measured if r['summary'][scope][metric]>0]
                old_positive=[r['original_index'] for r in measured if base[r['original_index']]['summary'][scope][metric]>0]
                output['comparisons'][scope][metric]=dict(new_positive=new_positive,baseline_positive_in_same_measured_subset=old_positive,
                    new_only=sorted(set(new_positive)-set(old_positive)),baseline_only=sorted(set(old_positive)-set(new_positive)),
                    missing_are_not_zero=True)
        report[arm]=output
    write(args.output/'ANALYSIS.json',dict(arms=report,D='NOT_MEASURED',training='NOT_RUN',
        limitation='Changes add worlds and may select a different equilibrium; baseline/new counts are design calibration, not an isolated causal effect or model training result.'))
    write(args.output/'COMPLETE.json',dict(analysis_sha256=sha(args.output/'ANALYSIS.json'),
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
