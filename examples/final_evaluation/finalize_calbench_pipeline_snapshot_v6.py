"""Finalize complete provenance snapshots for CalBench H100-47 batch runs."""
import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / 'examples/strategic_slices/versions/general_ms_calbench_v6_20261102/SNAPSHOT.json'


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def package_versions():
    names = ('vllm', 'torch', 'transformers', 'tokenizers', 'pydantic', 'ortools', 'json-repair')
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = '未记录（运行器环境未安装）'
    return versions


def native_snapshot(run_root, games_root, request, routes):
    from examples.final_evaluation.calbench_stream import FROZEN, load_frozen

    frozen, _cases = load_frozen()
    files = [
        'examples/final_evaluation/calbench_local.py',
        'examples/final_evaluation/calbench_formal.py',
        'examples/final_evaluation/calbench_stream.py',
        'examples/final_evaluation/calbench_stream_metrics.py',
        'examples/final_evaluation/launch_calbench_local.py',
        'examples/final_evaluation/interaction_scaffold.py',
        'examples/final_evaluation/finalize_calbench_pipeline_snapshot_v6.py',
    ]
    source_hashes = {name: sha_file(ROOT / name) for name in files if (ROOT / name).is_file()}
    source_manifest = ROOT / 'examples/final_evaluation/calbench_source.json'
    source_manifest_data = read_json(source_manifest, {})
    frozen_manifest = games_root / 'frozen_manifest.json'
    if frozen_manifest.is_file():
        frozen_hash = sha_file(frozen_manifest)
    else:
        frozen_hash = sha_file(FROZEN / 'manifest.json')
    execution_identity = read_json(run_root / 'execution_identity.json', '未记录')
    runtime_environment = read_json(run_root / 'runtime_environment.json', '未记录')
    servers = read_json(run_root / 'servers.json', '未记录')
    registration_hash = sha_file(REGISTRATION)
    return {
        'schema': 1,
        'version': 'calbench-native-stream24-h10047-control-v1',
        'source_version': 'general-ms-conditioning-v2-shared-budget',
        'scope': 'Native/base-prompt CalBench24 comparison condition; no MS scaffold applied.',
        'cli': request.get('launch_argv', '未记录'),
        'resolved_routes': routes,
        'game_config': frozen['config'],
        'contract': {
            'scaffold': 'native',
            'temperature': routes.get('temperature', '未记录'),
            'max_tokens': routes.get('max_tokens', '未记录'),
            'timeout_seconds': routes.get('timeout_seconds', '未记录'),
            'execution_protocol': routes.get('execution_protocol', '未记录'),
            'prompt_changed': False,
            'chat_template_kwargs': routes.get('chat_template_kwargs', {}),
            'reasoning_normalization': 'separate leading think block; preserve raw output',
            'retry': 'native decision retry policy; 1 decision retry',
            'fallback': False,
            'environment_reflection': False,
        },
        'source_sha256': source_hashes,
        'source_manifest': source_manifest_data,
        'input_sha256': {
            'suite_manifest': frozen_hash,
            'suite_manifest_checksum_file': sha_file(FROZEN / 'MANIFEST.sha256'),
            'source_manifest': sha_file(source_manifest),
            'registered_base_ms_v2_snapshot': registration_hash,
        },
        'model_identity': execution_identity,
        'runtime': {
            'python': sys.version,
            'executable': sys.executable,
            'platform': platform.platform(),
            'dependencies': package_versions(),
            'launcher_environment': runtime_environment,
            'server_commands': servers,
        },
        'scheduler': request.get('submission', '未记录'),
        'job_profile': request.get('runtime_profile', '未记录'),
        'comparison_batch': request.get('run_label', '未记录'),
        'condition': request.get('condition', {'scaffold': 'native'}),
        'evaluation': 'Original native rules, all four seats, original final-state scoring; frozen stream24 manifest.',
        'reward_advantage_training': 'No parameter updates; no training or D measurement.',
        'resume': 'Existing outputs are not overwritten; each submission uses a unique job-id output directory.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    games_root = run_root / 'games'
    run_root.mkdir(parents=True, exist_ok=True)
    games_root.mkdir(parents=True, exist_ok=True)
    request = read_json(args.request, {})
    routes = read_json(run_root / 'routes.json', request.get('resolved_routes_if_launcher_fails', {}))
    scaffold = request.get('condition', {}).get('scaffold', '未记录')

    run_snapshot_path = games_root / 'pipeline_snapshot.json'
    if scaffold in ('base-ms', 'belief-ms'):
        if not run_snapshot_path.is_file():
            from examples.final_evaluation.calbench_scaffold import write_snapshot
            write_snapshot(games_root, routes, cli=request.get('launch_argv'),
                           game_config=read_json(games_root / 'frozen_manifest.json', {}).get('config'),
                           job=request.get('submission'))
        snapshot = read_json(run_snapshot_path, {})
    else:
        snapshot = native_snapshot(run_root, games_root, request, routes)

    snapshot['scheduler'] = request.get('submission', '未记录')
    snapshot['job_profile'] = request.get('runtime_profile', '未记录')
    snapshot['condition'] = request.get('condition', {'scaffold': scaffold})
    snapshot['launcher_cli'] = request.get('launch_argv', '未记录')
    snapshot['submission_script_sha256'] = request.get('source', {}).get('execution_scripts_sha256', '未记录')
    snapshot['batch_exit_code'] = (run_root / 'BATCH_EXIT_CODE').read_text().strip() if (run_root / 'BATCH_EXIT_CODE').is_file() else '未记录'
    snapshot['launcher_exit_code'] = (run_root / 'EXIT_CODE').read_text().strip() if (run_root / 'EXIT_CODE').is_file() else '未记录'
    snapshot['run_finished'] = read_json(games_root / 'RUN_FINISHED.json', '未记录')
    snapshot['pipeline_status'] = 'COMPLETE' if snapshot['batch_exit_code'] == '0' and snapshot['launcher_exit_code'] == '0' else 'INCOMPLETE_OR_FAILED'
    run_snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')

    root_snapshot = deepcopy(snapshot)
    root_snapshot['scope'] = 'Run root summary; full game manifest and per-game snapshots are under games/.'
    (run_root / 'pipeline_snapshot.json').write_text(json.dumps(root_snapshot, ensure_ascii=False, indent=2) + '\n')

    for game_manifest_path in sorted(games_root.glob('*/manifest.json')):
        folder = game_manifest_path.parent
        game_manifest = read_json(game_manifest_path, {})
        game_snapshot = deepcopy(snapshot)
        game_snapshot['scope'] = 'One CalBench stream24 case.'
        game_snapshot['game_config'] = game_manifest.get('config', snapshot.get('game_config'))
        game_snapshot['game_job'] = game_manifest.get('job', '未记录')
        reference = folder / 'case_reference.json'
        if reference.is_file():
            game_snapshot['case_reference_sha256'] = sha_file(reference)
        (folder / 'pipeline_snapshot.json').write_text(json.dumps(game_snapshot, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
