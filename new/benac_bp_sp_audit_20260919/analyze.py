"""Diagnostic counts only: no model calls, altered rewards, or optimal-policy labels."""
import json
from collections import Counter,defaultdict
from pathlib import Path
from training.social_mixed.core import Episode
from examples.final_evaluation.benac_a_suite import SEED
from training.social_mixed.frozen.bp_display import Names
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
RUNS={'q0':'q0-formal-859851','bp':'bp-step139-formal-859921','sp':'selfplay-step69-formal-859921'}
def value(obs,bits):
 vals={'want':1,'neutral':0,'avoid':-1}
 return sum(vals[pref]*(float(all(bits[a['player_id']][a['action_id']] for a in g['required_actions'])) if g['binary'] else sum(bits[a['player_id']][a['action_id']] for a in g['required_actions'])/len(g['required_actions'])) for pref,g in zip(obs['own_preferences'],obs['game']['goals']))
def reason(c):
 if c['completion']['finish_reason']=='length':return 'output_truncated'
 ts=c['completion']['raw_message'].get('tool_calls') or []
 if len(ts)!=1:return 'tool_count_'+str(len(ts))
 f=ts[0]['function'];o=c['observation'];n=Names(o)
 try:a=json.loads(f['arguments'])
 except Exception:return 'invalid_tool_json'
 if f['name']=='OFFER':
  names=a.get('self_commitments',[])+a.get('partner_commitments',[])
  if any(x in n.goals for x in names):return 'goal_as_commitment'
  try:
   partner=n.players.index(a['partner']);actor=o['player']
   if any(o['public_state']['commitments'][p][n.actions[p].index(x)] for field,p in [('self_commitments',actor),('partner_commitments',partner)] for x in a[field]):return 'already_bound_commitment'
  except Exception:return 'other_offer_schema'
 return 'other_illegal_action'
report={};queries=[];failure_rows=[];terminal_decisions=[]
for model,run in RUNS.items():
 base=ROOT/'runs/benac_a_soc'/run;rows=[json.loads(l) for l in (base/'games/games.jsonl').read_text().splitlines()];stats=Counter();types=Counter()
 for r in rows:
  d=base/'games'/f'{r["reset"]["id"]}-seat{r["focal_seat"]}';cs=[json.loads(l) for l in (d/'calls.jsonl').read_text().splitlines()];ep=Episode(r['reset'],r['reset']['id'],0,SEED)
  for i,c in enumerate(cs):
   if c['role']=='focal':
    if not c['valid']:types[reason(c)]+=1
    else:
     o=c['observation'];act=c['action'];bits=o['public_state']['commitments'];v=value(o,bits)
     if 'response' in act:
      # Own utility change from accepting is fully observed; future strategic value is NOT evaluated.
      accept=next(a for a in ep.rules.actions(ep.node) if a.to_dict().get('response')=='ACCEPT')
      child=ep.rules.step(ep.node,accept,realized_world=ep.world);delta=value(o,child.state.snapshot_commitments())-v
      sign='positive' if delta>1e-9 else 'negative' if delta< -1e-9 else 'zero'
      stats['response_'+sign+'_'+act['response']]+=1
      if child.state.is_terminal:
       optimal=(delta>=-1e-9 if act['response']=='ACCEPT' else delta<=1e-9)
       stats['terminal_response_total']+=1;stats['terminal_response_own_optimal']+=optimal
       terminal_decisions.append(dict(model=model,game=d.name,line=i+1,action=act,accept_delta=delta,own_optimal=optimal,path=str(d.relative_to(ROOT))))
     if act.get('action')=='OFFER':
      after=[list(b) for b in bits];after[o['player']]=act['proposer_action'];after[act['partner_id']]=act['partner_action'];delta=value(o,after)-v
      sign='positive' if delta>1e-9 else 'negative' if delta< -1e-9 else 'zero';stats['offer_own_immediate_'+sign]+=1
      if o['public_state']['turn_index']==len(o['game']['round_robin'])-1:
       stats['last_offer_own_immediate_'+sign]+=1
     if act.get('action')=='INVESTIGATE':
      after=[(j,z) for j,z in enumerate(cs[i+1:],i+2) if z['role']=='focal'];nxt=next(((j,z) for j,z in after if z['valid']),None)
      stats['queries']+=1;stats['query_has_later_valid_focal_action']+=nxt is not None
      queried_value=r['reset']['realized_world'][act['player']][act['goal']]
      queries.append(dict(model=model,game=d.name,line=i+1,query=act,result=queried_value,
        before=c['completion']['raw_message'].get('content'),next_line=None if nxt is None else nxt[0],next=None if nxt is None else nxt[1],path=str(d.relative_to(ROOT))))
   ep.accept(c)
  if r['status']!='terminal':
   last=cs[-1];prev=cs[-2];same=prev['completion']['raw_message'].get('tool_calls')==last['completion']['raw_message'].get('tool_calls')
   # IDs differ between calls; compare function name/args only.
   def functions(c):return [t['function'] for t in (c['completion']['raw_message'].get('tool_calls') or [])]
   failure_rows.append(dict(model=model,game=d.name,status=r['status'],responsible_role=last['role'],player=last['player'],focal_seat=r['focal_seat'],first_reason=reason(prev),retry_reason=reason(last),same_function_retry=functions(prev)==functions(last),first_line=len(cs)-1,retry_line=len(cs),path=str(d.relative_to(ROOT))))
 report[model]=dict(diagnostics=dict(stats),invalid_call_types=dict(types))
train=[json.loads(l) for l in (ROOT/'examples/social_mixed/data_binary_linear_v3/bp_train.jsonl').read_text().splitlines()]
coverage={}
for kernel in sorted({r['kernel'] for r in train}):
 rs=[r for r in train if r['kernel']==kernel]
 coverage[kernel]=dict(rows=len(rs),origin_ids=len({r['origin_id'] for r in rs}),players=dict(Counter(r['input']['game']['n_players'] for r in rs)),mode=dict(Counter(r['completion_mode'] for r in rs)),public_unfixed_slots=dict(Counter(r['input']['game']['n_players']*len(r['input']['game']['goals'])-len(r['input'].get('public_preferences',[])) for r in rs)),own_has_avoid=sum('avoid' in r['input']['own_preferences'].values() for r in rs),supplied_belief=sum('supplied_belief' in r['input'] for r in rs))
(OUT/'analysis.json').write_text(json.dumps(dict(models=report,training_coverage=coverage,failures=failure_rows,terminal_decisions=terminal_decisions),indent=2)+'\n')
(OUT/'query_followups.json').write_text(json.dumps(queries,indent=2)+'\n')
lines=[]
for q in queries:
 z=q['next'];lines += [f"\n## {q['model']} {q['game']} L{q['line']} query={q['query']} result={q['result']} followup=L{q['next_line']}",str(None if z is None else z['action']),'' if z is None else (z['completion']['raw_message'].get('content') or '')]
(OUT/'query_followups.txt').write_text('\n'.join(lines))
print(json.dumps(dict(models=report,coverage=coverage,failures=failure_rows),indent=2))
