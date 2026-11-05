"""Closeout identity checks; old failed/superseded evidence is kept explicitly."""
import argparse
import json
from pathlib import Path

from .run import snapshot,REGISTRATION
from new.sparse_solver_v1_20261023.common import ROOT,POOL,POOL_SHA,sha,write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();base=Path(__file__).resolve().parent
    runs=sorted(p for p in base.iterdir() if p.is_dir() and (p/'pipeline_snapshot.json').exists())
    snapshot(args.output,dict(operation='Validate all earlier research artifacts/source archives and active identity',
        run_directories=[str(p.relative_to(ROOT)) for p in runs],
        known_failed='pilot_v1 native response decoding; no labels',
        superseded='window_analysis_v1 aggregation max_* count bug; node labels unchanged'),{})
    assert sha(POOL)==POOL_SHA
    old=ROOT/'examples/strategic_slices/versions/terminal_solver_repair_v6_20261023/SNAPSHOT.json'
    old_meta=json.loads(old.read_text())
    assert old_meta['status']=='CLOSED_RESEARCH_NOT_PRODUCTION'
    assert all(sha(ROOT/path)==h for path,h in old_meta['source_hashes'].items())
    index=json.loads((ROOT/'examples/strategic_slices/versions/index.json').read_text())
    assert index['active']=='terminal-node-regret-grpo-readable-v8'
    fields=dict(results_sha256='results.json',pipeline_snapshot_sha256='pipeline_snapshot.json',
        snapshot_sha256='pipeline_snapshot.json',test_log_sha256='tests.txt',
        diagnosis_sha256='diagnosis.json',analysis_sha256='ANALYSIS.json',
        overview_sha256='OVERVIEW.json',review_sha256='CASE_REVIEW.json')
    records=[];source_files=0;label_files=0
    for run in runs:
        meta=json.loads((run/'pipeline_snapshot.json').read_text())
        for path,h in meta['source_hashes'].items():
            assert sha(run/'source'/path)==h,(run,path)
            source_files+=1
        assert sha(run/'registered_snapshot_at_start.json')==meta['registration_sha256']
        assert meta['input_data']['sha256']==POOL_SHA
        for identity in meta['references'].values():assert sha(ROOT/identity['path'])==identity['sha256']
        done=json.loads((run/'COMPLETE.json').read_text())
        for field,path in fields.items():
            if field in done:assert sha(run/path)==done[field],(run,field)
        result_path=run/'results.json'
        if result_path.exists():
            for row in json.loads(result_path.read_text()):
                if 'labels_sha256' in row:
                    assert sha(run/'cases'/str(row['index'])/'labels.jsonl.gz')==row['labels_sha256'];label_files+=1
                if 'examples_sha256' in row:
                    assert sha(run/'cases'/str(row['index'])/'examples.json')==row['examples_sha256']
        records.append(dict(run=str(run.relative_to(ROOT)),
            snapshot_sha256=sha(run/'pipeline_snapshot.json'),complete_sha256=sha(run/'COMPLETE.json'),
            state=('FAILED_EARLY_NO_LABELS_RETAINED' if run.name=='pilot_v1' else
                   'SUPERSEDED_AGGREGATION_RETAINED' if run.name=='window_analysis_v1' else 'COMPLETED'),
            source_archive_verified=True,input_identities_verified=True))
    for run_name,expected in [('terminal99_v1',99),('window100_v1',100)]:
        done=json.loads((base/run_name/'COMPLETE.json').read_text())
        assert done['measured']==expected and not done['errors']
    assert json.loads((base/'terminal99_v1/COMPLETE.json').read_text())['missing_references']==[25]
    assert json.loads((base/'tests_final_v1/COMPLETE.json').read_text())['passed']
    witness=json.loads((base/'terminal_witnesses_v1/COMPLETE.json').read_text())
    assert witness['witnesses']==66 and witness['robust_positive_witnesses']==66
    assert json.loads((base/'native_case_review_v1/COMPLETE.json').read_text())['native_enumeration_matches_Q']
    write(args.output/'ARTIFACT_INDEX.json',dict(runs=records,source_archive_files_checked=source_files,
        label_files_checked=label_files,closed_solver_sources_unchanged=True,production_active_unchanged=True))
    write(args.output/'COMPLETE.json',dict(passed=True,runs=len(records),source_files=source_files,label_files=label_files,
        artifact_index_sha256=sha(args.output/'ARTIFACT_INDEX.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(passed=True,runs=len(records),source_files=source_files,label_files=label_files))


if __name__=='__main__':main()
