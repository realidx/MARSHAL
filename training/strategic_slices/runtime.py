"""Batched closed-loop windows and full games with the same action protocol."""
from collections import Counter, defaultdict
from copy import deepcopy
import math

import numpy as np
from .common import VERSION, seed_for, request, decode, materialize_node, replay_node


class Rollout:
    def __init__(self, dataset, parent, seed, world_index, slice_record=None, focal=None):
        self.parent, self.slice, self.focal = parent, slice_record, focal
        self.world_index = world_index
        self.rng = np.random.default_rng(seed)
        uses_reference = slice_record is not None or focal is not None
        self.fixed = parent.get('reference_backend') == 'fixed-myopic-v1'
        self.bounded = parent.get('reference_backend') == 'bounded-next-own-v1'
        self.rolling = None
        if self.bounded and focal is not None and slice_record is None:
            from .bounded_data import RecedingReference
            self.rolling = RecedingReference(dataset, parent)
        self.reference = (dataset.reference(parent, slice_record) if self.bounded else dataset.reference(parent)) if uses_reference and not self.rolling else None
        self.tree = self.reference if uses_reference and not self.fixed else None
        self.rules = self.reference.rules if self.reference else dataset.rules(parent)
        self.world = self.rules.worlds[world_index]
        self.index = slice_record['root_index'] if slice_record else 0
        self.history = list(slice_record['history']) if slice_record else []
        if self.fixed or (self.bounded and slice_record):
            self.node = replay_node(self.rules, self.history, self.world)
            if slice_record and (self.rules.actor(self.node) != slice_record['ego'] or
                                 list(self.world[slice_record['ego']]) != slice_record['own'] or
                                 list(map(list, self.node.state.private_results[slice_record['ego']])) !=
                                 list(map(list, slice_record['private_results']))):
                raise ValueError('Realized world or history is incompatible with slice entrance')
        else:
            self.node = materialize_node(self.tree, self.index, self.world) if self.tree else self.rules.initial()
        self.ego = slice_record['ego'] if slice_record else focal
        self.controlled = 0
        self.seed = seed
        self.calls = []
        self.status, self.utility = 'running', None
        self.advance_reference()

    @property
    def completed(self):
        return self.status in ('terminal', 'cutoff')

    def advance_reference(self):
        while self.status == 'running':
            if self.bounded and self.slice is not None and self.node.state.turn_index >= self.tree.cutoff and self.node.pending is None:
                from .bounded import current_payoffs
                self.status = 'terminal' if self.node.state.is_terminal else 'cutoff'
                self.utility = list(current_payoffs(self.rules, self.node, self.world))
                return
            if self.node.state.is_terminal:
                self.status = 'terminal'
                self.utility = list(self.rules.terminal_payoffs(self.node, self.world))
                return
            actor = self.rules.actor(self.node)
            controlled = self.ego is None or actor == self.ego
            if self.slice is not None:
                controlled = controlled and self.controlled < self.slice['k']
            if controlled:
                return
            if self.rolling:
                probabilities = self.rolling.probabilities(self.history)
                ai = int(self.rng.choice(len(probabilities), p=probabilities[:, self.world_index]))
                self.rolling.observe_reference(probabilities, ai)
            elif self.fixed:
                ai = self.reference.action_index(self.node, self.world)
            else:
                entry = self.tree.entries[self.index]
                wi = self.tree.worlds.index(self.world)
                ai = int(self.rng.choice(len(entry.actions), p=self.tree.policy[self.index][:, wi]))
            self.step(ai)

    def step(self, ai):
        actions = self.rules.actions(self.node)
        self.node = self.rules.step(self.node, actions[ai], realized_world=self.world)
        self.history.append(ai)
        if self.tree:
            self.index = self.tree.entries[self.index].children[ai]
            if self.node.state.public_state() != self.tree.entries[self.index].node.state.public_state():
                raise AssertionError('Live branch diverged from native reference tree')

    def request(self, temperature):
        cutoff = self.tree.cutoff if self.bounded and self.slice else None
        remaining = max(0, self.slice['k'] - self.controlled) if cutoff is not None else None
        return request(self.rules, self.node, self.world, seed_for(self.seed, len(self.calls)), temperature,
                       cutoff=cutoff, remaining_decisions=remaining)

    def accept(self, output):
        if output['completion'].get('status') == 'infrastructure_failure':
            raise RuntimeError('Infrastructure failure is not a game reward')
        actor = self.rules.actor(self.node)
        ai, status = decode(output, self.rules.actions(self.node))
        self.calls.append(dict(output, player=actor, action_index=ai, valid=status == 'ok',
                               native_node_index=self.index if self.tree else None,
                               protocol_failure=None if status == 'ok' else status, decision=len(self.calls)))
        if self.fixed:
            self.calls[-1]['native_history'] = list(self.history)
        if status != 'ok':
            self.status = status
            return
        self.controlled += 1
        self.step(ai)
        self.advance_reference()

    def summary(self):
        return dict(parent_id=self.parent['id'], family=self.parent['family'], players=self.parent['players'],
                    slice_id=self.slice['id'] if self.slice else None, focal=self.ego,
                    rollout_seed=self.seed, world_index=self.world_index, world=[list(row) for row in self.world],
                    k=self.slice['k'] if self.slice else None,
                    status=self.status, completed=self.completed,
                    terminal_utility=self.utility if not (self.bounded and self.slice) else None,
                    objective_utility=self.utility,
                    utility_scope='cutoff' if self.bounded and self.slice else 'native-terminal',
                    absolute_cutoff=self.slice['absolute_cutoff'] if self.bounded and self.slice else None,
                    oracle_seconds=self.rolling.seconds if self.rolling else 0.,
                    oracle_solves=self.rolling.solves if self.rolling else 0, calls=len(self.calls),
                    controlled_decisions=self.controlled)


