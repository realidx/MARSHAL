"""Source overlay for an existing MARSHAL checkout; no data, model or submission."""
import argparse
import io
import json
from pathlib import Path
import tarfile

from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.train_terminal import ROOT, source_identity
from training.strategic_slices.terminal_training import VERSION, CONTRACT, TrainingData
from training.strategic_slices.named_prompt import VERSION as PROMPT_VERSION
from training.strategic_slices.pipeline_versions import registered_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    registered=registered_snapshot(VERSION,PROMPT_VERSION)
    data=TrainingData(ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',
        ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    files=set(source_identity())
    files.add('training/__init__.py')
    folder=ROOT/'examples/strategic_slices'
    files.update(str(p.relative_to(ROOT)) for p in folder.iterdir()
        if p.is_file() and p.suffix in ('.py','.sh','.json','.md'))
    files.update(str(p.relative_to(ROOT)) for p in (folder/'fixtures').rglob('*') if p.is_file())
    files.update(str(p.relative_to(ROOT)) for p in (folder/'versions').rglob('*') if p.is_file())
    files.add('AGENTS.md')
    for name in ('terminal_node_grpo_readiness_20261016','terminal_refill_readiness_20261016','terminal_cpu_reuse_20261016','terminal_evaluation_refill_20261016'):
        evidence=ROOT/'new'/name
        files.update(str(p.relative_to(ROOT)) for p in evidence.glob('*')
            if p.is_file() and p.suffix in ('.md','.json','.log','.txt') and p.name!='source_bundle.json')
    manifest=dict(kind='terminal-training-source-overlay-v1',recipe=VERSION,contract=CONTRACT,registered_snapshot=registered,
        requires_existing_marshal_checkout=True,dataset_sha256=data.sha,
        data_included=False,model_weights_included=False,dependencies_included=False,submitted=False,
        files={name:file_hash(ROOT/name) for name in sorted(files)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(args.output,'x:gz') as archive:
        for name in sorted(files):archive.add(ROOT/name,arcname=name,recursive=False)
        payload=(json.dumps(manifest,indent=2)+'\n').encode()
        entry=tarfile.TarInfo('TERMINAL_TRAINING_SOURCE.json');entry.size=len(payload)
        archive.addfile(entry,io.BytesIO(payload))
    report=dict(archive=args.output.name,sha256=file_hash(args.output),files=len(files),recipe=VERSION,
        dataset_sha256=data.sha,data_included=False,model_weights_included=False,submitted=False)
    write_json(Path(str(args.output)+'.json'),report)
    print(json.dumps(report))


if __name__=='__main__':main()
