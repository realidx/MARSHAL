"""Targeted variants and family-isolated B checkpoint/sequence evaluation data.

No baseline comparisons, LM requests, optimizer updates or new submission tools.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import permutations, product
import json
import hashlib
import math
from pathlib import Path

from training.b_sft.social_b_dataset import digest, mine, question, validate_pair, observer_belief, judgment
from training.b_sft.social_b_oracle import BeliefOracle, VERSION
from training.b_sft.shared_teacher import native, SearchLimit
from benac_p.endgame_diagnose import decode_action


def read(folder, name):
    return [json.loads(x) for x in (folder/name).read_text().splitlines()]


def family(raw):
    """Goal topology modulo player/action/goal renaming; ignore schedule and preferences.

    The older dataset_review.family_id includes schedule, so cannot guard this
    experiment's turn-order and deadline variants without this stricter grouping.
    """
    g=raw['game']; n=g['n_players']; counts=g['n_actions_per_player']
    if n>4 or max(counts)>2: raise ValueError('Pilot canonicalization budget exceeded')
    best=None
    for order in permutations(range(n)):
        players={p:i for i,p in enumerate(order)}
        for maps in product(*(permutations(range(k)) for k in counts)):
            goals=sorted((bool(goal.get('binary',True)), tuple(sorted(
                (players[a['player_id']], maps[a['player_id']][a['action_id']])
                for a in goal['required_actions']))) for goal in g['goals'])
            key=(tuple(counts[p] for p in order), tuple(goals))
            if best is None or key<best: best=key
    return 'topology-'+digest(best)


def variants(source):
    raw=source['raw']; schedule=raw['game']['round_robin']; n=raw['game']['n_players']
    if len(schedule)!=2*n: return
    later=schedule[n:]
    candidates=[('rotate_later',schedule[:n]+later[1:]+later[:1]),
                ('reverse_later',schedule[:n]+list(reversed(later))),
                ('earlier_deadline',schedule[:n])]
    seen={tuple(schedule)}
    for kind, turns in candidates:
        if tuple(turns) in seen: continue
        seen.add(tuple(turns))
        r=deepcopy(raw); r['id']=raw['id']+'-'+kind; r['game']['round_robin']=turns
        rules,_,_=native(r); node=rules.initial()
        for action in source['prefix']: node=rules._apply(node,decode_action(action))
        yield dict(**{k:v for k,v in source.items() if k not in ('id','raw')},
                   id=r['id'],raw=r,variant=kind,parent=raw['id'])


def split_families(sources, update_sources):
    groups={s['family'] for s in sources.values()}
    updates=sorted({sources[s]['family'] for s in update_sources},key=lambda x:digest(('split-v1',x)))
    assigned={g:('train','validation','test','train','train')[i%5] for i,g in enumerate(updates)}
    for g in sorted(groups):
        if g not in assigned:
            k=int(digest(('split-v1',g)),16)%10
            assigned[g]='train' if k<6 else 'validation' if k<8 else 'test'
    return assigned


def build(out, folders):
    if out.exists(): raise ValueError('Use a new output directory')
    out.mkdir(parents=True)
    code=[Path(__file__),Path('training/b_sft/social_b_dataset.py'),Path('training/b_sft/social_b_oracle.py'),
          Path('training/b_sft/social_b_random_window.py'),Path('training/b_sft/shared_teacher.py')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    def write(name,rows):
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    sources={}; records={}; labels={}; pairs=[]; candidates=[]; attempts=[]
    for folder in folders:
        summary=json.loads((folder/'summary.json').read_text())
        if summary['version']!=VERSION: raise ValueError('Oracle version mismatch')
        for path, checksum in summary['source_hashes'].items():
            if Path(path).name in ('social_b_oracle.py','social_b_random_window.py','shared_teacher.py'):
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=checksum:
                    raise ValueError('Cached oracle mechanism changed')
        incoming={s['id']:s for s in read(folder,'sources.jsonl')}
        selected=read(folder,'screened_pairs.jsonl')
        used={p['source'] for p in selected}
        for sid in used: sources[sid]=dict(incoming[sid], origin=str(folder))
        records.update({r['id']:r for r in read(folder,'all_candidate_inputs.jsonl')})
        labels.update({r['id']:r for r in read(folder,'all_candidate_labels.jsonl')})
        pairs.extend(selected)
        candidates.extend(p for p in read(folder,'all_candidate_pairs.jsonl') if p['source'] in used)
    parents=sorted({p['source'] for p in pairs if p['category']=='update'})
    for sid in parents:
        for source in variants(sources[sid]):
            raw=source['raw']; source_pairs=[]
            queries=source.get('queries',[dict(player=source['target'],goal=source['goal'])])
            audits=[]
            for q in queries:
                r,l,ps,a=mine(raw,source['prefix'],q['player'],q['goal'])
                records.update(r);labels.update(l);source_pairs.extend(ps);audits.append(a)
            sources[source['id']]=source
            candidates.extend(source_pairs)
            for category in ('formation','maintain','update'):
                eligible=[p for p in source_pairs if p['category']==category]
                # Emphasize incoming offers while retaining all discovered updates up to cap.
                eligible.sort(key=lambda p:(not p.get('received_offer',False),p['after']))
                pairs.extend(eligible[:3])
            attempts.append(dict(source=source['id'],parent=sid,variant=source['variant'],
                counts=dict(Counter(p['category'] for p in source_pairs)),audits=audits))
            print(json.dumps({k:v for k,v in attempts[-1].items() if k!='audits'}),flush=True)
    # Checkpoint candidates so validation need not be preceded by re-mining.
    write('variant_attempts.jsonl',attempts)
    write('sources.jsonl',sources.values())
    write('candidate_pairs.jsonl',candidates)
    write('candidate_inputs.jsonl',records.values())
    write('candidate_labels.jsonl',labels.values())
    # Match genuinely alternative actions at the exact same history/query.
    by_before=defaultdict(list)
    for p in candidates: by_before[(p['source'],p['before'])].append(p)
    contrasts=[]
    for group in by_before.values():
        updates=[p for p in group if p['category']=='update']
        maintains=[p for p in group if p['category']=='maintain']
        if updates and maintains:
            u,m=updates[0],maintains[0]
            contrasts.append(dict(source=u['source'],before=u['before'],update=u['after'],maintain=m['after']))
            pairs.extend([u,m])
    unique={(p['before'],p['after']):p for p in pairs}; pairs=list(unique.values())
    # Keep only history-dependent updates. This is a teacher data-design check,
    # not a no-history LM comparison or an additional evaluation baseline.
    kept=[]; rejected=[]
    for p in pairs:
        s=sources[p['source']]; a=records[p['after']]; b=records[p['before']]
        validate_pair(s['raw'],s['prefix'],b,a,p,labels)
        if p['category']=='update':
            q=a['input']['queries'][0]; h=a['input']['history']
            try:
                o=BeliefOracle(s['raw'],h[:-1],max_nodes=3000,seconds=2)
                o.observe(h[-1]); answer=observer_belief(o,q['player'],q['goal'])
                if judgment(answer)==judgment(labels[p['after']]['answer']):
                    rejected.append(dict(pair=p,reason='last_action_sufficient')); continue
            except (SearchLimit,ValueError) as exc:
                rejected.append(dict(pair=p,reason='history_dependence_unresolved',detail=str(exc)));continue
        kept.append(p)
    pairs=kept
    ids={p[k] for p in pairs for k in ('before','after')}
    contrasts=[c for c in contrasts if all(c[k] in ids for k in ('before','update','maintain'))]
    used={p['source'] for p in pairs}
    sources={k:s for k,s in sources.items() if k in used}
    for s in sources.values(): s['family']=family(s['raw'])
    splits=split_families(sources,{p['source'] for p in pairs if p['category']=='update'})
    tasks={}; legacy={}; replay_cache={}; joint_audits={}
    def task(sid, history):
        s=sources[sid]; key=(sid,digest(history))
        if key in replay_cache:return replay_cache[key]
        events=[dict(action=a,kind='setup' if i<len(s['prefix']) else 'partner') for i,a in enumerate(history)]
        o=BeliefOracle.replay(s['raw'],events,max_nodes=3000,seconds=2)
        reverse=BeliefOracle.replay(s['raw'],events,max_nodes=3000,seconds=2,reverse_actions=True)
        assert set(o.worlds)==set(reverse.worlds)
        reverse_weights=dict(zip(reverse.worlds,reverse.weights))
        assert all(math.isclose(weight,reverse_weights[w],abs_tol=1e-9,rel_tol=0)
                   for w,weight in zip(o.worlds,o.weights))
        queries=s.get('queries',[dict(player=s['target'],goal=s['goal'])])
        inp=question(o,queries[0]['player'],queries[0]['goal'],s['prefix'])
        inp['queries']=queries
        inp['instruction']='Infer every queried partner preference from the visible history. Give one judgment per query; do not choose a game action.'
        judgments=[]
        for q in queries:
            answer=observer_belief(o,q['player'],q['goal'])
            judgments.append(dict(**q,possible_preferences=answer['possible_preferences'],favored=answer['favored']))
        tid=digest((s['family'],inp))
        tasks[tid]=dict(id=tid,source=sid,family=s['family'],split=splits[s['family']],input=inp,
                       gold=dict(judgments=judgments),history_length=len(history))
        joint_audits[tid]=dict(id=tid,public_joint=o.joint_belief(),
            observer_joint=o.joint_belief(observer=s['raw']['ego'],own=s['raw']['own_preferences']),
            marginals=[dict(query=q,answer=observer_belief(o,q['player'],q['goal'])) for q in queries])
        replay_cache[key]=tid
        return tid
    for rid in sorted(ids): legacy[rid]=task(records[rid]['source'],records[rid]['input']['history'])
    edges=[]
    for p in pairs:
        query=records[p['after']]['input']['queries'][0]
        edges.append(dict(source=p['source'],before=legacy[p['before']],after=legacy[p['after']],
                          query=query,category=p['category'],changes=p.get('changes',{}),received_offer=p.get('received_offer',False)))
    contrast_tasks=[dict(source=c['source'],**{k:legacy[c[k]] for k in ('before','update','maintain')}) for c in contrasts]
    # Complete chronological B sequences along real compatible histories.
    # Each source contributes up to two distinct update histories; no prior gold
    # is passed to the model at a subsequent checkpoint.
    sequences=[]
    by_source=defaultdict(list)
    for p in pairs:
        if p['category']=='update':by_source[p['source']].append(records[p['after']]['input']['history'])
    for sid,histories in by_source.items():
        for history in sorted({digest(h):h for h in histories}.values(),key=digest)[:2]:
            prefix=sources[sid]['prefix']; checkpoints=[]
            for length in range(len(prefix),len(history)+1):
                checkpoints.append(task(sid,history[:length]))
            sequences.append(dict(id=digest((sid,history)),source=sid,family=sources[sid]['family'],
                split=splits[sources[sid]['family']],checkpoints=checkpoints))
    write('tasks.jsonl',tasks.values());write('pairs.jsonl',edges);write('contrasts.jsonl',contrast_tasks)
    write('sequences.jsonl',sequences);write('excluded_updates.jsonl',rejected);write('sources.jsonl',sources.values())
    write('joint_belief_audit.jsonl',joint_audits.values())
    for split in ('train','validation','test'):
        subset=[t for t in tasks.values() if t['split']==split]
        write(split+'_inputs.jsonl',[{k:v for k,v in t.items() if k!='gold'} for t in subset])
        write(split+'_labels.jsonl',[dict(id=t['id'],gold=t['gold']) for t in subset])
    summary=dict(oracle=VERSION,training_ready=False,actual_LM=False,baselines=[],
        source_hashes=hashes,
        sources=len(sources),families=len(set(splits)),variant_attempts=len(attempts),
        tasks=len(tasks),pairs=len(edges),categories=dict(Counter(p['category'] for p in edges)),
        paired_update_maintain=len(contrasts),sequences=len(sequences),
        split_counts={s:dict(tasks=sum(t['split']==s for t in tasks.values()),
                           families=sum(v==s for v in splits.values()),
                           sequences=sum(x['split']==s for x in sequences),
                           categories=dict(Counter(p['category'] for p in edges if tasks[p['after']]['split']==s)))
                      for s in ('train','validation','test')},
        scope='Development partitions of already inspected games, not a fresh blind paper benchmark.',
        evaluation='Independent checkpoints and sequential model-answer retention; gold always follows actual history.',
        update_final_preferences=dict(Counter(labels[p['after']]['answer']['favored'] for p in pairs if p['category']=='update')))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('folders',type=Path,nargs='+');a=p.parse_args();build(a.out,a.folders)
