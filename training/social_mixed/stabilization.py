"""Versioned training recipe; statistics contain training data only."""
from collections import Counter, defaultdict
from copy import deepcopy
import math
import random
from training.social_mixed.core import Collector, seed_for

VERSION = 'social-stable-v2-b-bridges'


def learning_rate(consumed, budget):
    if budget <= 0:
        raise ValueError('Positive token budget required')
    progress = min(1., max(0., consumed / budget))
    return 1e-7 + .5 * 9e-7 * (1 + math.cos(math.pi * progress))


def bucket(reset):
    game = reset['raw']['game']
    mode = 'binary' if all(g['binary'] for g in game['goals']) else 'linear'
    # Exchangeable seat bucket: never key by arbitrary player numbering.
    return f"{game['n_players']}:{mode}:{len(game['round_robin'])}"


class StableCollector(Collector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = dict(version=VERSION, questions={}, baselines={})

    def restore(self, state):
        if state.get('version') != VERSION:
            raise ValueError('Recipe mismatch: start a new stage rather than silently resume')
        self.state = deepcopy(state)

    def collect(self, step, arm, token_target=65536, validation=False):
        if validation:
            return super().collect(step, arm, token_target, validation)
        if arm == 'bp':
            return self.collect_bp(step)
        if arm != 'selfplay':
            raise ValueError('Stable recipe supports bp and selfplay only')
        rows, units, games, metrics = super().collect(step, arm, token_target)
        resets = {r['id']: r for r in self.data['selfplay_train']}
        unit_rows = defaultdict(list)
        for r in rows:
            unit_rows[r['unit']].append(r)
        baseline = self.state['baselines']
        observations = defaultdict(list)
        n = len(rows)
        completed = sum(u['utility'] is not None and u['unit'] in unit_rows for u in units)
        all_units = len(unit_rows)
        for u in units:
            rs = unit_rows[u['unit']]
            if not rs:
                continue
            key = bucket(resets[rs[0]['reset_id']])
            old = baseline.get(key, {})
            fallback = baseline.get('global', {}).get('mean', 0.)
            b = old['mean'] if old.get('count', 0) >= 16 else fallback
            complete = u['utility'] is not None
            advantage = u['utility'] - b if complete else 0.
            for r in rs:
                r['task_advantage'] = advantage if not r['protocol_failure'] else 0.
                r['task_weight'] = n / all_units / len(rs)
                r['protocol_weight'] = r['loss_weight']
                r['kl_weight'] = r['loss_weight']
                r['task_denominator'] = 0.  # Existing per-call length mean for SP.
                r['baseline'] = b
                r['advantage_version'] = VERSION
                r['advantage'] = r['task_advantage']+r['protocol_advantage']
            if complete:
                observations[key].append(u['utility'])
                observations['global'].append(u['utility'])
        # Once per player episode; batch mean EMA makes seat/order permutations invariant.
        for key, values in observations.items():
            old = baseline.get(key)
            mean = sum(values) / len(values)
            baseline[key] = dict(mean=mean if old is None else .9*old['mean']+.1*mean,
                                 count=len(values)+(old or {}).get('count', 0))
        metrics={('legacy_group/'+k if 'mixed_groups' in k or 'task_abs_weighted_mass' in k or 'nonzero_task_calls' in k else k):v for k,v in metrics.items()}
        metrics.update(completed_player_episodes=completed,
                       censored_player_episodes=len(units)-completed)
        metrics['historical_baseline/nonzero_completed_episodes'] = sum(
            any(abs(r['task_advantage']) > 1e-9 for r in rs) for rs in unit_rows.values())
        return rows, units, games, metrics

    def collect_bp(self, step):
        from training.social_mixed.b_bridge_requests import request
        from training.b_sft.social_bp_training import reward
        rng = random.Random(seed_for(self.seed, step, VERSION))
        candidates = self.data['bp_train']
        if {t['task'] for t in candidates} != {'B', 'P'}:
            raise ValueError('Both B and P training domains required')
        if len({t['id'] for t in candidates}) != len(candidates):
            raise ValueError('Duplicate training question IDs')
        old_stats = deepcopy(self.state['questions'])
        rows, units = [], []
        used = set()
        effective, attempts = Counter(), Counter()
        semantic = Counter()
        tokens = 0
        for index in range(32):
            domains = [d for d in ('B', 'P') if effective[d] < 4 and
                       any(t['task'] == d and t['id'] not in used for t in candidates)]
            if not domains:
                break
            domain = min(domains, key=lambda d: (attempts[d], d))
            pool = [t for t in candidates if t['task'] == domain and t['id'] not in used]
            # Rotate direct inference aids, procedure-only, and unassisted B.
            # Never let successful scaffold groups permanently replace hard raw B.
            if domain == 'B' and any(t.get('b_bridge') for t in candidates):
                stage=('likelihood','procedure','raw')[(step+attempts[domain])%3]
                staged=[t for t in pool if t.get('b_bridge',{}).get('stage','raw')==stage]
                if staged:pool=staged
            source = 'coverage' if attempts[domain] % 2 == 0 else 'active'
            if source == 'active':
                active = [t for t in pool if old_stats.get(t['id'], {}).get('mixed', 0.) >= .05
                          and step-old_stats[t['id']].get('step',-1000) <= 32]
                if active:
                    pool = active
                else:
                    source = 'coverage_fallback'
            cells = defaultdict(list)
            for t in pool:
                cells[(t['kernel'], t['completion_mode'], t.get('information_role', 'na'))].append(t)
            task = rng.choice(cells[rng.choice(sorted(cells))])
            used.add(task['id']); attempts[domain] += 1
            group = f'train:step{step}:bp:{task["id"]}'
            requests = []
            for replica in range(8):
                req = request(task, 'action_tools', task.get('name_variant', 0))
                req['seed'] = seed_for(self.seed, task['id'], replica, step)
                requests.append(req)
            outputs = []
            for start in range(0, 8, self.concurrency):
                outputs.extend(self.generate(requests[start:start+self.concurrency]))
            if len(outputs) != 8:
                raise ValueError('Missing rollout outputs')
            scores = [reward(task, o['completion']) for o in outputs]
            values = [s['reward'] for s in scores]
            if any(v is None or not math.isfinite(v) for v in values):
                raise ValueError('Unscorable rollout cannot enter optimizer')
            mixed = max(values) > min(values)
            effective[domain] += int(mixed)
            valid_values = [s['reward'] for s,o in zip(scores,outputs)
                            if s['status'] != 'format_failure' and o['completion']['finish_reason'] != 'length']
            semantic[domain] += int(bool(valid_values) and max(valid_values)>min(valid_values))
            mean = sum(values)/8
            previous = old_stats.get(task['id'], {}).get('mixed', float(mixed))
            self.state['questions'][task['id']] = dict(mixed=.8*previous+.2*float(mixed),step=step)
            for replica, (output, score) in enumerate(zip(outputs, scores)):
                truncated = output['completion']['finish_reason'] == 'length'
                invalid = truncated or score['status'] == 'format_failure'
                unit = f'{group}:r{replica}'
                rows.append(dict(output, kind=domain, skill=task['pool'], group=group, unit=unit,
                                 replica=replica, task_id=task['id'], kernel=task['kernel'], score=score,
                                 sampling_source=source, b_bridge_stage=task.get('b_bridge',{}).get('stage','raw'), task_advantage=0. if invalid else score['reward']-mean,
                                 protocol_advantage=-self.protocol_coefficient if invalid else 0.,
                                 protocol_failure='truncated' if truncated else 'invalid_action' if invalid else None,
                                 selected_task_group=mixed, task_denominator=1024., advantage_version=VERSION))
                units.append(dict(group=group, unit=unit, replica=replica, kind=domain, utility=score['reward']))
                tokens += len(output['response_ids'])
        n = len(rows)
        for r in rows:
            d = r['kind']
            r['task_weight'] = n*.5/(effective[d]*8) if r['selected_task_group'] else 0.
            r['protocol_weight'] = n*.5/(attempts[d]*8)
            r['kl_weight'] = r['protocol_weight']
            r['loss_weight'] = r['protocol_weight']
            r['advantage'] = r['task_advantage']+r['protocol_advantage']
        metrics = dict(generated_tokens=tokens, rows=n, games=0,
                       candidate_groups=sum(attempts.values()), skip_optimizer=not any(effective.values()))
        for d in ('B', 'P'):
            metrics.update({f'{d}/effective_groups':effective[d], f'{d}/candidate_groups':attempts[d],
                            f'{d}/semantic_contrast_groups':semantic[d], f'{d}/underfilled':int(effective[d]<4)})
        for stage in ('likelihood','procedure','raw'):
            selected=[r for r in rows if r['kind']=='B' and r['b_bridge_stage']==stage]
            if selected:
                prefix='B/stage/'+stage
                metrics[prefix+'/samples']=len(selected)
                metrics[prefix+'/correct']=sum(r['score']['reward'] for r in selected)
                metrics[prefix+'/effective_groups']=len({r['group'] for r in selected if r['selected_task_group']})
        return rows, units, [], metrics
