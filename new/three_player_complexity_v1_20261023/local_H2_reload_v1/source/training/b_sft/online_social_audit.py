"""Independent native replay and whole-world likelihood checks for online data."""
from pathlib import Path
import json
import hashlib
import numpy as np

from training.b_sft.online_social import OnlineSocial, run_episode
from training.b_sft.social_cases_expand import information_fixture
from training.b_sft.shared_teacher import native
from training.b_sft.social_rollout import queries_for
from training.b_sft.favored_belief import marginal
from benac_p.endgame_diagnose import decode_action


def verify(fixtures, questions, traces):
    by_source = {}; checked = 0; qchecks = 0; pchecks = 0; direct_checks = 0
    for source, raw in fixtures.items():
        rules, worlds, _ = native(raw)
        episodes = [e for e in traces if e['source'] == source]
        for e in episodes:
            world = tuple(map(tuple, e['environment_world']))
            if world not in worlds: raise ValueError('Unknown actual world')
            node = rules.initial()
            if len(e['events']) != len(e['history']): raise ValueError('Missing event')
            for a, event in zip(e['history'], e['events']):
                if event['actor'] != rules.actor(node) or event['action'] != a: raise ValueError('Event chronology mismatch')
                if event['kind'] == 'learner' and event['actor'] != raw['ego']: raise ValueError('Wrong learner actor')
                if event['kind'] == 'learner' and event['worlds_before'] != event['worlds_after']:
                    raise ValueError('Learner intervention incorrectly filtered partner types')
                node = rules._apply(node, decode_action(a))
            if not node.state.is_terminal: raise ValueError('Nonterminal outcome')
            if (np.array(world) @ node.state.goal_satisfaction()).tolist() != e['utilities']:
                raise ValueError('Incorrect terminal payoff')
            checked += 1
        by_source[source] = episodes
    for q in questions:
        raw = fixtures[q['source']]; h = q['input']['history']; ego = raw['ego']
        rules, _, types = native(raw); node = rules.initial()
        for a in h: node = rules._apply(node, decode_action(a))
        if node.state.public_state() != q['input']['public_state'] or rules.actor(node) != ego:
            raise ValueError('Prompt does not match native decision')
        if q['input']['own_preferences'] != raw['own_preferences']: raise ValueError('Own observation mismatch')
        if q['input']['pending_offer'] != (None if node.pending is None else node.pending.to_dict()):
            raise ValueError('Pending offer mismatch')
        if 'B_task_version' in q['input']:
            if q['input']['queries'] != queries_for(types, ego):
                raise ValueError('Queries must depend only on initial public catalogues')
            if q['input']['legal_actions'] != [a.to_dict() for a in rules.actions(node)]:
                raise ValueError('Visible action set differs from native game')
        es = [e for e in by_source[q['source']] if e['history'][:len(h)] == h]
        compatible = tuple(sorted({tuple(map(tuple, e['environment_world'])) for e in es}))
        if not compatible: raise ValueError('Unreachable prompt')
        gold = q['teacher']['B_by_target']
        if gold is not None:
            expected = [dict(**target, **marginal(compatible, target['player'], target['goal']))
                        for target in queries_for(types, ego)]
            if gold != expected: raise ValueError('B differs from independently reconstructed history likelihood')
            qchecks += 1
        values = q['teacher'].get('P_reference', {})
        if values.get('mask'):
            if [v['action'] for v in values['values']] != [a.to_dict() for a in rules.actions(node)]:
                raise ValueError('P teacher omitted or reordered legal actions')
            for row in values['values']:
                if values.get('basis') == 'direct_terminal':
                    child=rules._apply(node,decode_action(row['action']))
                    if not child.state.is_terminal:raise ValueError('Nonterminal action labeled direct terminal')
                    actual=sum(p*s for p,s in zip(raw['own_preferences'],child.state.goal_satisfaction()))
                    if abs(actual-row['value'])>1e-8:raise ValueError('Wrong direct terminal utility')
                    direct_checks+=1
                matched = [e for e in es if len(e['history']) > len(h) and e['history'][len(h)] == row['action']]
                by_world = {}
                for e in matched:
                    world = tuple(map(tuple, e['environment_world']))
                    by_world.setdefault(world, set()).add(e['utilities'][ego])
                if set(by_world) != set(compatible): continue  # Unsampled action.
                if any(len(v) != 1 for v in by_world.values()):
                    continue  # Arbitrary future LM policies: not a reference-Q check.
                actual = np.mean([next(iter(v)) for v in by_world.values()])
                if abs(actual-row['value']) > 1e-8: raise ValueError('Reference P differs from completed continuation')
                pchecks += 1
    return dict(terminal_trajectories_checked=checked, B_snapshots_checked=qchecks,
                sampled_reference_P_values_checked=pchecks,all_direct_terminal_P_values_checked=direct_checks)


def audit_training(out):
    if out.exists(): raise ValueError('Use a new output directory')
    out.mkdir(parents=True); raw, prefix = information_fixture(); traces = []; questions = []
    base = OnlineSocial(raw, prefix)
    for policy in ('first', 'last'):
        source = 'information-'+policy
        for world in base.game.worlds:
            def b(ctx): return [dict(player=1, goal=0, possible_preferences=['avoid'], favored='avoid')]
            def p(ctx):
                if ctx['model_beliefs'] != b(ctx): raise ValueError('B was oracle-replaced')
                return ctx['legal_actions'][0 if policy == 'first' else -1]
            e = run_episode(raw, prefix, world, b, p)
            e['source'] = source; traces.append(e)
            for r in e['records']:
                questions.append(dict(source=source, input=r['input'], teacher=dict(B_by_target=r['teacher_B'])))
    result = verify({e['source']: raw for e in traces}, questions, traces)
    # Cover EVERY legal first action, not just the two deliberately wrong scripts.
    all_branches = []
    for action in base.game.rules.actions(base.node):
        for world in base.game.worlds:
            env = base.fork(); before = env.worlds; env.step(action, kind='learner')
            if env.worlds != before: raise ValueError('Intervention filtered types')
            outcome = env.finish_reference(world)
            all_branches.append(dict(action=action.to_dict(), history=env.history, events=env.events,
                                     environment_world=world, utilities=outcome, source='all-actions',
                                     usable=env.invalid_reason is None))
    branch_check = verify({'all-actions': raw}, [], all_branches)
    result.update(all_first_actions=len(base.game.rules.actions(base.node)), branch_check=branch_check,
                  scripted_B_passed_unchanged=True, actual_LM=False,
                  all_normal_runs_usable=all(e['usable_for_training'] for e in traces) and all(e['usable'] for e in all_branches))
    (out/'scripted_episodes.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in traces))
    (out/'all_first_actions.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in all_branches))
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    (out/'checksums.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.iterdir() if p.is_file()}, indent=2)+'\n')
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args(); print(json.dumps(audit_training(a.output_dir), indent=2))
