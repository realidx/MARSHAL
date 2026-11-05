"""Freeze a small tools-only subset; export visible requests for a Git checkout.

Run locally, not on the cluster. Teacher labels stay under new/local_data.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


SOURCES = (
    'one_response_accept', 'one_response_reject',
    'irrelevant_goal_response_maintains_three', 'maintain_favored_goal_0',
    'joint_unknown_favored_disappears', 'one_offer_forms_singleton',
    'one_offer_changes_favored_only', 'short_private_fact_0',
    'three_player_1_update', 'three_player_3_update',
    'favored_three_types_goal_0', 'joint_unknown_maintain',
    'complete_own_gain', 'complete_altruistic_tie',
    'investigate_acquisition_root', 'acquisition_same_game_last_turn',
    'private_result_avoid', 'private_result_want',
    'acquisition_avoid_next_proposal', 'acquisition_neutral_next_proposal',
    'qualitative_avoid_likely_0', 'qualitative_avoid_unlikely_0',
    'qualitative_avoid_certain_0', 'qualitative_want_very_likely_0',
)
CONTRASTS = ('one_response_accept', 'maintain_favored_goal_0',
             'investigate_acquisition_root', 'acquisition_avoid_next_proposal')


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def build(source, local, visible):
    source, local, visible = map(Path, (source, local, visible))
    if local.exists() or visible.exists():
        raise FileExistsError('Choose fresh local and visible output directories')
    tasks = read(source / 'tasks.jsonl')
    by_condition = {(t['source'], t['name_variant'], t['short_teaching']): t for t in tasks
                    if t['output_arm'] == 'action_tools'}
    keys = [(s, 0, False) for s in SOURCES]
    keys += [(s, 1, taught) for s in CONTRASTS for taught in (False, True)]
    selected = [by_condition[k] for k in keys]
    requests = {r['task_id']: r for r in read(source / 'bundle/requests.jsonl')}
    rows = [requests[t['id']] for t in selected]
    assert len(rows) == 32 and Counter(t['task'] for t in selected) == {'B': 16, 'P': 16}
    for row in rows:
        req = row['request']
        assert row['output_arm'] == 'action_tools' and req['tools']
        assert req['parallel_tool_calls'] is False and req['tool_choice'] == 'auto'
        assert req['max_tokens'] == 1024 and 'response_format' not in req
    local.mkdir(parents=True)
    visible.mkdir(parents=True)
    (local / 'tasks.jsonl').write_text(''.join(json.dumps(t) + '\n' for t in selected))
    raw = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
    (visible / 'requests.jsonl').write_text(raw)
    shutil.copyfile(source / 'bundle/remote_bp_probe.py', visible / 'remote_bp_probe.py')
    manifest = dict(version='bp-soc-small-v1', prompt_version='bp-readable-prompt-v2',
        conditions=32, conditions_by_task={'B': 16, 'P': 16}, group_size=2,
        formal_requests=64, preflight_requests=2, temperature=0.8, max_tokens=1024,
        parameters_updated=False, output_arm='action_tools',
        files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(visible.iterdir())})
    (visible / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copytree(visible, local / 'bundle')
    (local / 'selection.json').write_text(json.dumps(dict(
        source=str(source), keys=keys, note='24 base conditions plus 4 matched renamed/no-teaching and renamed/teaching pairs. '
        'Two samples per condition are diagnostic only; not a GRPO learnability estimate.'), indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='new/local_data/social_runs/bp_readable_prompt_review_v2')
    parser.add_argument('--local', default='new/local_data/social_runs/bp_soc_probe_r1')
    parser.add_argument('--visible', default='examples/bp_probe_nus/bundle')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.local, args.visible), indent=2))
