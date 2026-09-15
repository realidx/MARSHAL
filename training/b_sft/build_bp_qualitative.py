"""Certify qualitative belief contrasts on the generated native short games."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from training.b_sft.debug.audit_readable_pretraining import reconstruct, independent_final_actions
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.social_p_qualitative import robust_actions, WIDE_ENVELOPES, WORDS
from training.b_sft.social_bp_curriculum import digest
from training.b_sft.social_bp_training import reward, native_completion


def build(tasks, limit=160):
    examined = 0
    for task in tasks:
        if task['task'] != 'P' or task['pool'] != 'uncertain': continue
        inp = task['input']; unknown = inp['supplied_belief']['unresolved_preferences']
        if len(unknown) != 1 or inp['private_results']: continue
        raw, own = reconstruct(inp)
        q = unknown[0]
        if any(len(rows) != 1 for p, rows in raw['type_catalogues'].items() if int(p) != q['player']): continue
        e = PrivateEpisode(raw, inp['imposed_setup']); payoffs = independent_final_actions(e)
        if payoffs is None: continue
        examined += 1
        for value, level in ((-1, 'likely'), (-1, 'unlikely'), (1, 'very_likely')):
            claims = [dict(event=[dict(player=q['player'], goal=q['goal'], value=value)], level=level)]
            cert = robust_actions(payoffs, 0, e.tree.worlds, claims, own_tolerance=.1, social_tolerance=.1, envelopes=WIDE_ENVELOPES)
            if cert['status'] != 'certified': continue
            accepted = [inp['legal_actions'][i] for i in cert['acceptable']]
            if len(accepted) == len(inp['legal_actions']): continue
            t = deepcopy(task)
            t['input']['qualitative'] = dict(description='This is YOUR supplied current assessment. It replaces the generator prior for this decision.',
                assessments=[dict(player=q['player'], goal=q['goal'], preference='want' if value == 1 else 'avoid', qualifier=WORDS[level][0])])
            t['teacher'].update(acceptable_actions=accepted, qualitative_certificate=cert, audit_envelopes=WIDE_ENVELOPES,
                per_world_payoffs=payoffs.tolist(), worlds=e.tree.worlds, claims=claims)
            t['teacher'].pop('action_values')
            t['answer_signature'] = json.dumps(accepted, sort_keys=True)
            t['qualitative_level'] = level
            t['id'] = digest((t['mechanism'], 'qualitative', t['input'])); t['native_task_id'] = t['id']
            assert reward(t, native_completion(t))['reward'] == 1
            yield t
        if examined >= limit: break


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--data', required=True); p.add_argument('--out', required=True); p.add_argument('--limit', type=int, default=160)
    a = p.parse_args(); rows = [json.loads(s) for s in Path(a.data).read_text().splitlines()]
    tasks = list(build(rows, a.limit)); Path(a.out).write_text(''.join(json.dumps(t)+'\n' for t in tasks))
    print(json.dumps(dict(tasks=len(tasks))))
