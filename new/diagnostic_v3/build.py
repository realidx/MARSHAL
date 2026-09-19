from pathlib import Path
import json,hashlib
from copy import deepcopy
HERE=Path(__file__).resolve().parent
source=HERE.parent/'diagnostic_v2/composition'
tasks=list(map(json.loads,(source/'tasks.jsonl').read_text().splitlines()))
requests={r['task_id']:r['request'] for r in map(json.loads,(source/'requests.jsonl').read_text().splitlines())}
cases=[]
for t in tasks:
    if t['condition']!='P_gold':continue
    case=t['case_id'];q=t['input']['queries'][0]
    assert [w[q['player']][q['goal']] for w in t['teacher']['worlds']]==[1,0,-1]
    b=next(x for x in tasks if x['id']==case+':B')['teacher']['preference_weights']
    cases.append(dict(id=case,task=t,gold_belief=[b[k] for k in ('want','neutral','avoid')],
        requests={k:requests[case+':'+k] for k in ('B','P_gold','P_infer')}))
(HERE/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
(HERE/'certificates.json').write_bytes((source/'certificates.json').read_bytes())
m=dict(version='bp-repair-v3-pilot',cases=len(cases),independent_structures=1,repeats=3,max_calls_per_model=18,
    belief_interface='Full numeric distribution over the sole unknown preference; diagnostic only',
    scoring='All four cells use correct-posterior expected native own utility; no fabricated action for invalid output',
    projection='History removed from controlled P; native current state and tools retained. P_infer in v2 remains unassisted end-to-end diagnostic.',
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'cases.json',HERE/'certificates.json',HERE/'experiment.py']})
(HERE/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
print(json.dumps(m,indent=2))
