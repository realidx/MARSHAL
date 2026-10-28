"""Versioned B/P training signals and curriculum; no GPU dependencies."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import random

from training.b_sft import social_named_probe as named

VERSION = 'social-bp-pilot-v1'
CONTRACT = dict(version=VERSION, correct=1, incorrect=0, truncated=0, format_failure=0,
                infrastructure_failure=None, retry=0, length_penalty=0,
                group='Eight independent first attempts at the same prompt; never mix B/P or retries.')
B_SKILLS = ('formation', 'maintain', 'update')
P_SKILLS = ('complete', 'uncertain', 'result_use', 'information')


def reward(task, completion):
    if task['task'] not in ('B', 'P'):
        raise ValueError('Unknown task kind')
    if task['task'] == 'P' and not task['teacher']['acceptable_actions']:
        raise ValueError('No supported P target; exclude this task before rollout')
    if completion.get('status') == 'infrastructure_failure':
        return dict(status='infrastructure_failure', reward=None, correct=None)
    scored = named.score(task, completion, 'action_tools', task.get('name_variant', 0))
    if scored['correct'] is None:
        raise ValueError('Unscorable teacher cannot enter optimizer data')
    return dict(scored, reward=int(bool(scored['correct'])), reward_version=VERSION)


def target_answer(task):
    return named.gold_answer(task, task.get('name_variant', 0))


def native_completion(task):
    answer = target_answer(task)
    name, args = ('SUBMIT_BELIEFS', answer) if task['task'] == 'B' else named.action_call(answer)
    return dict(raw_message=dict(content='', tool_calls=[dict(function=dict(name=name, arguments=json.dumps(args)))]), finish_reason='stop')


def level_weights(step, kind, state=None):
    desired = 0 if step < 20 else 1 if step < 60 else 2
    allowed = (state or {}).get('allowed', {}).get(kind, 0)
    phase = min(desired, allowed)
    return ((.70, .25, .05), (.40, .50, .10), (.20, .50, .30))[phase]


def select_batch(rows, step, max_steps, batch_size, seed, state=None):
    if any(r.get('training_pack_version') for r in rows):
        from training.b_sft.bp_two_gpu_data import select_batch as select_two_gpu
        return select_two_gpu(rows, step, max_steps, batch_size, seed)
    if batch_size != 16 or not 0 <= step < max_steps:
        raise ValueError('Pilot requires 16 prompts per rollout and a valid step')
    rng = random.Random(f'{VERSION}:{seed}:{step}')
    selected = []; used = set(); family_uses = Counter(); direct = 0; kind_uses = Counter()
    information_polarities = [True,False]; rng.shuffle(information_polarities)
    stage_plans = {}
    for kind in ('B', 'P'):
        weights = level_weights(step, kind, state)
        counts = [int(80*w) for w in weights]
        for i in sorted(range(3), key=lambda i: 80*weights[i]-counts[i], reverse=True)[:80-sum(counts)]: counts[i] += 1
        plan = [i for i, count in enumerate(counts) for _ in range(count)]
        random.Random(f'{seed}:{kind}:{step//10}:{weights}').shuffle(plan)
        stage_plans[kind] = plan
    cells = [('B', s) for s in ('formation',)*3+('maintain',)*2+('update',)*3]
    cells += [('P', s) for s in P_SKILLS for _ in range(2)]
    rng.shuffle(cells)
    for kind, skill in cells:
        stage = stage_plans[kind][(step%10)*8+kind_uses[kind]]; kind_uses[kind] += 1
        pool = [r for r in rows if r['task'] == kind and r['pool'] == skill and r['stage'] == stage
                and r['id'] not in used and not (direct >= 1 and r.get('direct_answer'))]
        if skill == 'information':
            polarity = information_polarities.pop()
            pool = [r for r in pool if bool(r.get('information_positive')) == polarity]
        if not pool:
            raise ValueError(f'Missing distinct curriculum examples: {kind}/{skill}/{stage}; do not fill with easy duplicates')
        # Prefer an available within-game contrast; otherwise balance game
        # families before label profiles, never by observed learner success.
        pairs = [r for r in pool if any(r['contrast_group'] == x['contrast_group']
                                      and r['answer_signature'] != x['answer_signature'] for x in selected)]
        if pairs: pool = pairs
        families = defaultdict(list)
        for r in pool: families[r['family']].append(r)
        least = min(family_uses[f] for f in families)
        family = rng.choice(sorted(f for f in families if family_uses[f] == least))
        labels = defaultdict(list)
        for r in families[family]: labels[r['answer_signature']].append(r)
        chosen = rng.choice(labels[rng.choice(sorted(labels))])
        selected.append(chosen); used.add(chosen['id']); family_uses[family] += 1
        direct += bool(chosen.get('direct_answer'))
    return selected


def update_curriculum(state, step, measurements):
    """Aggregate held-out results only; no test feedback or training gold leak."""
    state = json.loads(json.dumps(state or dict(allowed={'B': 0, 'P': 0}, history=[])))
    history = [x for x in state['history'] if x['step'] != step]
    history.append(dict(step=step, measurements=measurements)); history.sort(key=lambda x: x['step'])
    state['history'] = history
    for kind in ('B', 'P'):
        level = state['allowed'][kind]
        recent = [h['measurements'] for h in history if h['step'] > 0][-2:]
        checks = [m.get(f'{kind}/{level}', {}) for m in recent]
        if level < 2 and len(checks) == 2 and all(x.get('count', 0) >= 8 and x.get('accuracy', 0) >= .60 for x in checks):
            controls = ('B/shrink_required','B/fullset_required','B/maintain','B/favored_only_update') if kind=='B' else (
                'P/information_positive','P/information_negative','P/result_use','P/uncertain')
            stable = all(recent[1][key]['accuracy']+.10 >= recent[0][key]['accuracy']
                         for key in controls if key in recent[0] and key in recent[1])
            if stable and checks[-1].get('contrast_accuracy', 0) + .05 >= checks[0].get('contrast_accuracy', 0):
                state['allowed'][kind] = level+1
    return state


def summarize(records):
    cells = defaultdict(list); pairs = defaultdict(list); groups = defaultdict(list)
    for r in records:
        t = r['task']; s = r['score']
        cells[t['task']].append(r); cells[f"{t['task']}/{t['pool']}"].append(r)
        if t['task'] == 'B' and 'gold' in t.get('teacher', {}):
            gold = t['teacher']['gold']; previous = t['input'].get('previous_belief')
            cells['B/shrink_required' if len(gold['possible_preferences'])<3 else 'B/fullset_required'].append(r)
            if len(gold['possible_preferences'])>1 and gold['favored']!='undetermined': cells['B/nonredundant_favored'].append(r)
            if previous and previous['possible_preferences']==gold['possible_preferences'] and previous['favored']!=gold['favored']:
                cells['B/favored_only_update'].append(r)
        if t['task'] == 'P':
            if t['pool'] == 'information':
                cells['P/information_positive' if t.get('information_positive') else 'P/information_negative'].append(r)
                if t.get('information_negative_kind') == 'future_opportunity_remains': cells['P/future_information_negative'].append(r)
            if t.get('qualitative_level'): cells['P/qualitative'].append(r)
        # Do not allow direct factual B accuracy to trigger behavior progression.
        if not t.get('direct_answer'): cells[f"{t['task']}/{t['stage']}"].append(r)
        pairs[(t['task'], t['stage'], t['contrast_group'])].append(r)
        groups[t['id']].append(r)
    result = {}
    for key, rs in cells.items():
        result[key] = dict(count=len(rs), accuracy=sum(x['score']['correct'] for x in rs)/len(rs),
            truncated=sum(x['score']['status'] == 'truncated' for x in rs)/len(rs),
            wrong_full_set=sum(x['score'].get('predicted_full_set', False) and not x['score']['correct'] for x in rs)/len(rs))
        result[key]['over_exclusion'] = sum(x['score'].get('false_exclusions',0)>0 for x in rs)/len(rs)
        result[key]['format_failure'] = sum(x['score']['status']=='format_failure' for x in rs)/len(rs)
        result[key]['investigation_rate'] = sum(x['score'].get('investigated',False) for x in rs)/len(rs)
    for kind in ('B', 'P'):
        for level in range(3):
            values = []
            for (k, s, group), rs in pairs.items():
                if (k, s) != (kind, level): continue
                by_id = defaultdict(list)
                for x in rs: by_id[x['task']['id']].append(x)
                if len({x['task']['answer_signature'] for x in rs}) < 2: continue
                # Chance that all different checkpoints succeed in independent
                # first attempts; report a matched-control metric, not pass@k.
                value = 1.
                for xs in by_id.values(): value *= sum(x['score']['correct'] for x in xs)/len(xs)
                values.append(value)
            if f'{kind}/{level}' in result:
                result[f'{kind}/{level}']['contrast_accuracy'] = sum(values)/len(values) if values else 0.
    diagnostic = Counter()
    for rs in groups.values():
        successes = sum(x['score']['correct'] for x in rs)
        diagnostic['all_correct' if successes == len(rs) else 'all_wrong' if successes == 0 else 'mixed'] += 1
    result['groups'] = dict(diagnostic)
    return result


def save_feedback(output_dir, step, records):
    path = Path(output_dir)/'bp_curriculum_state.json'
    state = json.loads(path.read_text()) if path.exists() else None
    measurements = summarize(records)
    state = update_curriculum(state, step, measurements)
    temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(state, indent=2)+'\n'); temporary.replace(path)
    with (Path(output_dir)/'bp_validation.jsonl').open('a') as log:
        log.write(json.dumps(dict(step=step, measurements=measurements, allowed=state['allowed']))+'\n')
    from training.b_sft.bp_checkpoints import retain
    retain(output_dir, step, measurements)
    return measurements


def batch_records(batch):
    records = []
    for i, value in enumerate(batch.non_tensor_batch['ground_truth']):
        task = json.loads(value) if isinstance(value,str) else value
        records.append(dict(task=task, score=dict(correct=bool(batch.batch['scores'][i].item()==1),
            status='truncated' if batch.batch['bp_truncated'][i].item() else 'format_failure' if batch.batch['bp_format'][i].item() else 'ok',
            false_exclusions=batch.batch['bp_exclusions'][i].item(), investigated=bool(batch.batch['bp_investigated'][i].item()),
            predicted_full_set=bool(batch.batch['bp_fullset'][i].item()))))
    return records
