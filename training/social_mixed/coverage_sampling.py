"""Global per-view coverage: relations cannot bypass the least-exposed frontier."""
from training.social_mixed.task_difficulty import describe
VERSION = 'global-frontier-curriculum-btolerance-v4'


def choose_view(collector,view,quota):
    state=collector.state;memory=state.setdefault('coverage',{})
    visits=state.setdefault('coverage_structure',{});block=state['block']
    eligible=[c for c in collector.schedule if view!='Pplus' or collector.views[c,view].get('p_train_eligible',True)]
    if len(eligible)<quota:raise ValueError('Too few distinct eligible tasks for '+view)
    used=set();result=[]
    def difficulty(c):
        own=describe(collector.views[c,view])['order']
        parent_tier=max(describe(collector.views[c,v])['tier'] for v in ('O','B','Pplus') if (c,v) in collector.views)
        return (parent_tier,*own[1:])
    def count(c):return memory.get(view+':'+c,{}).get('count',0)
    def category(c):
        if view=='Pplus' and collector.p_categories:
            from training.social_mixed.p_task_categories import cell
            return view+':'+cell(collector.p_categories[c])
        t=collector.views[c,view]
        return view+':'+t['completion_mode']+':'+t['source_kernel']
    sizes={}
    for c in eligible:sizes[category(c)]=sizes.get(category(c),0)+1
    def record(cs,label):
        for j,c in enumerate(cs):
            key=view+':'+c;old=memory.get(key,{})
            memory[key]=dict(old,count=count(c)+1,last=block,
                previous_gap=None if 'last' not in old else block-old['last'])
            cell=category(c);visits[cell]=visits.get(cell,0)+1
            used.add(c);result.append((c,view,f'{label}-{j}-visit{memory[key]["count"]}'))
    # Relations remain intact when both ends are due globally. No mandatory pair tax each update.
    windows=collector.feedback_windows
    kind='must_change' if view=='O' else ('update' if block%2==0 else 'maintain') if view=='B' else None
    floor=min(map(count,eligible))
    pairs=[tuple(cs) for cs in windows.get(kind,[]) if len(set(cs))==2 and all(c in eligible and count(c)==floor for c in cs)] if kind else []
    if quota>=2 and pairs:
        pair=min(pairs,key=lambda cs:(max(difficulty(c) for c in cs),cs))
        record(pair,kind)
    while len(used)<quota:
        available=[c for c in eligible if c not in used]
        # Exposure precedes difficulty. Easy tasks cannot starve harder tasks.
        c=min(available,key=lambda c:(count(c),difficulty(c),
             visits.get(category(c),0)/sizes[category(c)],memory.get(view+':'+c,{}).get('last',-1),c))
        record((c,),'coverage-'+view)
    return result


def plan(collector):
    return [r for view in ('O','B','Pplus') for r in choose_view(collector,view,4)]
