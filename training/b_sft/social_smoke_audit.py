"""Join visible facts, type exclusions and independently replayed action values.

This is a local teacher/prompt audit. It makes no model requests and never uses
teacher answers as P's model_beliefs. Actual LM results belong in a separate run.
"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json

from training.b_sft.online_social import OnlineSocial
from training.b_sft.social_cases import p_input
from training.b_sft.social_dataset_v4 import require_coverage
from training.b_sft.social_lm_eval import load_pack, model_payload, tool_for, system_for, PROMPT_VERSION
from benac_p.endgame_diagnose import decode_action


def inspect(point):
    prefix = []
    for event in point['events']:
        if event['kind'] != 'setup': break
        prefix.append(event['action'])
    env = OnlineSocial(point['raw'], prefix, **point['row']['solver_budgets'])
    evidence = []
    for event in point['events'][len(prefix):]:
        if event['kind'] == 'partner':
            if not env.ensure_teacher(): raise ValueError(env.invalid_reason)
            tree, index, possible = env.position
            comparisons = []
            for own in dict.fromkeys(tree.worlds[i][env.actor] for i in possible):
                label = tree.labels(index, possible, env.actor, own)
                observed = event['action']
                reason = ('retained' if observed == label['selected'] else
                          'residual_native_order' if observed in label['social_optimal_actions'] else
                          'prosocial_tie_rule' if observed in label['own_optimal_actions'] else 'strict_self_value')
                comparisons.append(dict(own_type=own, classification=reason,
                                        observed=observed, alternatives=label['actions']))
            evidence.append(dict(actor=env.actor, observed=event['action'], by_type=comparisons))
        env.step(event['action'], kind=event['kind'])
    ctx = env.context()
    if ctx != point['row']['input']: raise ValueError('Changed visible facts')
    if env.invalid_reason or env.fragile: raise ValueError('Smoke teacher unavailable or fragile')
    if env.belief_table() != point['row']['teacher']['B_by_target']:
        raise ValueError('B replay disagrees with saved supervision')
    reference = point['row']['teacher']['P_reference']
    if not reference['mask']: raise ValueError('Smoke P teacher unavailable')
    action_checks = []
    for value in reference['values']:
        outcomes = []
        for world in env.worlds:
            branch = env.fork()
            branch.step(value['action'], kind='learner')
            utilities = branch.finish_reference(world)
            if branch.invalid_reason: raise ValueError(branch.invalid_reason)
            # Replay the entire path in the native game without a value cache.
            node = env.game.rules.initial()
            for action in branch.history:
                node = env.game.rules._apply(node, decode_action(action))
            if not node.state.is_terminal: raise ValueError('Partial continuation')
            satisfaction = node.state.goal_satisfaction()
            independent = [float(sum(p*s for p, s in zip(row, satisfaction))) for row in world]
            if independent != utilities: raise ValueError('Terminal payoff mismatch')
            outcomes.append(dict(world=world, terminal_commitments=node.state.snapshot_commitments(),
                                 satisfied_goals=[i for i, s in enumerate(satisfaction) if s], utilities=utilities))
        own = sum(o['utilities'][env.actor] for o in outcomes)/len(outcomes)
        others = sum(sum(o['utilities'])-o['utilities'][env.actor] for o in outcomes)/len(outcomes)
        if abs(own-value['value']) > 1e-8 or abs(others-value['others_value']) > 1e-8:
            raise ValueError('Reference value disagrees with complete native continuations')
        action_checks.append(dict(action=value['action'], own_value=own, others_value=others,
                                  terminal_outcomes=outcomes))
    inputs = {'B': model_payload('B', ctx), 'P': model_payload('P', p_input(ctx,
        dict(submission_status='not_run', judgments_available=False)))}
    requests = [dict(stage=stage, messages=[dict(role='system', content=system_for(stage)),
                dict(role='user', content=json.dumps(inp, ensure_ascii=False))],
                tools=[tool_for(stage, inp)], tool_choice='auto', parallel_tool_calls=False,
                max_tokens=1024) for stage, inp in inputs.items()]
    text = json.dumps(requests, ensure_ascii=False)
    if any('\u4e00' <= c <= '\u9fff' for c in text): raise ValueError('Non-English request text')
    for inp in inputs.values():
        if any(k in inp for k in ('teacher_B', 'B_by_target', 'teacher_counts', 'environment_world', 'P_reference')):
            raise ValueError('Teacher data entered model input')
    return dict(id=point['row']['id'], facts=inputs['B'],
                allowed_partner_explanations=env.belief_table(), solver_exclusions=evidence,
                action_value_basis=reference['basis'], verified_action_values=action_checks,
                prepared_requests=requests, model_answer=None,
                model_status='not_run; P preview uses explicit unavailable B, actual evaluation uses actual model B')


def run(data, out):
    _, points = load_pack(data, 'both')
    require_coverage([p['row'] for p in points], smoke=True)
    if out.exists(): raise ValueError('Use a fresh audit directory')
    out.mkdir(parents=True)
    counts = Counter()
    for point in points:
        case = inspect(point)
        (out/(case['id']+'.json')).write_text(json.dumps(case, indent=2)+'\n')
        counts['points'] += 1
        counts['action_values_verified'] += len(case['verified_action_values'])
        counts['native_terminal_rollouts'] += sum(len(a['terminal_outcomes']) for a in case['verified_action_values'])
        counts['partner_events_audited'] += len(case['solver_exclusions'])
        print(json.dumps(dict(id=case['id'], checked=True)), flush=True)
    summary = dict(actual_LM=False, prompt_version=PROMPT_VERSION, **counts,
                   dataset_checksums_sha256=hashlib.sha256((data/'checksums.json').read_bytes()).hexdigest(),
                   implementation_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                       for name in ('social_smoke_audit.py','social_lm_eval.py','social_presentation.py','online_social.py','shared_teacher.py')},
                   all_checks_passed=True, raw_model_answers_available=False,
                   scope='All smoke action values replayed to native terminal payoffs under the declared reference continuation. No model-quality or causal claim.')
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('new/local_data/social_smoke_v4'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.data_dir, args.output_dir), indent=2))
