"""Finalize provenance for CalBench runs using the registered v12-inbox scaffold."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path


PROMPT_VERSION = 'general-belief-ms-v12-inbox'


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else default


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


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
    if request.get('prompt_version') != PROMPT_VERSION:
        raise ValueError('Submission metadata does not identify the registered v12-inbox prompt')
    if request.get('condition', {}).get('scaffold') != 'belief-ms':
        raise ValueError('This finalizer only accepts the belief-ms scaffold condition')

    from examples.final_evaluation.calbench_scaffold import VERSION, verify_registration, write_snapshot

    registration = verify_registration()
    if VERSION != PROMPT_VERSION or registration.get('version') != PROMPT_VERSION:
        raise ValueError('The runtime scaffold does not match the v12-inbox registration')

    routes = read_json(run_root / 'routes.json', request.get('resolved_routes_if_launcher_fails', {}))
    run_snapshot_path = games_root / 'pipeline_snapshot.json'
    if not run_snapshot_path.is_file():
        frozen = read_json(games_root / 'frozen_manifest.json', {})
        write_snapshot(
            games_root,
            routes,
            cli=request.get('launch_argv'),
            game_config=frozen.get('config'),
            job=request.get('submission'),
        )

    snapshot = read_json(run_snapshot_path, {})
    snapshot['scheduler'] = request.get('submission', '未记录')
    snapshot['job_profile'] = request.get('runtime_profile', '未记录')
    snapshot['condition'] = request.get('condition', '未记录')
    snapshot['prompt_version'] = PROMPT_VERSION
    snapshot['prompt_registration'] = 'examples/strategic_slices/versions/general_ms_calbench_v12_inbox_20261102/SNAPSHOT.json'
    snapshot['launcher_cli'] = request.get('launch_argv', '未记录')
    snapshot['submission_script_sha256'] = request.get('source', {}).get('execution_scripts_sha256', '未记录')
    snapshot['batch_exit_code'] = (run_root / 'BATCH_EXIT_CODE').read_text().strip() if (run_root / 'BATCH_EXIT_CODE').is_file() else '未记录'
    snapshot['launcher_exit_code'] = (run_root / 'EXIT_CODE').read_text().strip() if (run_root / 'EXIT_CODE').is_file() else '未记录'
    snapshot['run_finished'] = read_json(games_root / 'RUN_FINISHED.json', '未记录')
    snapshot['pipeline_status'] = 'COMPLETE' if snapshot['batch_exit_code'] == '0' and snapshot['launcher_exit_code'] == '0' else 'INCOMPLETE_OR_FAILED'
    run_snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')

    root_snapshot = deepcopy(snapshot)
    root_snapshot['scope'] = 'Run root summary; per-case snapshots and traces are under games/.'
    (run_root / 'pipeline_snapshot.json').write_text(json.dumps(root_snapshot, ensure_ascii=False, indent=2) + '\n')

    for manifest_path in sorted(games_root.glob('*/manifest.json')):
        folder = manifest_path.parent
        manifest = read_json(manifest_path, {})
        case_snapshot = deepcopy(snapshot)
        case_snapshot['scope'] = 'One CalBench stream24 case.'
        case_snapshot['game_config'] = manifest.get('config', snapshot.get('game_config'))
        case_snapshot['game_job'] = manifest.get('job', '未记录')
        reference = folder / 'case_reference.json'
        if reference.is_file():
            case_snapshot['case_reference_sha256'] = sha_file(reference)
        (folder / 'pipeline_snapshot.json').write_text(json.dumps(case_snapshot, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
