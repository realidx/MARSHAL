"""Combine native easy candidates with unchanged existing tasks; never launch training."""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from training.social_mixed.reasoning_bank import load, PATH as OLD
from training.social_mixed.build_progressive_bank import OUT as EASY, stable, digest

OUT = OLD.parent / 'combined_curriculum_v1'


def scene_key(t):
    # Deliberately ignore evidence, priors, names, turn order and private preferences.
    # A conservative collision test, not a proof against all graph isomorphisms.
    g = t['input']['game']
    goals = sorted((bool(x['binary']), sorted((a['player_id'], a['action_id'])
                    for a in x['required_actions'])) for x in g['goals'])
    return stable([g['n_players'], g['n_actions_per_player'], goals])


def evidence_stage(t):
    i = t['input']; q = i['queries'][0]
    direct = any(f['player'] == q['player'] and f['goal'] == q['goal']
                 for f in i.get('private_results', []))
    small = len(i['game']['goals']) <= 2
    history = i.get('voluntary_history', [])
    if small and direct:
        return 'direct_evidence'
    if small and len(history) == 1:
        return ('single_choice_identifying' if len(t['teacher']['gold']['possible_preferences']) == 1
                else 'single_choice_uncertain')
    if small and not history:
        return 'public_constraints_only'
    return 'continued_or_multigoal'


def build():
    original = load('train') + load('validation')
    new = [json.loads(l) for l in (EASY/'tasks.jsonl').read_text().splitlines()]
    old_scenes = defaultdict(set)
    for t in original:
        old_scenes[scene_key(t)].add(t['split'])
    # Keep existing splits intact. Quarantine entire new families on any cross-split collision.
    blocked = {t['family'] for t in new if old_scenes[scene_key(t)] - {t['split']}}
    ids = {t['id'] for t in original}
    accepted = [t for t in new if t['family'] not in blocked and t['id'] not in ids]
    rows = []; parents = defaultdict(list)
    for origin, bank in [('existing', original), ('new_small_scene', accepted)]:
        for source in bank:
            t = deepcopy(source)
            t['curriculum_origin'] = origin
            t['training_ready'] = False
            rows.append(t); parents[t['canonical_id']].append(t)
    for group in parents.values():
        assert {t['paired_view'] for t in group} == {'B','O','Pplus'} and len(group) == 3
        assert len({t['split'] for t in group}) == 1
        b = next(t for t in group if t['paired_view'] == 'B')
        for t in group:
            t['b_evidence_stage'] = evidence_stage(b)
            t['difficulty_status'] = 'structural_candidate_not_empirically_verified'
    common = [t for group in parents.values()
              if next(t for t in group if t['paired_view'] == 'Pplus').get('p_train_eligible', False)
              for t in group]
    OUT.mkdir(exist_ok=True)
    files = {}
    def write(name, records):
        payload = ''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records).encode()
        (OUT/name).write_bytes(payload)
        files[name] = dict(rows=len(records), sha256=hashlib.sha256(payload).hexdigest())
    write('tasks.jsonl', rows)
    for split in ('train','validation'):
        write('common_'+split+'.jsonl', [t for t in common if t['split'] == split])
    retained = set(parents)
    relations = []
    for path, origin in [(OLD/'relations.jsonl','existing'), (EASY/'relations.jsonl','new_small_scene')]:
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r['left'] in retained and r['right'] in retained:
                relations.append(dict(r, curriculum_origin=origin))
    write('relations.jsonl', relations)
    summary = dict(status='candidate_not_runtime_bank', existing_parents=len(original)//3,
        added_parents=len(accepted)//3, quarantined_new_families=sorted(blocked),
        parents=len(parents), common_parents=len(common)//3,
        common_counts=dict(Counter(t['split'] for t in common if t['paired_view']=='B')),
        b_coverage=dict(Counter(t['split']+'/'+t['b_evidence_stage']+'/'+t['teacher']['gold']['favored']
            for t in common if t['paired_view']=='B')),
        existing_cross_split_scene_signatures=sum(len(s)>1 for s in old_scenes.values()),
        limitations=['Scene signature does not canonicalize player/action permutations.',
            'Existing family split is preserved; coarse scene sharing is reported, not silently repartitioned.',
            'No model learning measurement; no runtime loader replacement.',
            'P qualification and fixed-continuation limitations inherited unchanged.'])
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    manifest = dict(files=files, sources={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [OLD/'tasks.jsonl',EASY/'tasks.jsonl',OLD/'relations.jsonl',EASY/'relations.jsonl',Path(__file__)]},
        training_ready=False)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__ == '__main__':
    build()
