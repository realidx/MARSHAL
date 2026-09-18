"""CPU-only sampling, native episode transitions and auditable GRPO grouping."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import math
import os

from training.social_mixed.weighted_rules import OutcomeRules
from training.social_mixed import policy_prompt as sp_prompt

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('SOCIAL_DATA_DIR', ROOT/'examples/social_mixed/data_binary_linear_v3')).resolve()


def seed_for(*values):
    return int(hashlib.sha256(json.dumps(values).encode()).hexdigest()[:8], 16)


def load_data():
    manifest = json.loads((DATA/'manifest.json').read_text())
    result = {}
    for name, expected in manifest['prompt_sources'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f'Prompt changed since label review: {name}')
    for name in ('bp_train.jsonl','bp_validation.jsonl','selfplay_train.jsonl','selfplay_validation.jsonl'):
        record=manifest['files'][name]
        payload = (DATA/name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record['sha256']:
            raise ValueError(f'Data changed after preparation: {name}')
        rows = [json.loads(line) for line in payload.splitlines()]
        split = 'validation' if 'validation' in name else 'train'
        assert all(r['split']==split for r in rows)
        from training.social_mixed.scoring_scope import validate_rows
        validate_rows(rows, name)
        result[name.removesuffix('.jsonl')] = rows
    return result


class Episode:
    def __init__(self, reset, group, replica, seed):
        self.reset = reset
        self.rules = OutcomeRules(reset['raw'])
        self.world = tuple(tuple(row) for row in reset['realized_world'])
        if self.world not in self.rules.worlds:
            raise ValueError('Reset world outside public prior')
        self.node = self.rules.initial()
        self.group, self.replica, self.seed = group, replica, seed
        self.attempt = 0
        self.decisions = 0
        self.calls = []
        self.penalties = [0.0]*self.rules.spec.n_players
        self.terminal = None
        self.status = 'running'

    def observation(self):
        player = self.rules.actor(self.node)
        obs = self.rules.observation(self.node, player, self.world[player])
        forbidden = {'teacher', 'worlds', 'private_preferences', 'type_catalogues', 'public_type_catalogues', 'certificate'}
        def check(value):
            if isinstance(value, dict):
                assert not forbidden.intersection(value)
                for child in value.values(): check(child)
            elif isinstance(value, (list, tuple)):
                for child in value: check(child)
        check(obs)
        return obs

    def request(self):
        obs = self.observation()
        messages = [dict(role='system', content=sp_prompt.SYSTEM), dict(role='user', content=sp_prompt.render(obs))]
        from training.social_mixed.prompt_clarification import VERSION,clarify
        if self.reset.get('prompt_clarification')==VERSION:
            messages[1]['content']=clarify(messages[1]['content'])
        if self.attempt:
            messages.append(dict(role='user', content=sp_prompt.RETRY))
        return dict(messages=messages, tools=sp_prompt.tools_for(obs),
                    seed=seed_for(self.seed, self.group, self.replica, self.decisions, self.attempt))

    def accept(self, generated):
        actor = self.rules.actor(self.node)
        obs = self.observation()
        completion = generated['completion']
        action = None
        valid = False
        if completion['finish_reason'] != 'length':
            try:
                calls = completion['raw_message'].get('tool_calls') or []
                if len(calls) != 1:
                    raise ValueError('Exactly one native tool call required')
                call = calls[0]['function']
                action = sp_prompt.decode_call(obs, call['name'], json.loads(call['arguments']))
                legal = {json.dumps(a.to_dict(), sort_keys=True): a for a in self.rules.actions(self.node)}
                native = legal[json.dumps(action, sort_keys=True)]
                valid = True
            except (ValueError, KeyError, TypeError):
                pass
        penalty = 0.0 if valid else -0.1
        self.penalties[actor] += penalty
        record = dict(generated, kind='selfplay', skill='outcome', group=f'{self.group}:p{actor}',
                      unit=f'{self.group}:r{self.replica}:p{actor}', replica=self.replica,
                      player=actor, decision=self.decisions, attempt=self.attempt,
                      valid=valid, protocol_cost=penalty, action=action,
                      observation=obs, reset_id=self.reset['id'])
        self.calls.append(record)
        if not valid:
            if self.attempt == 0:
                self.attempt = 1
            else:
                self.status = 'truncated_response' if completion['finish_reason']=='length' else 'invalid_action'
            return
        self.node = self.rules.step(self.node, native, realized_world=self.world)
        self.attempt = 0
        self.decisions += 1
        if self.node.state.is_terminal:
            self.status = 'terminal'
            self.terminal = list(self.rules.terminal_payoffs(self.node, self.world))
            # Independent utility recomputation, including linear and negative payoffs.
            bits = self.node.state.snapshot_commitments()
            satisfaction = [float(all(bits[a.player_id][a.action_id] for a in g.required_actions)) if g.binary
                            else sum(bits[a.player_id][a.action_id] for a in g.required_actions)/len(g.required_actions)
                            for g in self.rules.spec.goals]
            expected = [sum(v*s for v,s in zip(row, satisfaction)) for row in self.world]
            assert all(abs(a-b)<1e-9 for a,b in zip(expected, self.terminal))
        elif self.decisions > 2*len(self.rules.spec.round_robin):
            raise RuntimeError('Native game exceeded finite proposal/response bound')

    def units(self):
        return [dict(group=f'{self.group}:p{p}', unit=f'{self.group}:r{self.replica}:p{p}',
                     kind='selfplay', utility=None if self.terminal is None else self.terminal[p],
                     protocol=self.penalties[p], replica=self.replica)
                for p in range(self.rules.spec.n_players)]

    def summary(self):
        return dict(reset=self.reset, group=self.group, replica=self.replica, status=self.status,
                    terminal_utility=self.terminal, protocol=self.penalties, decisions=self.decisions)


def centered(values):
    mean = sum(values)/len(values)
    var = sum((v-mean)**2 for v in values)/len(values)
    if var < 1e-16:
        return [0.0]*len(values)
    return [(v-mean)/(math.sqrt(var)+1e-6) for v in values]


def arm_mixture(arm):
    return {'mixed': {'B': .25, 'P': .25, 'selfplay': .5},
            'selfplay': {'selfplay': 1.0},
            'bp': {'B': .5, 'P': .5}}[arm].copy()


PROTOCOL_VERSION = 'call-local-negative-v1'


def assign_advantages(rows, units, arm, protocol_coefficient=0.2):
    """Task advantage for valid calls; uncentered negative signal for failures.

    Incomplete SP groups have no outcome advantage. Episode protocol totals are
    retained for auditing only, never used to reward or punish other calls.
    """
    if not math.isfinite(protocol_coefficient) or protocol_coefficient <= 0:
        raise ValueError('Protocol coefficient must be finite and positive')
    groups = defaultdict(list)
    for unit in units:
        groups[unit['group']].append(unit)
    advantages = {}
    metrics = Counter()
    for group, members in groups.items():
        assert len({u['replica'] for u in members}) == len(members)
        assert len(members) >= 2
        kind = members[0]['kind']
        complete = all(u['utility'] is not None for u in members)
        values = [u['utility'] if complete else 0.0 for u in members]
        adv = centered(values)
        # Task-gradient coverage is distinct from formatting/protocol rewards.
        if kind in ('B', 'P'):
            labels = {u.get('diagnostic_cell', 'legacy') for u in members}
            assert len(labels) == 1
            cell = next(iter(labels))
            prefix = f'task_signal/{cell}'
            metrics[prefix+'/groups'] += 1
            metrics[prefix+'/nonzero_advantage_groups'] += int(any(abs(a)>1e-9 for a in adv))
            metrics[prefix+'/utility_mixed_groups'] += int(complete and max(u['utility'] for u in members)-min(u['utility'] for u in members)>1e-9)
            metrics[prefix+'/correct_samples'] += sum(u['utility']==1 for u in members)
            metrics[prefix+'/samples'] += len(members)
        metrics[f'{kind}/groups'] += 1
        metrics[f'{kind}/mixed_groups'] += int(max(values)-min(values)>1e-9)
        metrics[f'{kind}/outcome_incomplete_groups'] += int(not complete)
        if complete:
            rewards = [u['utility'] for u in members]
            metrics[f'{kind}/utility_mixed_groups'] += int(max(rewards)-min(rewards)>1e-9)
        for unit, value in zip(members, adv):
            advantages[unit['unit']] = value
    by_unit = Counter(r['unit'] for r in rows)
    kind_units = defaultdict(set)
    for r in rows:
        kind_units[r['kind']].add(r['unit'])
    proportions = arm_mixture(arm)
    if set(kind_units) != set(proportions):
        raise ValueError(f'Missing task domain: {set(kind_units)}')
    # Worker averages rows over all microbatches. These weights produce exactly
    # the specified task mixture, averaging decisions within each player episode.
    for r in rows:
        completion=r.get('completion',{})
        status=r.get('score',{}).get('status')
        if completion.get('status')=='infrastructure_failure' or status=='infrastructure_failure':
            raise ValueError('Infrastructure failure cannot enter optimizer data')
        truncated=completion.get('finish_reason')=='length' or status=='truncated'
        invalid=truncated or (not r.get('valid',True) if r['kind']=='selfplay' else status=='format_failure')
        r['task_advantage']=0.0 if invalid else advantages[r['unit']]
        r['protocol_advantage']=-protocol_coefficient if invalid else 0.0
        r['advantage']=r['task_advantage']+r['protocol_advantage']
        r['protocol_failure']='truncated' if truncated else 'invalid_action' if invalid else None
        r['advantage_version']=PROTOCOL_VERSION
        r['loss_weight'] = len(rows)*proportions[r['kind']]/len(kind_units[r['kind']])/by_unit[r['unit']]
        prefix=f"{r['kind']}/call_signal"
        metrics[prefix+'/calls']+=1
        metrics[prefix+'/truncated']+=int(truncated)
        metrics[prefix+'/invalid_nontruncated']+=int(invalid and not truncated)
        metrics[prefix+'/protocol_negative_calls']+=int(invalid)
        metrics[prefix+'/nonzero_task_calls']+=int(abs(r['task_advantage'])>1e-9)
        metrics[prefix+'/task_abs_weighted_mass']+=abs(r['task_advantage'])*r['loss_weight']/len(rows)
        metrics[prefix+'/protocol_abs_weighted_mass']+=abs(r['protocol_advantage'])*r['loss_weight']/len(rows)
    assert abs(sum(r['loss_weight'] for r in rows)-len(rows))<1e-6
    return dict(metrics)


class Collector:
    def __init__(self, data, generate, seed=42, concurrency=32, protocol_coefficient=0.2):
        if concurrency<4 or concurrency%4:raise ValueError("Concurrency must be a positive multiple of four")
        self.data, self.generate, self.seed, self.concurrency = data, generate, seed, concurrency
        self.protocol_coefficient=protocol_coefficient

    def collect(self, step, arm, token_target=65536, validation=False):
        arm_mixture(arm)  # Reject unknown arms before generating samples.
        from training.social_mixed.prompt_clarification import request
        from training.b_sft.social_bp_training import reward
        split = 'validation' if validation else 'train'
        rng = random.Random(seed_for(self.seed, step, split))
        rows, units, games = [], [], []
        tokens = 0
        # Small validation is fixed across arms and checkpoints; no training gate.
        if validation:
            rng = random.Random(seed_for(self.seed, 'validation'))
        if arm in ('mixed','bp') or validation:
            candidates = self.data[f'bp_{split}']
            from training.social_mixed.curriculum_sampling import select
            selected = select(candidates,step,self.seed,validation)
            jobs = []
            for task in selected:
                group = f'{split}:step{step}:bp:{task["id"]}'
                for replica in range(2 if validation else 8):
                    req = request(task, 'action_tools', task.get('name_variant', 0))
                    req['seed'] = seed_for(self.seed, task['id'], replica, 0 if validation else step)
                    jobs.append((task, group, replica, req))
            for start in range(0, len(jobs), self.concurrency):
                chunk = jobs[start:start+self.concurrency]
                generated = self.generate([j[3] for j in chunk])
                assert len(generated)==len(chunk)
                for (task, group, replica, req), output in zip(chunk, generated):
                    scored = reward(task, output['completion'])
                    assert scored['reward'] is not None
                    unit = f'{group}:r{replica}'
                    rows.append(dict(output, kind=task['task'], skill=task['pool'], group=group,
                                     unit=unit, replica=replica, task_id=task['id'], kernel=task['kernel'], background_profile=task['background_profile'], score=scored))
                    role = ('full_support' if len(task['teacher']['gold']['possible_preferences'])==3 else 'reduced_support') if task['task']=='B' else task.get('information_role','na')
                    cell = '/'.join((task['kernel'], task['completion_mode'], role, task.get('p4_case','na')))
                    rows[-1]['diagnostic_cell'] = cell
                    units.append(dict(group=group, unit=unit, replica=replica, kind=task['task'],
                                      diagnostic_cell=cell, utility=scored['reward'], protocol=0.0))
                    tokens += len(output['response_ids'])
        cursor = peak_active = 0
        if arm != 'bp' or validation:
            candidates = self.data[f'selfplay_{split}']
            from training.social_mixed.curriculum_sampling import reset_order as schedule_resets
            reset_order = schedule_resets(candidates,rng)
            cursor = 0
            episodes = []
            def admit_group():
                nonlocal cursor
                reset=candidates[reset_order[cursor%len(reset_order)]]
                group=f'{split}:step{step}:sp{cursor}:{reset["id"]}'
                episodes.extend(Episode(reset,group,replica,self.seed) for replica in range(2 if validation else 4))
                cursor+=1
            initial_groups=2 if validation else self.concurrency//4
            for _ in range(initial_groups):admit_group()
            peak_active=0
            while True:
                active=[e for e in episodes if e.status=='running']
                # Refill only in complete four-replica groups. Stop admitting once
                # the token budget is reached; drain every previously admitted game.
                if not validation and tokens<token_target:
                    while len(active)+4<=self.concurrency:
                        admit_group()
                        active=[e for e in episodes if e.status=='running']
                if not active:break
                peak_active=max(peak_active,len(active))
                for start in range(0,len(active),self.concurrency):
                    chunk=active[start:start+self.concurrency]
                    outputs=self.generate([e.request() for e in chunk])
                    assert len(outputs)==len(chunk)
                    for episode,output in zip(chunk,outputs):
                        episode.accept(output)
                        tokens+=len(output['response_ids'])
                # Retire finished games immediately; their siblings can keep running.
                finished=[e for e in episodes if e.status!='running']
                for episode in finished:
                    rows.extend(episode.calls);units.extend(episode.units());games.append(episode.summary())
                episodes=[e for e in episodes if e.status=='running']
        metrics = assign_advantages(rows, units, 'mixed' if validation else arm, self.protocol_coefficient)
        metrics.update(generated_tokens=tokens, rows=len(rows), games=len(games),
                       terminal_games=sum(g['status']=='terminal' for g in games),
                       admitted_reset_groups=cursor,peak_active_games=peak_active,
                       truncated=sum(r['completion']['finish_reason']=='length' for r in rows))
        for cell in sorted({r['diagnostic_cell'] for r in rows if 'diagnostic_cell' in r}):
            chosen = [r for r in rows if r.get('diagnostic_cell')==cell]
            prefix = 'behavior/'+cell
            metrics[prefix+'/samples'] = len(chosen)
            metrics[prefix+'/accuracy'] = sum(r['score']['reward'] for r in chosen)/len(chosen)
            metrics[prefix+'/format_failure_rate'] = sum(r['score']['status']=='format_failure' for r in chosen)/len(chosen)
            metrics[prefix+'/truncation_rate'] = sum(r['completion']['finish_reason']=='length' for r in chosen)/len(chosen)
            metrics[prefix+'/investigate_call_rate'] = sum(any(c.get('function',{}).get('name')=='INVESTIGATE' for c in (r['completion'].get('raw_message',{}).get('tool_calls') or [])) for r in chosen)/len(chosen)
        for kind in ('B','P'):
            for skill in ('all','formation','maintain','update','complete','uncertain','result_use','information'):
                chosen = [r for r in rows if r['kind']==kind and (skill=='all' or r['skill']==skill)]
                if chosen:
                    metrics[f'{kind}/{skill}/accuracy'] = sum(r['score']['reward'] for r in chosen)/len(chosen)
                    metrics[f'{kind}/{skill}/wrong_fullset'] = sum(r['score'].get('predicted_full_set',False) and not r['score']['correct'] for r in chosen)/len(chosen)
        return rows, units, games, metrics
