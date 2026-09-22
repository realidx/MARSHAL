"""Training-only evidence windows; no previous gold belief is supplied."""
from collections import defaultdict
import json

VERSION='feedback-windows-v1'
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def build_windows(tasks,relations):
    views={(t['canonical_id'],t['paired_view']):t for t in tasks if t['split']=='train'}
    groups=defaultdict(list)
    for (cid,view),t in views.items():
        if view!='B':continue
        i=t['input']
        key=stable([i['game'],i['player'],i['own_preferences'],i['public_preferences'],
                    i.get('imposed_setup'),i.get('background_prior'),i.get('partner_policy'),i['queries']])
        groups[key].append(t)
    result={'update':[],'maintain':[],'must_change':[]}
    for members in groups.values():
        for a in members:
            for b in members:
                x=a['input'].get('voluntary_history',[]);y=b['input'].get('voluntary_history',[])
                # Do not infer a temporal window if private observations changed:
                # those need independently attributed investigation outcomes.
                old=a['input'].get('private_results',[]);new=b['input'].get('private_results',[])
                if old!=new:
                    # Certify a single native investigation by this observer.
                    if len(y)!=len(x)+1 or y[:len(x)]!=x:continue
                    event=y[-1]
                    if event.get('action')!='INVESTIGATE' or a['input']['current_state'].get('current_proposer')!=a['input']['player']:continue
                    if any(f not in new for f in old):continue
                    added=[f for f in new if f not in old]
                    if len(added)!=1 or any(added[0][k]!=event.get(k) for k in ('player','goal')):continue
                if len(x)<len(y) and y[:len(x)]==x:
                    kind='maintain' if a['teacher']['gold']==b['teacher']['gold'] else 'update'
                    result[kind].append((a['canonical_id'],b['canonical_id']))
    for r in relations:
        if r['split']!='train' or not r.get('fixed_continuation_payoffs_match') or not r.get('isolated_B_action_pair'):continue
        a=views.get((r['left'],'O'));b=views.get((r['right'],'O'))
        if not a or not b:continue
        aa={stable(x) for x in a['teacher']['acceptable_actions']};bb={stable(x) for x in b['teacher']['acceptable_actions']}
        if aa and bb and aa.isdisjoint(bb):result['must_change'].append((r['left'],r['right']))
    # Rotate parent pairs first, rather than letting densely connected cases dominate.
    for kind,pairs in result.items():
        parents=defaultdict(list)
        for a,b in sorted(set(pairs)):
            parents[(views[a,'B']['package_id'],views[b,'B']['package_id'])].append((a,b))
        ordered=[]
        while any(parents.values()):
            for key in sorted(parents):
                if parents[key]:ordered.append(parents[key].pop(0))
        result[kind]=ordered
    return result
