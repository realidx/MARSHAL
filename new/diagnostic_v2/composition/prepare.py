"""Freeze a small teacher-reachable, same-history B/P diagnostic. CPU only."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'new/bp_interface_audit_20260917'))
from audit import independent_final_payoffs
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.b_sft.preference_contract import belief, profile
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_named_probe import present, answer_schema, action_tools
from training.b_sft import review_prompt as wording

VERSION = 'bp-composition-diagnostic-v1'
CONDITIONS = ('B', 'P_gold', 'P_infer')
VALUES = {'want': 1, 'neutral': 0, 'avoid': -1}
NAMES = {v: k for k, v in VALUES.items()}
SOURCES = (
    ('binary_complementarity', '6465d8b4c2aff4f1a189',
     [dict(action='OFFER', partner_id=0, proposer_action=[1, 0], partner_action=[0, 1]),
      dict(response='ACCEPT')]),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def common_context(t):
    v = present(t, 0)
    # Oracle beliefs never alter the shared facts table or chronology.
    v.pop('your_current_belief', None)
    return '\n'.join([
        wording.game_rules(v), '', *wording.layout(v), '', 'PREFERENCE CONDITIONS',
        wording.preference_conditions(v), '', 'HOW OTHER PLAYERS CHOOSE', wording.partner_policy(v),
        'For this diagnostic, voluntary choices follow the selected fixed policy. After any preset events, '
        'initialize every legal choice uniformly and synchronously update player best responses until '
        'the full policy is stable. Randomize uniformly among remaining optimal choices. '
        'This specifies the reference policy; it does not assert uniqueness. '
        'Preset events were required and do not provide evidence of the acting player\'s preferences.',
        '', *wording.chronology(v), '', *wording.decision(v)])


def request(t):
    v = present(t, 0); c = t['condition']
    objective = (f"What do you believe {v['belief_question']['player']}'s preference for "
                 f"{v['belief_question']['goal']} is?" if c == 'B' else
                 'Choose your next action using the supplied correct belief.' if c == 'P_gold' else
                 'Infer the relevant preferences from the visible information and choose your next action.')
    lines = ['YOUR TASK', f'You are {v["you"]}.', objective, '', common_context(t)]
    if c == 'P_gold':
        lines += ['', 'CORRECT CURRENT BELIEF',
            'The following is the correct current joint belief derived from this history and your known facts. '
            'Use it directly. It is supplied only to you, not to other players. '
            'Each row is a complete assignment of the unknown preferences; all unlisted assignments have probability zero.']
        for row in v['your_current_belief']['joint_distribution']:
            lines.append(f"Probability {row['probability']}: " + '; '.join(
                f"{p}: " + ', '.join(f'{g}={value}' for g, value in goals.items())
                for p, goals in row['preferences'].items()))
    lines += ['', 'RESPONSE INSTRUCTIONS']
    if c == 'B':
        lines += [wording.belief_output(v),
                  'Briefly explain your answer, then make exactly one SUBMIT_BELIEFS call. '
                  'Keep the explanation outside the tool arguments.']
        tools = [dict(type='function', function=dict(name='SUBMIT_BELIEFS',
            description='Submit the requested belief judgment.', parameters=answer_schema(t, v)))]
    else:
        lines += [wording.OBJECTIVE,
            'An action is acceptable if it loses at most 0.1 goal-completion points compared with the best action. '
            'When responses are equally good for you, the allowance for helping others is also 0.1 points in total.',
            'Briefly explain your decision, then make exactly one registered game-action tool call. '
            'Keep the explanation outside the tool arguments.']
        tools = action_tools(v)
    return dict(messages=[dict(role='system', content=wording.SYSTEM),
                          dict(role='user', content='\n'.join(lines))],
                tools=tools, tool_choice='auto', parallel_tool_calls=False, max_tokens=1024)


def build():
    source = ROOT / 'examples/social_mixed/data_distribution_v1/bp_train.jsonl'
    by_id = {r['id']: r for r in map(json.loads, source.read_text().splitlines())}
    tasks = []; certificates = []; cases = {}
    for family, source_id, events in SOURCES:
        original = by_id[source_id]; raw, own = reconstruct(deepcopy(original['input']))
        raw['game']['round_robin'] = [1, 0]
        raw['background_prior'] = profile('balanced')
        for provenance in ('voluntary', 'preset'):
            prefix = [] if provenance == 'voluntary' else events
            e = PrivateEpisode(raw, prefix, seconds=30, max_nodes=10000, max_sweeps=128)
            native = audit_native(e.tree); trace = []; path_probability = 1.
            if provenance == 'voluntary':
                for event in events:
                    en = e.tree.entries[e.index]
                    ai = [a.to_dict() for a in en.actions].index(event)
                    likelihood = e.tree.policy[e.index][ai]
                    prob = float(e.weights @ likelihood)
                    assert prob > 0
                    path_probability *= prob
                    trace.append(dict(actor=en.actor, event=event,
                                      likelihood_by_world=likelihood.tolist(), probability=prob))
                    e.observe(event)
            en = e.tree.entries[e.index]; state = en.node.state.public_state()
            assert en.actor == 0 and en.node.pending is None and state['turn_index'] == 1
            post = e._weights(0, own, ())
            prior = e.tree.world_weights * [w[0] == tuple(own) for w in e.tree.worlds]
            prior /= prior.sum()
            slots = [(p, g) for p in range(2) for g in range(len(raw['game']['goals']))
                     if len({w[p][g] for w in e.tree.worlds}) > 1]
            assert len(slots) == 1 and slots[0][0] == 1
            p, g = slots[0]
            mass = {n: float(sum(v for w, v in zip(e.tree.worlds, post) if w[p][g] == value))
                    for n, value in VALUES.items()}
            gold = belief(mass)
            pay = np.array([e.tree.values[c] for c in en.children])
            actions = [a.to_dict() for a in en.actions]
            value = np.einsum('awp,w->ap', pay, post)
            blind_value = np.einsum('awp,w->ap', pay, prior)
            accepted = acceptable(value, 0, actions=actions)
            blind = acceptable(blind_value, 0, actions=actions)
            if provenance == 'voluntary':
                assert not set(accepted) & set(blind), 'Behavior must change acceptable actions'
            else:
                np.testing.assert_allclose(post, prior)
            public = deepcopy(original['input']['public_preferences'])
            joint = []
            for w, weight in zip(e.tree.worlds, post):
                if weight <= 0: continue
                rational = Fraction(float(weight)).limit_denominator(1000000)
                assert abs(float(rational) - weight) < 1e-12
                joint.append(dict(probability=str(rational), preferences=[
                    dict(player=p, goal=g, preference=NAMES[w[p][g]])]))
            assert sum(Fraction(row['probability']) for row in joint) == 1
            inp = dict(game=e.rules.public_game(), player=0, observer=0,
                preference_generation=original['input']['preference_generation'],
                public_preferences=public, own_preferences={f'goal_{j}': NAMES[v] for j, v in enumerate(own)},
                private_results=[], current_state=state, pending_offer=None,
                imposed_setup=deepcopy(prefix), voluntary_history=deepcopy(events if provenance == 'voluntary' else []),
                partner_policy=original['input']['partner_policy'],
                knowledge_rule=original['input']['knowledge_rule'], background_prior=profile('balanced'),
                favored_margin=.1, legal_actions=actions, queries=[dict(player=p, goal=g)],
                supplied_belief=dict(known_preferences=public, unresolved_preferences=[dict(player=p, goal=g)],
                    support='This is YOUR supplied exact joint distribution. Derived from the displayed history.',
                    joint_distribution=joint))
            teacher = dict(gold=gold, preference_weights=mass, acceptable_actions=[actions[j] for j in accepted],
                action_values=value.tolist(), per_world_payoffs=pay.tolist(), worlds=e.tree.worlds,
                own_tolerance=.1, social_tolerance=.1, policy_sha256=e.tree.certificate['policy_sha256'])
            case = f'{family}:{provenance}'
            base = dict(case_id=case, family=family, source_id=source_id, split='diagnostic_development',
                        name_variant=0, training_ready=False, input=inp, teacher=teacher)
            np.testing.assert_allclose(independent_final_payoffs(base), pay, atol=1e-9)
            for cond in CONDITIONS:
                t = deepcopy(base)
                t.update(id=f'{case}:{cond}', condition=cond, task='B' if cond == 'B' else 'P',
                         skill='formation' if cond == 'B' else 'uncertain')
                tasks.append(t)
            cert = dict(case_id=case, family=family, source_id=source_id, provenance=provenance,
                mode=original['completion_mode'], schedule_change=dict(before=original['input']['game']['round_robin'], after=[1, 0]),
                teacher=e.tree.certificate, native_transition_audit=native,
                independent_final_payoffs_match=True, trace=trace,
                history_probability=path_probability if trace else None,
                worlds=e.tree.worlds, prior=prior.tolist(), posterior=post.tolist(), b_gold=gold,
                posterior_acceptable=accepted, prior_acceptable=blind,
                action_values=value.tolist(), prior_action_values=blind_value.tolist(), actions=actions,
                min_regret_of_prior_acceptable_under_posterior=float(value[:, 0].max() - max(value[j, 0] for j in blind)))
            certificates.append(cert); cases[case] = base
        a = cases[f'{family}:voluntary']; b = cases[f'{family}:preset']
        assert a['input']['current_state'] == b['input']['current_state']
        assert a['input']['legal_actions'] == b['input']['legal_actions']
        np.testing.assert_allclose(a['teacher']['per_world_payoffs'], b['teacher']['per_world_payoffs'], atol=1e-9)
        assert not {json.dumps(x, sort_keys=True) for x in a['teacher']['acceptable_actions']} & {
            json.dumps(x, sort_keys=True) for x in b['teacher']['acceptable_actions']}
    # Shared observations and identical action tool interfaces across conditions.
    for case in cases:
        ts = [t for t in tasks if t['case_id'] == case]
        assert len({common_context(t) for t in ts}) == 1
        assert request(ts[1])['tools'] == request(ts[2])['tools']
    requests = [dict(task_id=t['id'], case_id=t['case_id'], condition=t['condition'], request=request(t)) for t in tasks]
    jsonl(HERE / 'tasks.jsonl', tasks)
    jsonl(HERE / 'requests.jsonl', requests)
    (HERE / 'certificates.json').write_text(json.dumps(certificates, indent=2) + '\n')
    # Freeze local dependencies too: evaluation must not silently rescore with a new contract.
    dependencies = [source, Path(__file__), ROOT / 'new/bp_interface_audit_20260917/audit.py']
    dependencies += list((ROOT / 'training/b_sft').glob('*.py'))
    dependencies += list((ROOT / 'third_party/negotiation_benchmark/src/benac_p').glob('*.py'))
    dependencies += list((ROOT / 'training/b_sft/debug').glob('*.py'))
    manifest = dict(version=VERSION, cases=2, independent_structural_families=1, conditions=list(CONDITIONS),
        tasks=len(tasks), default_repeats=8, planned_calls=8 * len(tasks), max_tokens=1024,
        model_calls=0, split='diagnostic_development', training_data_changed=False,
        selection='Teacher-only discovery over existing train geometries adapted to schedule [1,0]; no learner response selection. '
                  'Two selected natural histories plus matched all-preset controls. Not a held-out generalization benchmark.',
        files={name: sha(HERE / name) for name in ('tasks.jsonl', 'requests.jsonl', 'certificates.json')},
        dependencies={str(p.relative_to(ROOT)): sha(p) for p in dependencies})
    (HERE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(cases=manifest['cases'], tasks=len(tasks), planned_calls=manifest['planned_calls'],
                         model_calls=0, families=[x[0] for x in SOURCES]), indent=2))


if __name__ == '__main__':
    build()
