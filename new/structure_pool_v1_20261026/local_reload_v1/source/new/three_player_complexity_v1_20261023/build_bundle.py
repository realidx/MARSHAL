"""Standalone remote CPU package, with exact registered code and frozen inputs."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile

from .common import ROOT,REG,identity,snapshot,write,sha,stable


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pool',type=Path,default=ROOT/'new/three_player_complexity_v1_20261023/pool_v1')
    args=parser.parse_args();args.pool=args.pool.resolve();baseline=ROOT/'new/node_qs_audit_v1_20261023/terminal99_v1/results.json'
    snapshot(args.output,dict(operation='Build standalone CPU H2-first remote study package',
        pool=str(args.pool),default_remote_arm='H2',optional_arms=['H3','A2H2'],
        pinned_packages=['numpy==1.26.4','scipy==1.12.0'],GPU=False,models=False),
        {'pool':identity(args.pool/'games.jsonl'),'baseline_results':identity(baseline)})
    target=args.output/'three_player_remote_v1';target.mkdir()
    meta=json.loads(REG.read_text())
    extras=[REG.relative_to(ROOT),Path('examples/strategic_slices/versions/index.json'),
        Path('examples/strategic_slices/REMOTE_THREE_PLAYER_20261023.md'),
        Path('examples/strategic_slices/THREE_PLAYER_COMPLEXITY_20261023.md'),
        Path('new/three_player_complexity_v1_20261023/README.md'),
        Path('new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl'),
        Path('examples/strategic_slices/versions/node_qs_audit_v1_20261023/SNAPSHOT.json'),
        Path('examples/strategic_slices/versions/terminal_solver_repair_v6_20261023/SNAPSHOT.json')]
    extras += [REG.parent.relative_to(ROOT)/name for name in ('DESIGN.md','CHANGELOG.md')]
    extras += [args.pool.relative_to(ROOT)/name for name in ('games.jsonl','MANIFEST.json','pipeline_snapshot.json','COMPLETE.json')]
    diagnostic=ROOT/'new/three_player_complexity_v1_20261023/diagnostic_jobs_v1'
    extras += [(diagnostic/name).relative_to(ROOT) for name in ('three_player_subgames.jsonl','parent25_subgames.jsonl','COMPLETE.json')]
    for rel in sorted(set(list(map(Path,meta['source_hashes']))+extras)):
        dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dest)
    data=target/'data';data.mkdir()
    jobs=list(map(json.loads,(args.pool/'games.jsonl').read_text().splitlines()))
    for arm in ('H2','H3','A2H2'):
        (data/f'{arm}.jsonl').write_text(''.join(stable(j)+'\n' for j in jobs if j['arm']==arm))
    old_rows=json.loads(baseline.read_text());old_pool=list(map(json.loads,
        (ROOT/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl').read_text().splitlines()))
    baseline_games=[]
    for r in old_rows:
        if old_pool[r['index']]['configuration']['players']!=3:continue
        summary={scope:{k:v for k,v in r['summary'][scope].items() if not isinstance(v,list)}
                 for scope in ('counterfactual','on_reference')}
        baseline_games.append(dict(original_index=r['index'],summary=summary,reference_sha256=r['reference_sha256'],
            labels_sha256=r['labels_sha256']))
    write(data/'baseline_three_player.json',dict(version='node-qs-interactivity-audit-v1',games=baseline_games,
        source_result_sha256=sha(baseline),claim='Historical frozen original33 terminal audit; not new expansion/model-D measurements'))
    write(data/'STUDY_INPUTS.json',dict(source_pool=identity(args.pool/'games.jsonl'),
        arms={arm:dict(games=33,sha256=sha(data/f'{arm}.jsonl')) for arm in ('H2','H3','A2H2')},
        baseline_sha256=sha(data/'baseline_three_player.json')))
    (target/'requirements.txt').write_text('numpy==1.26.4\nscipy==1.12.0\n')
    (target/'RUN_REMOTE.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs
python -m new.three_player_complexity_v1_20261023.remote doctor
python -u -m new.three_player_complexity_v1_20261023.remote run --jobs data/H2.jsonl --output remote_runs/H2 --workers "${STUDY_WORKERS:-1}" "$@"
''')
    from .remote import DEFAULTS
    write(target/'PROTOCOL.json',dict(version=meta['version'],source_registration_sha256=sha(REG),
        defaults=DEFAULTS,workers=1,primary_arm='H2',optional_arms=['H3','A2H2'],
        acceptance='native full-terminal private BR/local support/response social ties; no threshold relaxation',
        S='per-item current-node omission; uniform remaining masked ties; zero_CF unavailable',
        heavy_remote_run='NOT_RUN_LOCALLY',production_changed=False))
    files={str(p.relative_to(target)):sha(p) for p in sorted(target.rglob('*')) if p.is_file()}
    write(target/'BUNDLE_MANIFEST.json',dict(version='three-player-remote-bundle-v1',files=files,
        recommended_python='3.12',supported_pinned_python='3.10-3.12',GPU_required=False,
        default='H2 first; do not run all99 unless desired',registration_sha256=sha(REG)))
    archive=args.output/'three_player_remote_v1.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(target,arcname=target.name)
    digest=sha(archive);archive.with_suffix(archive.suffix+'.sha256').write_text(digest+'  '+archive.name+'\n')
    write(args.output/'COMPLETE.json',dict(archive=str(archive),archive_sha256=digest,bytes=archive.stat().st_size,
        files=len(files),manifest_sha256=sha(target/'BUNDLE_MANIFEST.json'),pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(stable(dict(archive=str(archive),sha256=digest,bytes=archive.stat().st_size,files=len(files))))


if __name__=='__main__':main()
