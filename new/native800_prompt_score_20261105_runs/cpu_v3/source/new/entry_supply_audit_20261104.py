"""Inventory observable entry states; no800 selection, sampling, or new solver."""
from new import qualified_parents_6535_20261104 as p
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
from pathlib import Path
import time

VERSION = 'qualified-parent-entry-supply-v1'
REG = p.m.ROOT/'examples/strategic_slices/versions/entry_supply_v1_20261104/SNAPSHOT.json'
TAGS = ('information_use', 'information_current', 'information_future',
        'information_private', 'information_history', 'information_LP_witness',
        'strict_query_pending_answer_causality', 'valuation_verified_predicate',
        'planning_verified_predicate', 'response_own_choice',
        'response_social_priority', 'response_social_information', 'other_nonflat_Q')


class OrderedLocator:
    """Skip irrelevant subtrees, replay actual native histories in preorder."""
    def __init__(self, indexed):
        self.indexed = indexed
        self.path = [(0, indexed.rules.initial(), indexed.nodes)]
        self.last = -1

    def find(self, target):
        assert target >= self.last, 'Saved profiles must be in native preorder'
        self.last = target
        while not (self.path[-1][0] <= target < self.path[-1][0]+self.path[-1][2]):
            self.path.pop()
        while self.path[-1][0] != target:
            index, node, _ = self.path[-1]
            position = index+1
            for action in self.indexed.rules.actions(node):
                child = self.indexed.rules._apply(node, action)
                size = self.indexed.stats(child)[0]
                if position <= target < position+size:
                    self.path.append((position, child, size))
                    break
                position += size
            else:
                raise AssertionError((target, index))
        return self.path[-1][1]


def focal_horizon(rules, node, focal):
    """Exact min/max focal decisions over ALL legal continuations, including entry.

    PASS/REJECT preserve commitments. To attain max, each eligible other player
    can offer once to focal, who rejects; so no promise is consumed. Current
    pending response is handled first. This uses quota1/max_changes1 only.
    It is NOT a length expectation or support restricted to saved reference.
    """
    assert rules.offer_limit == 1 and rules.spec.max_changes == 1
    state = node.state
    pending = node.pending is not None
    start = state.turn_index+int(pending)
    remaining = rules.spec.round_robin[start:]
    proposals = sum(actor == focal for actor in remaining)
    current_response = int(pending and rules.actor(node) == focal)
    minimum = proposals+current_response
    commitments = state.snapshot_commitments()
    free = [not all(row) for row in commitments]
    optional = sum(actor != focal and actor in remaining
                   and state.offer_used[actor] < rules.offer_limit
                   and (free[actor] or free[focal])
                   for actor in range(rules.spec.n_players))
    return dict(min=minimum, max=minimum+optional,
                scheduled_focal_proposals=proposals,
                current_response=current_response,
                optional_future_responses=optional)


def native_horizon(rules, node, focal):
    if rules.actor(node) is None:
        return 0, 0
    children = [native_horizon(rules, rules._apply(node, action), focal)
                for action in rules.actions(node)]
    here = int(rules.actor(node) == focal)
    return here+min(x[0] for x in children), here+max(x[1] for x in children)


def classify(row, certified_witness):
    tags = []
    positive = [x for x in row['S_items'] if x['S'] > p.m.EPS]
    if positive:
        tags.append('information_use')
        if any(x['own_current_loss'] > p.m.EPS for x in positive): tags.append('information_current')
        if any(x['own_future_loss'] > p.m.EPS for x in positive): tags.append('information_future')
        for channel in ('private', 'history'):
            if any(x['omitted'][0] == channel for x in positive): tags.append('information_'+channel)
    if certified_witness: tags.append('information_LP_witness')
    if row['query_gap'] is not None and row['query_gap'] > p.m.EPS:
        tags.append('strict_query_pending_answer_causality')
    if p.valuation_witness(row) is not None: tags.append('valuation_verified_predicate')
    planning = p.planning_witness(row)
    if planning is not None: tags.append('planning_verified_predicate')
    if row['phase'] == 'response':
        if row['span'] > p.m.EPS: tags.append('response_own_choice')
        values = [row['Q_others'][a] for a in row['own_optimal']]
        if max(values)-min(values) > p.m.EPS: tags.append('response_social_priority')
        if any((x.get('response_secondary_loss') or 0) > p.m.EPS for x in row['S_items']):
            tags.append('response_social_information')
    if not tags and row['span'] > p.m.EPS: tags.append('other_nonflat_Q')
    return tags, positive, planning


