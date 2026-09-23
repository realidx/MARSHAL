"""Frozen 200-parent training pool. Validation remains the existing independent bank."""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
from training.social_mixed import reasoning_bank as old
from training.social_mixed.task_difficulty import describe
from training.social_mixed.feedback_sampling import build_windows
from training.social_mixed.p_task_categories import inventory

PATH = old.PATH.parent / 'compact_bank_200'
SOURCE = old.PATH.parent / 'combined_curriculum_v1'
QUOTAS = {0:60, 1:60, 2:80}


def build():
    rows = list(map(json.loads, (SOURCE/'common_train.jsonl').read_text().splitlines()))
    groups = defaultdict(list)
    for t in rows: groups[t['canonical_id']].append(t)
    tiers = {c:max(describe(t)['tier'] for t in ts) for c,ts in groups.items()}
    bs = {c:next(t for t in ts if t['paired_view']=='B') for c,ts in groups.items()}
    ps = {c:next(t for t in ts if t['paired_view']=='Pplus') for c,ts in groups.items()}
    previous = old.load('train')
    cats = inventory(previous, old.load('train','cases.jsonl'))
    for c,p in ps.items():
        if c in cats: continue
        actions=p['input']['legal_actions']
        cats[c]=dict(operation='response' if p['input']['pending_offer'] else 'investigation_choice'
                     if any(a.get('action')=='INVESTIGATE' for a in actions) else 'ordinary_proposal',
                     horizon=p['planning_stage']+'_proxy',mode=p['completion_mode'],
                     relevance='relevant' if p['belief_action_relevant'] else 'control',
                     horizon_scope='generation structural proxy, not audited immediate transitions')
    relations=old.load('train','relations.jsonl')
    windows=build_windows(rows,relations)
    from training.social_mixed.operation_curriculum import links, operation
    operations={c:operation(ts) for c,ts in groups.items()}
    candidates_links=links(groups,windows)
    selected=set();counts=Counter();features=Counter();families=Counter()
    def cells(c):
        b=bs[c];p=cats[c]
        return [('B',b['b_evidence_stage'],b['teacher']['gold']['favored']),
                ('operation',operations[c]['B'],operations[c]['P']),
                ('P',p['operation'],p['horizon'],p['mode'],p['relevance']),
                ('source',b['source_kernel'],b['completion_mode'])]
    def add(c):
        if c in selected:return
        selected.add(c);counts[tiers[c]]+=1;features.update(cells(c));families[bs[c]['family']]+=1
    # Preserve at least one certified pair of each kind, without mandatory per-step pair quotas.
    for kind in ('update','maintain','must_change'):
        pair=next(cs for cs in windows[kind] if all(c in groups for c in cs))
        for c in pair:add(c)
    # Reserve up to 120 parents in linked units before broad coverage filling.
    # Each relation type gets a turn; all endpoints must fit the frozen tier budgets.
    linked_counts=Counter()
    while len(selected)<120:
        feasible=[]
        for r in candidates_links:
            fresh={r['left'],r['right']}-selected
            extra=Counter(tiers[c] for c in fresh)
            if not fresh or len(selected)+len(fresh)>120:continue
            if any(counts[t]+n>QUOTAS[t] for t,n in extra.items()):continue
            feasible.append((r,fresh))
        if not feasible:break
        r,fresh=min(feasible,key=lambda item:(linked_counts[item[0]['kind']],
            sum(features[x] for c in item[1] for x in cells(c))/len(item[1]),
            sum(families[bs[c]['family']] for c in item[1]),item[0]['left'],item[0]['right']))
        for c in sorted(fresh):add(c)
        linked_counts[r['kind']]+=1
    for tier,quota in QUOTAS.items():
        while counts[tier]<quota:
            candidates=[c for c in groups if tiers[c]==tier and c not in selected]
            c=min(candidates,key=lambda c:(sum(features[x] for x in cells(c)),families[bs[c]['family']],c))
            add(c)
    assert len(selected)==200 and dict(counts)==QUOTAS
    final=[dict(t,training_pool='compact-200-operations-v2',operation_curriculum=operations[c]) for c in sorted(selected) for t in groups[c]]
    assert len(final)==600 and all(t['split']=='train' and t['p_train_eligible'] for t in final)
    finalwindows=build_windows(final,relations)
    assert all(finalwindows.values())
    PATH.mkdir(exist_ok=True)
    payload=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in final).encode()
    (PATH/'tasks.jsonl').write_bytes(payload)
    selected_links=[r for r in candidates_links if r['left'] in selected and r['right'] in selected]
    (PATH/'operation_links.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in selected_links))
    meta=dict(categories={c:cats[c] for c in sorted(selected)},windows=finalwindows)
    (PATH/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    summary=dict(parents=200,views=600,tiers=dict(counts),
        origins=dict(Counter(bs[c]['curriculum_origin'] for c in selected)),
        b_coverage=dict(Counter('/'.join(cells(c)[0][1:]) for c in selected)),
        p_coverage=dict(Counter('/'.join(cells(c)[2][1:]) for c in selected)),
        windows={k:len(v) for k,v in finalwindows.items()},
        operation_links=dict(Counter(r['kind'] for r in selected_links)),
        linked_parents=len({r[k] for r in selected_links for k in ('left','right')}),
        validation='unchanged paired_bank_v2',selection='linked operations then structural coverage; no model outcomes',
        difficulty='unverified structural proxy',d_updates_per_cycle=50)
    (PATH/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    manifest=dict(version='compact-200-operations-v2',files={name:old.sha((PATH/name).read_bytes())
        for name in ('tasks.jsonl','metadata.json','summary.json','operation_links.jsonl')},
        sources={str(p.relative_to(old.ROOT)):old.sha(p.read_bytes()) for p in
            (SOURCE/'common_train.jsonl',old.PATH/'tasks.jsonl',old.PATH/'cases.jsonl',old.PATH/'relations.jsonl',Path(__file__),Path(__file__).with_name('operation_curriculum.py'))})
    (PATH/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


def load():
    old.load('train')  # Verify live prompt/reward contracts as well as the frozen original source.
    m=json.loads((PATH/'manifest.json').read_text())
    for name,sha in m['files'].items():
        if old.sha((PATH/name).read_bytes())!=sha:raise ValueError('Compact bank changed: '+name)
    for name,sha in m['sources'].items():
        if old.sha((old.ROOT/name).read_bytes())!=sha:raise ValueError('Compact source changed: '+name)
    rows=list(map(json.loads,(PATH/'tasks.jsonl').read_text().splitlines()))
    return rows,json.loads((PATH/'metadata.json').read_text()),old.sha((PATH/'manifest.json').read_bytes())

if __name__=='__main__':build()
