"""Single-query B curriculum, teacher-verified contrasts and shortcut diagnostics.

Selection uses teacher labels and structural features, never learner responses.
The sampler is pure Python so its actual training decisions can be checked on CPU.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

VERSION = 'social-b-behavior-curriculum-v1'
BUCKETS = ('behavior_short', 'behavior_long', 'control')
CATEGORIES = ('formation', 'maintain', 'update', 'uninformative', 'strength_change', 'known_control')


def single_queries(task):
    """Project the requested outputs only; retain all public and private inputs."""
    queries = task['input']['queries']
    gold = {(j['player'], j['goal']): j for j in task['gold']['judgments']}
    if len(gold) != len(queries) or len({(q['player'], q['goal']) for q in queries}) != len(queries):
        raise ValueError('Query/gold mismatch')
    for q in queries:
        item = deepcopy(task)
        if len(queries) > 1:
            item['parent_checkpoint'] = task['id']
            item['id'] = f"{task['id']}-p{q['player']}-g{q['goal']}"
        item['input']['queries'] = [deepcopy(q)]
        item['gold'] = dict(judgments=[deepcopy(gold[q['player'], q['goal']])])
        if 'category_queries' in item:
            item['category_queries'] = [p for p in item['category_queries'] if p['query'] == q]
        if len(queries) > 1 and item.get('curriculum'):
            item['curriculum'] = describe(item)
        yield item


def describe(task):
    from training.b_sft.social_b_dataset import judgment
    inp = task['input']; q = inp['queries'][0]; gold = task['gold']['judgments'][0]
    names = {1: 'want', 0: 'neutral', -1: 'avoid'}
    catalogue = inp['public_type_catalogues'][str(q['player'])]
    if q['player'] == inp['player']:
        prior = dict(possible_preferences=[names[inp['own_preferences'][q['goal']]]],
                     favored=names[inp['own_preferences'][q['goal']]])
    else:
        counts = Counter(row[q['goal']] for row in catalogue)
        leaders = [v for v, n in counts.items() if n == max(counts.values())]
        prior = dict(possible_preferences=[names[v] for v in counts],
                     favored=names[leaders[0]] if len(leaders) == 1 else 'undetermined')
    events = len(inp['history']) - len(inp['public_setup']['intervention_prefix'])
    hidden = sum(len({row[g] for row in rows}) > 1
                 for p, rows in inp['public_type_catalogues'].items() if int(p) != inp['player']
                 for g in range(len(rows[0])))
    behavior = judgment(prior) != judgment(gold)
    bucket = ('behavior_short' if events <= 2 and hidden == 1 else 'behavior_long') if behavior else 'control'
    return dict(bucket=bucket, autonomous_events=events, observer_unknown_slots=hidden,
                requires_behavior=behavior, gold_size=len(gold['possible_preferences']),
                gold_favored=gold['favored'], prior=judgment(prior),
                difficulty='Structural proxy only; not measured learner success probability.')


def choose_balanced(items, rng):
    """Uniform families, then label profiles, then checkpoints within that cell."""
    families = defaultdict(list)
    for item in items: families[item['family']].append(item)
    group = families[rng.choice(sorted(families))]
    labels = defaultdict(list)
    for item in group:
        m = item['curriculum']; labels[m['gold_size'], m['gold_favored']].append(item)
    return rng.choice(labels[rng.choice(sorted(labels))])


def select_batch(rows, step, max_steps, batch_size, seed):
    """Reserve 1/4 for controls; fade short behavioral tasks from 75% to 25% of core.

    No reward filtering or retries. Selection is reproducible from optimizer step,
    independent of asynchronous completion order and scheduler epoch state.
    """
    if batch_size < 4 or max_steps < 1 or not 0 <= step < max_steps:
        raise ValueError('B curriculum requires batch_size >= 4 and a valid optimizer step')
    pools = {b: [r for r in rows if r['curriculum']['bucket'] == b] for b in BUCKETS}
    if any(not pool for pool in pools.values()):
        raise ValueError('B curriculum requires short behavior, longer behavior, and control coverage')
    rng = random.Random(f'{seed}:{step}:{VERSION}')
    controls = max(1, batch_size // 4)
    core = batch_size - controls
    fraction = .75 - .5 * step / max(1, max_steps - 1)
    # Stochastic rounding retains the intended schedule with small rollout batches.
    expected = core * fraction
    short = int(expected) + (rng.random() < expected % 1)
    buckets = ['behavior_short'] * short + ['behavior_long'] * (core-short) + ['control'] * controls
    selected = []; seen = set()
    for bucket in buckets:
        pool = [r for r in pools[bucket] if r['id'] not in seen]
        if not pool: raise ValueError(f'Insufficient distinct checkpoints in {bucket}')
        chosen = choose_balanced(pool, rng)
        selected.append(chosen); seen.add(chosen['id'])
    rng.shuffle(selected)
    return selected


def shortcut_report(tasks):
    by_bucket = defaultdict(list)
    for t in tasks: by_bucket[t['curriculum']['bucket']].append(t)
    def report(rows):
        n = len(rows)
        answers = Counter((tuple(sorted(t['gold']['judgments'][0]['possible_preferences'])),
                           t['gold']['judgments'][0]['favored']) for t in rows)
        majority = answers.most_common(1)
        return dict(count=n,
            full_set_exact=sum(set(t['gold']['judgments'][0]['possible_preferences']) == {'want','neutral','avoid'}
                               and t['gold']['judgments'][0]['favored'] == 'undetermined' for t in rows) / n if n else None,
            catalogue_prior_exact=sum(not t['curriculum']['requires_behavior'] for t in rows) / n if n else None,
            best_constant_exact=majority[0][1]/n if n else None,
            best_constant_answer=dict(possible_preferences=list(majority[0][0][0]),favored=majority[0][0][1]) if n else None,
            labels=dict(Counter(f"{t['curriculum']['gold_size']}:{t['curriculum']['gold_favored']}" for t in rows)))
    return dict(all=report(tasks), buckets={b: report(by_bucket[b]) for b in BUCKETS})


def diagnostics(task, score):
    """Per-response counts; invalid outputs stay in accuracy denominators."""
    gold = task['gold']['judgments']
    predictions = {(j['player'], j['goal']): j for j in score['judgments']}
    counts = Counter(queries=len(gold), valid=int(score['status'] == 'ok'), responses=1)
    for g in gold:
        j = predictions.get((g['player'], g['goal']))
        possible = set(j['prediction']['possible_preferences']) if j else set()
        exact = bool(j and j['set_exact'] and j['favored_exact'])
        counts['exact'] += exact
        counts['set_exact'] += bool(j and j['set_exact'])
        counts['favored_exact'] += bool(j and j['favored_exact'])
        counts['predicted_full'] += len(possible) == 3
        needs_exclusion = len(g['possible_preferences']) < 3
        counts['needs_exclusion'] += needs_exclusion
        counts['wrong_full'] += needs_exclusion and len(possible) == 3
        counts['gold_full'] += not needs_exclusion
        counts['false_exclusion'] += not needs_exclusion and bool(j) and len(possible) < 3
        favored_multi = len(g['possible_preferences']) > 1 and g['favored'] != 'undetermined'
        counts['favored_multi'] += favored_multi
        counts['favored_multi_exact'] += favored_multi and exact
    bucket = (task.get('curriculum') or {}).get('bucket')
    for b in BUCKETS:
        counts[b] = int(bucket == b)
        counts[b+'_exact'] = int(bucket == b and counts['exact'] == len(gold))
    categories = {p['category'] for p in task.get('category_queries', [])}
    for category in CATEGORIES:
        name = 'target_'+category
        counts[name] = int(category in categories)
        counts[name+'_exact'] = int(category in categories and counts['exact'] == len(gold))
    return dict(counts)


def diagnostic_metrics(tensors):
    """Aggregate actual response counts rather than averaging worker rates."""
    totals = {k[2:]: float(v.sum().item()) for k, v in tensors.items() if k.startswith('b_')}
    if not totals: return {}
    ratios = dict(exact=('exact','queries'), set_exact=('set_exact','queries'),
                  favored_exact=('favored_exact','queries'), valid=('valid','responses'),
                  predicted_full=('predicted_full','queries'), wrong_full_when_exclusion_needed=('wrong_full','needs_exclusion'),
                  false_exclusion_on_full=('false_exclusion','gold_full'),
                  favored_multi_exact=('favored_multi_exact','favored_multi'))
    ratios.update({b+'_exact': (b+'_exact', b) for b in BUCKETS})
    ratios.update({'target_'+c+'_exact': ('target_'+c+'_exact', 'target_'+c) for c in CATEGORIES})
    result = {f'val_b/count/{k}': v for k, v in totals.items()}
    for name, (num, den) in ratios.items():
        if totals.get(den, 0): result['val_b/'+name] = totals.get(num, 0) / totals[den]
    return result


def build(folder, out, per_family=3):
    from training.b_sft.social_b_dataset import digest, judgment, observer_belief
    from training.b_sft.social_b_oracle import BeliefOracle, VERSION as ORACLE_VERSION
    from training.b_sft.social_b_curriculum import family, split_families
    from training.b_sft.social_b_evaluation import request
    from training.b_sft.social_b_rl import reward
    from training.b_sft.debug.audit_social_b_weighted import exact_posterior
    from training.b_sft.shared_teacher import SearchLimit

    if out.exists(): raise ValueError('Use a new output directory')
    if per_family < 1: raise ValueError('per_family must be positive')
    def read(name): return list(map(json.loads, (folder/name).read_text().splitlines()))
    summary = json.loads((folder/'summary.json').read_text())
    if summary['version'] != ORACLE_VERSION: raise ValueError('New weighted labels required')
    for path, checksum in summary['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Stale mined data: {path}')
    sources = {s['id']: dict(s, family=family(s['raw'])) for s in read('sources.jsonl')}
    labels = {r['id']: r['answer'] for r in read('all_candidate_labels.jsonl')}
    pairs = read('all_candidate_pairs.jsonl')
    splits = split_families(sources, {p['source'] for p in pairs if p['category'] == 'update'})
    categories = defaultdict(set)
    for p in pairs:
        # Only screened updates have the additional history-dependence check.
        if p['category'] != 'update': categories[p['after']].add(p['category'])
    for p in read('screened_pairs.jsonl'): categories[p['after']].add(p['category'])
    tasks = {}
    for row in read('all_candidate_inputs.jsonl'):
        sid = row['source']; q = row['input']['queries'][0]
        t = dict(row, family=sources[sid]['family'], split=splits[sources[sid]['family']],
                 gold=dict(judgments=[dict(**q, **judgment(labels[row['id']]))]),
                 category_queries=[dict(category=c, query=q) for c in sorted(categories[row['id']])])
        t['curriculum'] = describe(t); tasks[t['id']] = t
    # This is a new, inspected development partition. Stratify rare short
    # behavioral families before the generic hash split; never split a topology.
    short_families = sorted({t['family'] for t in tasks.values()
                             if t['curriculum']['bucket'] == 'behavior_short'}, key=lambda f: digest(('short-split', f)))
    if len(short_families) < 3: raise ValueError('Need short behavioral examples in at least three independent topologies')
    for i, fam in enumerate(short_families):
        splits[fam] = ('train','validation','test','train','train')[i % 5]
    for t in tasks.values(): t['split'] = splits[t['family']]
    # Cap each topology/stratum, avoiding the thousands of redundant controls.
    pools = defaultdict(list)
    for t in tasks.values(): pools[t['family'], t['curriculum']['bucket']].append(t)
    selected = {}
    for key, pool in sorted(pools.items()):
        rng = random.Random(digest(key))
        for _ in range(min(per_family, len(pool))):
            t = choose_balanced(pool, rng); selected[t['id']] = t; pool.remove(t)
    # Keep the scarce, already checked history-dependent updates in the pool.
    for p in read('screened_pairs.jsonl'):
        if p['category'] == 'update': selected[p['after']] = tasks[p['after']]
    # Exact same pre-action history/query, different real autonomous actions.
    # The changed gold must be a genuine difference, not merely a category name.
    siblings = defaultdict(list)
    for p in pairs: siblings[p['source'], p['before']].append(p)
    contrasts = []; seen_families = set()
    for key, group in sorted(siblings.items()):
        fam = sources[key[0]]['family']
        if fam in seen_families: continue
        controls = [p for p in group if tasks[p['after']]['curriculum']['bucket'] == 'control']
        core = [p for p in group if tasks[p['after']]['curriculum']['requires_behavior']]
        if not controls or not core: continue
        a, b = controls[0]['after'], core[0]['after']
        selected[a] = tasks[a]; selected[b] = tasks[b]; seen_families.add(fam)
        contrasts.append(dict(source=key[0], before=key[1], control=a, behavior=b,
                              family=fam, split=splits[fam]))
    # Replay every selected checkpoint, including additions outside old screened data.
    out.mkdir(parents=True)
    audited = []; failures = []
    for i, t in enumerate(sorted(selected.values(), key=lambda t: t['id'])):
        s = sources[t['source']]; inp = t['input']; q = inp['queries'][0]
        events = [dict(action=a, kind='setup' if k < len(s['prefix']) else 'partner')
                  for k, a in enumerate(inp['history'])]
        try:
            o = BeliefOracle.replay(s['raw'], events, max_nodes=3000, seconds=2)
            reverse = BeliefOracle.replay(s['raw'], events, max_nodes=3000, seconds=2, reverse_actions=True)
            exact_posterior(o)
            expected = judgment(t['gold']['judgments'][0])
            if judgment(observer_belief(o, q['player'], q['goal'])) != expected:
                raise ValueError('Cached gold differs from replay')
            if judgment(observer_belief(reverse, q['player'], q['goal'])) != expected:
                raise ValueError('Action enumeration changed gold')
            if o.node.state.public_state() != inp['public_state']:
                raise ValueError('Public state mismatch')
            completion = dict(raw_message=dict(tool_calls=[dict(function=dict(name='SUBMIT_BELIEFS', arguments=json.dumps(t['gold'])))]))
            if reward(t, completion)['reward'] != 1: raise ValueError('Gold reward roundtrip failed')
            req = request(t)
            if any(k in json.loads(req['messages'][-1]['content']) for k in ('gold','curriculum','category_queries')):
                raise ValueError('Teacher metadata leaked into prompt')
            audited.append(t)
        except (ValueError, AssertionError, SearchLimit) as exc:
            failures.append(dict(id=t['id'], error=str(exc)))
        if (i+1) % 20 == 0: print(json.dumps(dict(audited=i+1, total=len(selected), failures=len(failures))), flush=True)
    passed = {t['id'] for t in audited}
    contrasts = [c for c in contrasts if c['control'] in passed and c['behavior'] in passed]
    def write(name, rows): (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    write('tasks.jsonl', audited)
    write('pairs.jsonl', [dict(p, query=tasks[p['after']]['input']['queries'][0]) for p in read('screened_pairs.jsonl')
                         if p['after'] in passed and p['before'] in passed])
    write('contrasts.jsonl', contrasts); write('audit_failures.jsonl', failures)
    reports = {split: shortcut_report([t for t in audited if t['split'] == split]) for split in ('train','validation','test')}
    schedule = []
    train = [t for t in audited if t['split'] == 'train']
    for step in range(60):
        batch = select_batch(train, step, 60, 4, 20260912)
        schedule.append(dict(step=step, ids=[t['id'] for t in batch], buckets=dict(Counter(t['curriculum']['bucket'] for t in batch))))
    write('schedule_preview.jsonl', schedule)
    result = dict(version=VERSION, oracle=ORACLE_VERSION, audited=True, training_ready=not failures,
                  source=str(folder), inspected_development_data=True, actual_LM=False,
                  tasks=len(audited), failures=len(failures), contrasts=len(contrasts), splits=reports,
                  recipe='Single-query; 25% controls; core short-history share fades 75% to 25%; family/label balanced.',
                  limitation='Structural difficulty only. These inspected development families are not a blind benchmark.',
                  data_sha256={name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in
                               ('tasks.jsonl','pairs.jsonl','contrasts.jsonl','schedule_preview.jsonl')},
                  source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      (Path(__file__), folder/'summary.json', folder/'all_candidate_inputs.jsonl', folder/'all_candidate_labels.jsonl')})
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failures: raise SystemExit(2)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--per-family', type=int, default=3)
    a = p.parse_args(); build(a.data_dir, a.out, a.per_family)
