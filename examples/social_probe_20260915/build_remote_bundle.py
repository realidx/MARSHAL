"""Build an isolated upload directory; exclude local B/P scoring labels."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(l0=False, qwen17=False, thinking=False):
    qwen17 = qwen17 or thinking
    if l0 and qwen17:
        raise ValueError('Choose one bundle profile')
    selection = HERE/'selection_v1'
    original = json.loads((selection/'manifest.json').read_text())
    for name, digest in original['files_sha256'].items():
        assert hashlib.sha256((selection/name).read_bytes()).hexdigest() == digest, name
    out = HERE/('remote_bundle_qwen17_thinking' if thinking else 'remote_bundle_qwen17' if qwen17 else 'remote_bundle_l0' if l0 else 'remote_bundle')
    out.mkdir(exist_ok=True)
    files = {}
    def copy(path, name=None):
        name = name or path.name
        shutil.copy2(path, out/name)
        files[name] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    for name in ('bp_requests.jsonl','bridges_requests.jsonl','selfplay_resets.environment.jsonl'):
        copy(selection/name)
    if l0 or qwen17:
        pack = ROOT/'examples/social_bp/b_l0_isolated_v1'
        probe = json.loads((pack/'probe_manifest.json').read_text())
        assert hashlib.sha256((pack/'requests.jsonl').read_bytes()).hexdigest() == probe['requests_sha256']
        assert probe['conditions'] == 6 and probe['formal_requests'] == 48 and probe['test_requests'] == 0
        copy(pack/'requests.jsonl', 'l0_requests.jsonl' if qwen17 else 'bridges_requests.jsonl')
        copy(pack/'probe_manifest.json', 'l0_probe_manifest.json')
    copy(selection/'manifest.json', 'selection_manifest.json')
    for name in ('runtime_v4.tar.gz','runtime_v4.sha256','unpack_runtime.py'):
        copy(ROOT/'examples/outcome_selfplay_nus'/name)
    assert files['runtime_v4.tar.gz'] == original['source_sha256']['examples/outcome_selfplay_nus/runtime_v4.tar.gz']
    copy(ROOT/'training/b_sft/remote_bp_probe.py')
    for name in ('run_remote.py','run_remote.sh','diagnose_cpu.py','capture_performance.py'):
        copy(HERE/name)
    old_manifest = json.loads((ROOT/'examples/bp_pilot_probe_nus/bundle/manifest.json').read_text())
    manifest = dict(version='social-probe-2gpu-v1', files=files, bp_template_sha256=old_manifest['template_sha256'],
                    conditions=dict(bp=28, bridges=6 if l0 else 18, selfplay=12), test_selected=0,
                    scoring_labels_uploaded=False, hidden_worlds='Environment reset file only; learner uses safe_observation',
                    training_started=False)
    if l0:
        manifest.update(version='social-probe-l0-2gpu-v1', allowed_stages=['bridges'],
                        formal_conditions=6, formal_responses=48,
                        selection_note='L0 probe manifest replaces historical bridge selection; old BP is preflight only; no self-play stage.')
    if qwen17:
        copy(HERE/'qwen17_profile.json')
        template_name = 'qwen17_thinking.jinja' if thinking else 'qwen17_nonthinking.jinja'
        copy(HERE/template_name)
        copy(HERE/'probe_generation_config.json')
        copy(HERE/'launch_qwen17.sh')
        copy(HERE/'download_qwen17.py')
        profile = json.loads((HERE/'qwen17_profile.json').read_text())
        if thinking:
            copy(HERE/'launch_qwen17_thinking.sh')
            copy(HERE/'validate_thinking.py')
            profile.update(enable_thinking=True, template_filename=template_name,
                           effective_template_sha256=files[template_name], reasoning_parser='deepseek_r1',
                           sampling_note='Paired with nonthinking probe: same questions, seeds and sampling parameters; thinking plus final answer share 1024 output tokens.')
            (out/'qwen17_profile.json').write_text(json.dumps(profile, indent=2)+'\n')
            files['qwen17_profile.json'] = hashlib.sha256((out/'qwen17_profile.json').read_bytes()).hexdigest()
        manifest.update(version='social-probe-qwen17-v1', model_profile=profile,
                        bp_template_sha256=profile['original_template_sha256'],
                        allowed_stages=['bp', 'bridges', 'l0', 'selfplay'])
        manifest['conditions']['l0'] = 6
        if thinking:
            manifest['version'] = 'social-probe-qwen17-thinking-v1'
    (out/'bundle_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    assert {p.name for p in out.iterdir() if p.name != '__pycache__'} == set(files)|{'bundle_manifest.json'}, 'Unexpected stale files in bundle'
    print(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--l0', action='store_true', help='Build the separate six-question L0 upload bundle')
    group.add_argument('--qwen17', action='store_true', help='All previous small probes on Qwen3-1.7B')
    group.add_argument('--qwen17-thinking', action='store_true', help='Same Qwen3-1.7B probes with thinking enabled')
    args = parser.parse_args()
    main(l0=args.l0, qwen17=args.qwen17, thinking=args.qwen17_thinking)
