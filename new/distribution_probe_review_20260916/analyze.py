import json,statistics,hashlib
from pathlib import Path
from collections import Counter,defaultdict
from training.b_sft.social_bp_training import reward
from training.social_mixed.core import Episode
ROOT=Path(__file__).resolve().parents[2];RUN=ROOT/'runs/distribution_probe_v1_download/20260915-170449';OUT=Path(__file__).parent
read=lambda p:[json.loads(s) for s in p.read_text().splitlines()]
bp=read(RUN/'run/evaluation/bp/bp.jsonl');sp=read(RUN/'run/evaluation/sp/games.jsonl')
pack=ROOT/'examples/social_mixed/distribution_probe_v1'
expected={t['id']:t for t in read(pack/'bp.jsonl')}
assert len(bp)==1312 and len(sp)==192
assert all(r['task']==expected[r['task']['id']] for r in bp)
assert all(n==8 for n in Counter(r['task']['id'] for r in bp).values())
assert all(reward(r['task'],r['response']['completion'])==r['score'] for r in bp)
for game in sp:
 ep=Episode(game['reset'],game['group'],game['replica'],42)
 for call in game['calls']:
  assert ep.request()['messages']==call['request']['messages']
  ep.accept({'completion':call['completion']})
  assert ep.calls[-1]['valid']==call['valid']
 assert ep.status==game['status'] and ep.penalties==game['protocol']
 assert ep.terminal==game['terminal_utility']

def stats(rows):
 groups=defaultdict(list)
 for r in rows:groups[r['task']['id']].append(r)
 return dict(n=len(rows),correct=sum(r['score']['correct'] for r in rows),truncated=sum(r['score']['status']=='truncated' for r in rows),format_failure=sum(r['score']['status']=='format_failure' for r in rows),groups=len(groups),mixed=sum(0<sum(r['score']['correct'] for r in rr)<len(rr) for rr in groups.values()),all_wrong=sum(not any(r['score']['correct'] for r in rr) for rr in groups.values()),all_correct=sum(all(r['score']['correct'] for r in rr) for rr in groups.values()),set_exact=sum(r['score'].get('set_exact',False) for r in rows),favored_exact=sum(r['score'].get('favored_exact',False) for r in rows),full_set_outputs=sum(r['score'].get('predicted_full_set',False) for r in rows))
core=[r for r in bp if not r['task']['probe_diagnostic_only']];table={}
for split in ('train','validation'):
 for k in ('B1','B2','B3','P1','P2','P3','P4'):
  table[split+':'+k]=stats([r for r in core if r['task']['split']==split and r['task']['kernel']==k])
profiles={p:stats([r for r in core if r['task']['background_profile']==p]) for p in ('balanced','want_heavy','neutral_heavy','avoid_heavy')}
summary=json.loads((RUN/'run/evaluation/sp/summary.json').read_text());sg=summary['seat_groups'];complete=[g for g in sg if g['complete_group']]
lengths={}
for name,rows in [('correct',[r for r in bp if r['score']['correct']]),('wrong_complete',[r for r in bp if not r['score']['correct'] and r['score']['status']!='truncated']),('truncated',[r for r in bp if r['score']['status']=='truncated'])]:
 vals=[r['response']['usage']['completion_tokens'] for r in rows];lengths[name]=dict(n=len(vals),mean=statistics.mean(vals),median=statistics.median(vals))
bygroup=defaultdict(list)
for g in sp:bygroup[g['reset']['id']].append(g)
result=dict(verified=dict(bp_scores=len(bp),selfplay_replays=len(sp),task_match=True),core=stats(core),diagnostics=stats([r for r in bp if r['task']['probe_diagnostic_only']]),by_kernel=table,by_profile=profiles,lengths=lengths,selfplay=dict(status=dict(Counter(g['status'] for g in sp)),calls=summary['total_calls'],truncated=summary['truncated_calls'],invalid=summary['invalid_calls'],investigations=summary['investigations'],seat_groups=len(sg),complete_seat_groups=len(complete),variable_seat_groups=sum(not g['zero_outcome_advantage'] for g in complete),zero_seat_groups=sum(g['zero_outcome_advantage'] for g in complete),complete_reset_groups=sum(all(g['status']=='terminal' for g in gg) for gg in bygroup.values())))
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