def worker(parent, pool, out, native_checks, max_check_nodes):
    started = time.monotonic()
    folder = out/'cases'/str(parent['index']); folder.mkdir(parents=True)
    source = json.loads((p.m.ROOT/parent['admission']['path']).read_text())['source']
    assert p.digest(parent['raw']) == parent['source_raw_sha256'] == source['raw_sha256']
    for kind in ('labels', 'reference'):
        assert p.m.sha(pool/parent[kind]['path']) == parent[kind]['sha256']
    indexed = p.IndexedReference(source['job'])
    locator = OrderedLocator(indexed); rules = indexed.rules
    witness = json.loads((pool/parent['witness_check']['path']).read_text())
    lp = parent['purpose'] == 'information'
    if lp: assert witness['proof']['S_lower'] > p.m.EPS
    counts = Counter(); tag_counts = Counter(); stages = defaultdict(Counter)
    horizons = defaultdict(Counter); checks = []; checked_nodes = set(); seen = {}; physical = defaultdict(set)
    examples = {}; prior_node = None; base = None; skeleton = None
    world_rows = rules.worlds
    with gzip.open(pool/parent['labels']['path'], 'rt') as stream, gzip.open(folder/'entries.jsonl.gz', 'wt') as dest:
        for line in stream:
            row = json.loads(line); counts['saved_rows'] += 1
            if row['counterfactual_mass'] <= 0:
                counts['zero_CF_unavailable'] += 1
                continue
            assert row['Q_scope'] == 'contingent_BR'
            node = locator.find(row['node'])
            if row['node'] != prior_node:
                actions = [a.to_dict() for a in rules.actions(node)]
                assert actions == row['actions']
                assert rules.actor(node) == row['actor'] and node.state.turn_index == row['turn']
                assert ('response' if node.pending is not None else 'proposal') == row['phase']
                facts = dict(actor=row['actor'], turn=row['turn'],
                    commitments=node.state.snapshot_commitments(), query_used=node.state.query_used,
                    offer_used=node.state.offer_used,
                    pending=None if node.pending is None else node.pending.to_dict(),
                    history=[e.to_dict() for e in node.state.transcript], legal=actions)
                base = p.digest(facts)
                skeleton = p.digest({k:v for k,v in facts.items() if k not in ('history', 'legal')})
                slots = tuple(p.observed_slots(node, row['actor']))
                prior_node = row['node']
            assert [tuple(x[:2]) for x in row['private_answers']] == list(slots)
            assert abs(sum(row['posterior'])-1) < 1e-9
            for wi in row['world_ids']:
                assert list(world_rows[wi][row['actor']]) == row['own_type']
                assert all(world_rows[wi][a][g] == value for a,g,value in row['private_answers'])
            entry_id = p.digest([parent['canonical_id'], base, row['own_type'], sorted(row['private_answers'])])
            semantic = p.digest({k:row[k] for k in ('world_ids','posterior','actions','Q','Q_others','optimal','S_items')})
            if entry_id in seen:
                assert seen[entry_id] == semantic, 'Same observations have inconsistent labels/beliefs'
                counts['exact_observation_duplicates'] += 1
                continue
            seen[entry_id] = semantic
            counts['unique_positive_CF_entries'] += 1
            certified = lp and row['node'] == witness['witness']['node'] and row['cell'] == witness['witness']['cell']
            tags, positive, planning = classify(row, certified)
            horizon = focal_horizon(rules, node, row['actor'])
            assert horizon['min'] >= 1
            h = f'{horizon["min"]}-{horizon["max"]}'
            stage = f'{row["phase"]}/turn{row["turn"]}'
            counts['Q_nonflat'] += row['span'] > p.m.EPS
            counts['missing_S_items'] += row['unavailable_S_items']
            counts['entries_with_missing_S'] += row['unavailable_S_items'] > 0
            counts['no_omittable_information'] += not row['S_items'] and not row['unavailable_S_items']
            relative = any(x['relative_Q_change_Linf'] > p.m.EPS for x in row['S_items'])
            counts['relative_Q_changed'] += relative
            distribution = any(x['policy_total_variation'] > p.m.EPS for x in row['S_items'])
            counts['distribution_changed_without_S_or_relative_Q'] += distribution and not positive and not relative
            groups = ['all']+tags
            substantive = [t for t in tags if t not in ('strict_query_pending_answer_causality', 'other_nonflat_Q')]
            if substantive:
                counts['established_reason_union'] += 1; groups.append('established_reason_union')
            if tags: counts['all_tagged_union'] += 1
            else: counts['no_declared_reason'] += 1
            for tag in groups:
                tag_counts[tag] += 1
                stages[tag][stage] += 1; horizons[tag][h] += 1
                if tag != 'all': physical[tag].add(skeleton)
            record = dict(id=entry_id, parent_index=parent['index'], parent_id=parent['id'],
                source_key=parent['source_key'], node=row['node'], cell=row['cell'],
                actor=row['actor'], phase=row['phase'], turn=row['turn'], tags=tags,
                focal_decisions_to_native_terminal=horizon, physical_skeleton=skeleton,
                reference_reachable=row['reference_mass'] > 0,
                positive_S_channels=sorted({x['omitted'][0] for x in positive}),
                positive_S_items=[dict(omitted=x['omitted'],S=x['S'],current=x['own_current_loss'],future=x['own_future_loss']) for x in positive],
                own_Q_span=row['span'], query_gap=row['query_gap'],
                planning_kind=None if planning is None else planning['kind'],
                relative_Q_changed=relative, unavailable_S_items=row['unavailable_S_items'],
                detail='Read this node/cell in the hash-bound parent profile; hidden worlds are not separate entries')
            dest.write(p.stable(record)+'\n')
            for tag in tags:
                if tag not in examples: examples[tag] = record
            if (tags and len(checks) < native_checks and row['node'] not in checked_nodes
                    and indexed.stats(node)[0] <= max_check_nodes):
                actual = native_horizon(rules, node, row['actor'])
                assert actual == (horizon['min'], horizon['max'])
                checked_nodes.add(row['node'])
                checks.append(dict(node=row['node'],actor=row['actor'],native_nodes=indexed.stats(node)[0],
                                   native_min=actual[0],native_max=actual[1]))
    assert counts['saved_rows'] == source['profile_result']['summary']['contexts']+counts['zero_CF_unavailable']
    if lp: assert tag_counts['information_LP_witness'] == 1
    result = dict(index=parent['index'], source_key=parent['source_key'], players=parent['players'],
        primary_purpose=parent['purpose'], geometry=parent['geometry'], counts=dict(counts),
        tags={t:tag_counts[t] for t in ('all',)+TAGS+('established_reason_union',)},
        stages={k:dict(v) for k,v in stages.items()}, horizons={k:dict(v) for k,v in horizons.items()},
        physical_skeleton_counts={k:len(v) for k,v in physical.items()},
        horizon_native_checks=checks, examples=examples,
        entries=dict(path=str((folder/'entries.jsonl.gz').relative_to(out)),sha256=p.m.sha(folder/'entries.jsonl.gz')),
        elapsed_seconds=time.monotonic()-started)
    p.m.write(folder/'SUMMARY.json',result)
    print(dict(index=parent['index'],source=parent['source_key'],entries=tag_counts['all'],
               info=tag_counts['information_use'],seconds=round(result['elapsed_seconds'],2)),flush=True)
    return result


