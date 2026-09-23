"""Operation links between existing certified parents; no auxiliary answers or relabeling."""
from collections import defaultdict
from copy import deepcopy
from itertools import combinations
import json

VERSION='operation-links-v1'
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))


def operation(group):
    b=next(t for t in group if t['paired_view']=='B')
    p=next(t for t in group if t['paired_view']=='Pplus')
    i=b['input'];q=i['queries'][0];hist=i.get('voluntary_history',[])
    direct=any(f['player']==q['player'] and f['goal']==q['goal'] for f in i.get('private_results',[]))
    support=len(b['teacher']['gold']['possible_preferences'])
    evidence=('direct_result' if direct else 'prior_and_public_constraints' if not hist else
              'single_behavior_exclusion' if len(hist)==1 and support==1 else
              'single_behavior_uncertainty' if len(hist)==1 else 'multiple_events')
    remaining=len(i['game']['round_robin'])-i['current_state']['turn_index']
    response=bool(i['pending_offer'])
    # Last proposal still has a partner response, so don't label it direct terminal.
    horizon='terminal_response' if response and remaining<=1 else 'last_proposal' if not response and remaining<=1 else 'continuation'
    known=all(len(x['possible_preferences'])==1 for x in p['input']['supplied_belief'].get('semantic_beliefs',[]))
    return dict(B=evidence,P=('known' if known else 'uncertain')+'/'+horizon,
        O=evidence+'/'+horizon,remaining=remaining,goals=len(i['game']['goals']),
        mode=b['completion_mode'],status='operation_description_not_mastery')


def evidence_input(t):
    i=deepcopy(t['input'])
    for key in ('supplied_belief','belief_source','history','task','queries'):
        # 'history' is not removed: source implementations may use it for evidence.
        if key!='history':i.pop(key,None)
    return i


def links(groups,windows):
    os={c:next(t for t in ts if t['paired_view']=='O') for c,ts in groups.items()}
    records=[]
    # These are evidence contrasts, not claims that one side is intrinsically harder.
    for field,kind in [('background_prior','prior_contrast'),('private_results','result_contrast')]:
        buckets=defaultdict(list)
        for c,t in os.items():
            i=evidence_input(t);value=i.pop(field,None)
            buckets[stable(i)].append((c,value))
        for members in buckets.values():
            for (a,x),(b,y) in combinations(members,2):
                if x!=y:records.append(dict(left=a,right=b,kind=kind,changed_field=field,
                    scope='All other normalized source input fields identical; teacher recomputed in source bank'))
    for kind,pairs in windows.items():
        for a,b in pairs:
            records.append(dict(left=a,right=b,kind=kind,scope='Existing feedback-window certification'))
    # Related operation stages: exact same rules, preferences and public policy,
    # but different native histories/turn schedules. NOT single-factor interventions.
    families=defaultdict(list)
    for c,t in os.items():
        i=t['input'];g=deepcopy(i['game']);g.pop('round_robin',None)
        key=stable([g,i['player'],i['own_preferences'],i['public_preferences'],i['background_prior'],i['partner_policy']])
        families[key].append(c)
    ops={c:operation(ts) for c,ts in groups.items()}
    for members in families.values():
        # Preserve a sparse connection between operation cells rather than every possible pair.
        cells=defaultdict(list)
        for c in sorted(members):cells[(ops[c]['B'],ops[c]['P'])].append(c)
        for a,b in combinations(sorted(cells),2):
            x=cells[a][0];y=cells[b][0]
            records.append(dict(left=x,right=y,kind='same_scene_operation_link',
                scope='Same goal geometry/preferences/prior/policy; histories and horizons may both differ. Not a controlled difficulty increment.'))
    return sorted(records,key=lambda r:(r['kind'],r['left'],r['right']))
