"""Fixed D batches, intact relations and checkpointed exposure balancing."""
VERSION = 'd-coverage-fixed12-v1'


def plan(collector):
    state=collector.state
    memory=state.setdefault('coverage', {})
    structure=state.setdefault('coverage_structure',{})
    def cell(view,c):
        t=collector.views[c,view]
        return view+':'+t['completion_mode']+':'+t['source_kernel']
    block=state['block']; result=[]; used={'O':set(),'B':set(),'Pplus':set()}
    def choose(view, candidates, label):
        candidates=[tuple(cs) for cs in candidates if not used[view].intersection(cs)]
        if not candidates:raise ValueError('No distinct eligible coverage unit for '+label)
        def rank(cs):
            records=[memory.get(view+':'+c, {}) for c in cs]
            return (min(r.get('count',0) for r in records),
                    sum(r.get('count',0) for r in records)/len(records),
                    max(r.get('last',-1) for r in records),
                    sum(structure.get(cell(view,c),0) for c in cs),cs)
        cs=min(candidates,key=rank)
        for j,c in enumerate(cs):
            key=view+':'+c; old=memory.get(key,{})
            memory[key]=dict(old,count=old.get('count',0)+1,last=block,
                             previous_gap=None if 'last' not in old else block-old['last'])
            sk=cell(view,c);structure[sk]=structure.get(sk,0)+1
            used[view].add(c);result.append((c,view,f'{label}-{j}'))
    windows=collector.feedback_windows
    if windows:
        choose('O',windows['must_change'],'must-change')
        kind='update' if block%2==0 else 'maintain'
        choose('B',windows[kind],kind)
    for view in ('O','B','Pplus'):
        eligible=[c for c in collector.schedule if view!='Pplus' or collector.views[c,view].get('p_train_eligible',True)]
        while len(used[view])<4:
            choose(view,[(c,) for c in eligible],'coverage-'+view)
    return result