def aggregate(results):
    out = {}
    for name, cases in [('all',results),('two_player',[x for x in results if x['players']==2]),
                        ('three_player',[x for x in results if x['players']==3])]:
        counts=Counter(); tags=Counter(); stages=defaultdict(Counter); horizons=defaultdict(Counter)
        for case in cases:
            counts.update(case['counts']); tags.update(case['tags'])
            for k,v in case['stages'].items(): stages[k].update(v)
            for k,v in case['horizons'].items(): horizons[k].update(v)
        concentration={}
        for tag in TAGS:
            ranked=sorted(cases,key=lambda x:(-x['tags'][tag],x['index']))
            total=tags[tag]
            concentration[tag]=dict(parents=sum(x['tags'][tag]>0 for x in cases),
                top2=[dict(index=x['index'],source=x['source_key'],count=x['tags'][tag]) for x in ranked[:2]],
                top2_share=sum(x['tags'][tag] for x in ranked[:2])/total if total else None,
                physical_skeletons=sum(x['physical_skeleton_counts'].get(tag,0) for x in cases))
        out[name]=dict(parents=len(cases),counts=dict(counts),tags=dict(tags),
            stages={k:dict(v) for k,v in stages.items()},horizons={k:dict(v) for k,v in horizons.items()},
            concentration=concentration,native_horizon_checks=sum(len(x['horizon_native_checks']) for x in cases))
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--indices',default='all');parser.add_argument('--native-checks-per-parent',type=int,default=6)
    parser.add_argument('--max-native-check-nodes',type=int,default=1000);args=parser.parse_args()
    args.pool=args.pool.resolve();args.output=args.output.resolve()
    manifest=json.loads((args.pool/'MANIFEST.json').read_text());complete=json.loads((args.pool/'COMPLETE.json').read_text())
    assert p.m.sha(args.pool/'MANIFEST.json')==complete['manifest_sha256']
    assert p.m.sha(args.pool/'parents.jsonl')==complete['parents_sha256']==manifest['parent_sha256']
    parents=[json.loads(x) for x in (args.pool/'parents.jsonl').read_text().splitlines()]
    indices=list(range(100)) if args.indices=='all' else list(map(int,args.indices.split(',')))
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='Observable entry supply audit only',workers=args.workers,
        requested_parent_indices=indices,entry_identity='Full public native facts/history+own type+direct answers, no hidden-world ID',
        duplicate_policy='Merge identical observations only if beliefs and all labels agree; otherwise fail',
        physical_skeleton='Concentration diagnostic only; never merges histories/beliefs',
        classes='Information use; strict-query candidates pending answer causality; existing valuation/planning predicates; response own/social; other nonflatQ reserve',
        acquisition='Positive query_gap is NOT proof of private-answer value; no new acquisition certificate',
        horizon='Exact min/max focal decisions on all LEGAL paths, includes current; not fixed-reference expected length',
        horizon_validation=dict(checks_per_parent=args.native_checks_per_parent,max_native_nodes=args.max_native_check_nodes),
        target_split='Proposed600train-candidates/200validation;80/20parents; no split membership or800 selected',
        parent_ratio='65/35 is not automatically an800entry quota',
        no_new_Oracle_Q_S=True),dict(parent_manifest=p.ident(args.pool/'MANIFEST.json'),parents=p.ident(args.pool/'parents.jsonl')))
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        pending=[executor.submit(worker,parents[i],args.pool,args.output,args.native_checks_per_parent,args.max_native_check_nodes) for i in indices]
        for future in as_completed(pending):
            results.append(future.result());results.sort(key=lambda x:x['index'])
            p.m.write(args.output/'PARENTS.json',results)
    summary=aggregate(results);p.m.write(args.output/'SUMMARY.json',summary)
    lines=['# 逐父入口供给表','',
        '各列可交叉，不相加；调查列尚未核验私人答案因果收益。物理骨架只计集中度，不合并历史。',
        '完整S/Q与belief见父池profile；本表未选800或分train/validation。','',
        '|index|来源|人数|去重入口|正S|调查严格最优待验|估值|规划|回应own|回应社会平局|',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for x in results:
        t=x['tags'];lines.append(f'|{x["index"]}|{x["source_key"]}|{x["players"]}|{t["all"]}|{t["information_use"]}|{t["strict_query_pending_answer_causality"]}|{t["valuation_verified_predicate"]}|{t["planning_verified_predicate"]}|{t["response_own_choice"]}|{t["response_social_priority"]}|')
    (args.output/'PARENT_SUPPLY.md').write_text('\n'.join(lines)+'\n')
    p.m.write(args.output/'COMPLETE.json',dict(parents=len(results),summary_sha256=p.m.sha(args.output/'SUMMARY.json'),
        parent_results_sha256=p.m.sha(args.output/'PARENTS.json'),table_sha256=p.m.sha(args.output/'PARENT_SUPPLY.md'),
        pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json'),
        unique_entries=summary['all']['tags']['all'],candidate800='NOT_SELECTED',D='NOT_MEASURED'))


if __name__=='__main__':main()
