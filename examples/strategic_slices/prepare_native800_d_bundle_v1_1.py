"""Package the frozen native800 D source, inputs and references, without tests."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
VERSION_DIR = ROOT/'examples/strategic_slices/versions/native800_d_runner_v1_1_20261105'


def sha(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):checksum.update(chunk)
    return checksum.hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',type=Path,required=True)
    args = cli.parse_args()
    snapshot = json.loads((VERSION_DIR/'SNAPSHOT.json').read_text())
    cfg_path = ROOT/'examples/strategic_slices/native800/d_config_v1.json'
    cfg = json.loads(cfg_path.read_text())
    data,pool = ROOT/cfg['data'],ROOT/cfg['pool']
    files = set(snapshot['source_hashes'])
    files.update(str(p.relative_to(ROOT)) for p in VERSION_DIR.iterdir() if p.is_file())
    prompt = ROOT/'examples/strategic_slices/versions/native800_prompt_score_v4_20261105'
    files.update(str(p.relative_to(ROOT)) for p in prompt.iterdir() if p.is_file())
    files.add('examples/strategic_slices/NATIVE800_D_REMOTE_20261105.md')
    files.update(str((data/name).relative_to(ROOT)) for name in ('MANIFEST.json','train.jsonl','validation.jsonl','ENTRY_INDEX.md'))
    files.update(str((pool/name).relative_to(ROOT)) for name in ('MANIFEST.json','parents.jsonl'))
    for parent in map(json.loads,(pool/'parents.jsonl').read_text().splitlines()):
        files.add(parent['admission']['path'])
        files.add(str((pool/parent['reference']['path']).relative_to(ROOT)))
    # Keep ordinary package entry files where present. Namespace packages remain valid.
    for name in tuple(files):
        for parent in (ROOT/name).parents:
            if parent==ROOT:break
            init=parent/'__init__.py'
            if init.is_file():files.add(str(init.relative_to(ROOT)))
    identity = {name:dict(sha256=sha(ROOT/name),bytes=(ROOT/name).stat().st_size) for name in sorted(files)}
    manifest = dict(version=snapshot['version'],status='PACKAGED_AFTER_V1_STARTUP_FAILURE_NOT_EXECUTED',
        runtime_validation='STATIC_SOURCE_AND_PACKAGE_HASH_CHECKS_ONLY; NO_CPU_MOCK_GPU_SMOKE; 1077848_FAILED_BEFORE_MODEL_CALL',
        prior_attempt=dict(job_id='1077848',state='FAILED_BEFORE_MODEL_CALL',error="ModuleNotFoundError: No module named examples.strategic_slices.run_terminal_d"),files=identity,
        source_registration_sha256=sha(VERSION_DIR/'SNAPSHOT.json'),
        data_manifest_sha256=sha(data/'MANIFEST.json'),model_weights_included=False,
        full_label_profiles_included=False,entry_oracle_rows='Embedded in frozen train/validation JSONL',
        solver_run=False,model_run=False,submitted=False,
        entry='bash examples/strategic_slices/run_native800_d_v1_1.sh --model /path/to/local/model --output runs/native800-D-v1.1')
    pipeline = dict(operation='Transfer archive creation after job 1077848 failed before model invocation',version=snapshot['version'],
        actual_argv=sys.argv,resolved_config=cfg,source_identity=snapshot['source_hashes'],
        input_identity=identity,source_registration_sha256=manifest['source_registration_sha256'],
        environment=dict(python=sys.version,executable=sys.executable,platform=platform.platform()),
        model='NOT_USED',sampling='NOT_RUN',D='NOT_MEASURED',training='NOT_STARTED',
        validation='NO_CPU_MOCK_GPU_SMOKE; prior job 1077848 failed before model invocation')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(args.output,'x:gz') as archive:
        for name in sorted(files):archive.add(ROOT/name,arcname=name,recursive=False)
        payload=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        info=tarfile.TarInfo('NATIVE800_D_BUNDLE.json');info.size=len(payload)
        archive.addfile(info,io.BytesIO(payload))
        payload=(json.dumps(pipeline,ensure_ascii=False,indent=2)+'\n').encode()
        info=tarfile.TarInfo('NATIVE800_BUNDLE_PIPELINE_SNAPSHOT.json');info.size=len(payload)
        archive.addfile(info,io.BytesIO(payload))
    sidecar=dict(archive=args.output.name,sha256=sha(args.output),files=len(files),
        bytes=args.output.stat().st_size,**{k:v for k,v in manifest.items() if k!='files'})
    args.output.with_name(args.output.name+'.json').write_text(json.dumps(sidecar,ensure_ascii=False,indent=2)+'\n')
    args.output.with_name(args.output.name+'.pipeline_snapshot.json').write_text(json.dumps(pipeline,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(sidecar,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