def execute(jobs, generate, temperature=1.0, concurrency=32):
    while any(j.status == 'running' for j in jobs):
        active = [j for j in jobs if j.status == 'running']
        for offset in range(0, len(active), concurrency):
            batch = active[offset:offset + concurrency]
            outputs = generate([j.request(temperature) for j in batch])
            if len(outputs) != len(batch):
                raise RuntimeError('Missing native generation outputs')
            for job, output in zip(batch, outputs):
                job.accept(output)


def normalized(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite reward')
    return ((values - values.mean()) / (values.std() + 1e-6)).tolist()


class Collector:
    def __init__(self, dataset, generate, arm, seed=42, replicas=4, concurrency=32):
        if arm not in ('slices', 'selfplay') or replicas < 2:
            raise ValueError('Choose slices/selfplay and >=2 replicas')
        self.dataset, self.generate, self.arm = dataset, generate, arm
        self.seed, self.replicas, self.concurrency = seed, replicas, concurrency
        self.data = {}; self.state = dict(version=VERSION, dataset_sha256=dataset.sha, arm=arm,
                                         seed=seed, replicas=replicas, cursor=0, consumed=0, exposure={})
        self.pool = defaultdict(list)
        for s in dataset.slices['train']:
            self.pool[s['parent_id']].append(s)

    def restore(self, state):
        for key in ('version', 'dataset_sha256', 'arm', 'seed', 'replicas'):
            if state[key] != self.state[key]:
                raise ValueError('Collector resume contract changed: ' + key)
        self.state = deepcopy(state)

    def collect(self, step, arm, token_target=65536, validation=False):
        if arm != self.arm or validation or token_target < 1:
            raise ValueError('Invalid collection request')
        working = deepcopy(self.state)
        rows, units, games, tokens, active_groups = [], [], [], 0, 0
        parents = self.dataset.parents['train']
        while tokens < token_target:
            cursor = working['cursor']; cycle, offset = divmod(cursor, len(parents))
            order = np.random.default_rng(seed_for(self.seed, 'parents', cycle)).permutation(len(parents))
            parent = parents[int(order[offset])]
            rng = np.random.default_rng(seed_for(self.seed, self.arm, cursor))
            selected = self.pool[parent['id']][int(rng.integers(len(self.pool[parent['id']])))] if arm == 'slices' else None
            weights = selected['entry_world_weights'] if selected else parent['world_weights']
            world_index = int(rng.choice(len(weights), p=weights))
            jobs = [Rollout(self.dataset, parent, seed_for(self.seed, arm, cursor, r), world_index, selected)
                    for r in range(self.replicas)]
            execute(jobs, self.generate, concurrency=self.concurrency)
            complete = all(j.completed for j in jobs)
            players = [selected['ego']] if selected else list(range(parent['players']))
            for player in players:
                group = f'{arm}:{cursor}:p{player}'
                advantages = normalized([j.utility[player] for j in jobs]) if complete else [0.] * len(jobs)
                active_groups += int(any(abs(a) > 1e-12 for a in advantages))
                for r, (job, advantage) in enumerate(zip(jobs, advantages)):
                    calls = [c for c in job.calls if c['player'] == player]
                    if not calls:
                        continue
                    unit = f'{group}:r{r}'
                    units.append(dict(unit=unit, group=group, parent_id=parent['id'], player=player,
                                      utility=job.utility[player] if job.utility else None, group_complete=complete))
                    for call in calls:
                        ids, logps = call.get('response_ids'), call.get('behavior_log_probs')
                        if not ids or logps is None or len(ids) != len(logps) or not all(math.isfinite(p) for p in logps):
                            raise ValueError('Missing native tokens or behavior probabilities')
                        rows.append(dict(call, kind=arm, task_id=selected['id'] if selected else parent['id'],
                                         parent_id=parent['id'], group=group, unit=unit, replica=r,
                                         task_advantage=advantage, protocol_advantage=-.2 if not call['valid'] else 0.,
                                         trajectory_length=len(calls), task_denominator=0.,
                                         advantage=advantage + (-.2 if not call['valid'] else 0.)))
            batch_tokens = sum(len(c['response_ids']) for job in jobs for c in job.calls)
            if batch_tokens <= 0:
                raise RuntimeError('A training group produced no model responses')
            tokens += batch_tokens
            games.extend(dict(j.summary(), group_cursor=cursor, replica=r) for r, j in enumerate(jobs))
            exposure = working['exposure'].setdefault(parent['id'], dict(groups=0, tokens=0, trajectories=0,
                completed_trajectories=0, decision_calls=0, valid_calls=0, truncated_calls=0, invalid_calls=0))
            exposure['groups'] += 1; exposure['tokens'] += batch_tokens; exposure['trajectories'] += len(jobs)
            exposure['completed_trajectories'] += sum(j.completed for j in jobs)
            exposure['decision_calls'] += sum(len(j.calls) for j in jobs)
            exposure['valid_calls'] += sum(c['valid'] for j in jobs for c in j.calls)
            exposure['truncated_calls'] += sum(c['protocol_failure'] == 'truncated' for j in jobs for c in j.calls)
            exposure['invalid_calls'] += sum(c['protocol_failure'] == 'invalid_action' for j in jobs for c in j.calls)
            working['cursor'] += 1
        # Average over player trajectories, then decisions; all three losses share weighting.
        nrows, nunits = len(rows), len(units)
        for row in rows:
            weight = nrows / (nunits * row['trajectory_length'])
            row.update(loss_weight=weight, task_weight=weight, protocol_weight=weight, kl_weight=weight)
        working['consumed'] += tokens
        self.state = working
        return rows, units, games, dict(generated_tokens=tokens, rows=nrows, active_groups=active_groups,
            completion_rate=sum(g['completed'] for g in games) / len(games),
            invalid_calls=sum(not r['valid'] for r in rows), truncations=sum(r['protocol_failure'] == 'truncated' for r in rows),
            parent_ids_this_update=len({g['parent_id'] for g in games}),
            parent_ids_cumulative=len(working['exposure']), sampling_cursor=working['cursor'], skip_optimizer=False)
