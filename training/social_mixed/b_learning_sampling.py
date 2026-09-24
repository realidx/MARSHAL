"""Opt-in weighted coverage for the frozen B candidate; no online reward filtering."""
def select(tasks, counts, size=4):
    weights={t['id']:t['b_sampling_weight'] for t in tasks if t['b_sampling_weight']>0}
    if size>len(weights) or size<1:raise ValueError('Invalid group count')
    chosen=[]
    for _ in range(size):
        key=min((k for k in weights if k not in chosen),key=lambda k:((counts.get(k,0)+1)/weights[k],k))
        counts[key]=counts.get(key,0)+1;chosen.append(key)
    return chosen
