"""Deterministic development pilot; never selects on model responses."""
from pathlib import Path
import sys,json,hashlib
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HERE=Path(__file__).resolve().parent
from training.social_mixed.prompt_clarification import request
from training.b_sft.social_bp_training import reward,native_completion

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,rows):p.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
def build():
    source=ROOT/'examples/social_mixed/data_reasoning_v5_candidate/bp_validation.jsonl'
    rows=list(map(json.loads,source.read_text().splitlines()));tasks=[];requests=[];missing=[]
    train=list(map(json.loads,(source.parent/'bp_train.jsonl').read_text().splitlines()))
    def signature(r):return json.dumps(r['input'],sort_keys=True)
    signatures={signature(r) for r in train}
    specs=[]
    for mode in ('binary','linear'):
        for k in ('B1','B2','B3'):
            for support in ('full','reduced'):specs.append((k,mode,support))
        for k in ('P1','P2','P3'):specs.append((k,mode,'any'))
        for role in ('query_only','ordinary_only','result_use'):specs.append(('P4',mode,role))
    for k,mode,kind in specs:
        pool=[r for r in rows if r['kernel']==k and r['completion_mode']==mode]
        if k.startswith('B'):pool=[r for r in pool if (len(r['teacher']['gold']['possible_preferences'])==3)==(kind=='full')]
        elif kind=='result_use':pool=[r for r in pool if r['skill']=='result_use']
        elif kind!='any':pool=[r for r in pool if r.get('information_role')==kind and r['skill']!='result_use']
        cell=f'{k}/{mode}/{kind}'
        if not pool:missing.append(cell);continue
        t=deepcopy(min(pool,key=lambda r:hashlib.sha256(('diagnostic-v2:'+r['id']).encode()).hexdigest()))
        source_id=t['id'];t['id']='unit:'+cell
        t.update(condition='unit',case_id=t['id'],source_id=source_id,exact_training_input_match=signature(t) in signatures)
        assert reward(t,native_completion(t))['correct']
        tasks.append(t);requests.append(dict(task_id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))))
    for t in map(json.loads,(HERE/'composition/tasks.jsonl').read_text().splitlines()):
        t['exact_training_input_match']=signature(t) in signatures;tasks.append(t)
    requests+=list(map(json.loads,(HERE/'composition/requests.jsonl').read_text().splitlines()))
    # Analytic inverse planning: same observed A, different available alternative B.
    for context,b in [('diagnostic',[-1,0,1]),('uninformative',[0,0,0])]:
        likelihood=[1 if v<0 else .5 if v==0 else 0 for v in b]
        posterior=[p/sum(likelihood) for p in likelihood]
        possible=[x for x,p in zip(['want','neutral','avoid'],posterior) if p>0]
        favored='want' if context=='diagnostic' else 'undetermined'
        for assisted in (False,True):
            tid=f'inverse:{context}:{"likelihood" if assisted else "utilities"}'
            prompt=('A partner has one hidden preference: want, neutral or avoid, each with prior probability 1/3. '
                'It chooses between A and B by maximizing the following terminal own utilities, uniformly at ties. '
                'You observe voluntary action A. There are no future choices.\n'
                + '\n'.join(f'{p}: utility(A)=0; utility(B)={v}' for p,v in zip(['want','neutral','avoid'],b))
                +'\nInfer the posterior support and favored preference. Favored is undetermined when the largest two probabilities differ by at most 0.1. Explain briefly and call SUBMIT_BELIEFS.')
            if assisted:prompt+='\nVerified planning assistance: P(A | want, neutral, avoid) = '+str(likelihood)+'. These are likelihoods, not posterior probabilities.'
            schema=dict(type='object',additionalProperties=False,required=['possible_preferences','favored'],properties=dict(
                possible_preferences=dict(type='array',uniqueItems=True,minItems=1,items=dict(type='string',enum=['want','neutral','avoid'])),
                favored=dict(type='string',enum=['want','neutral','avoid','undetermined'])))
            tasks.append(dict(id=tid,task='analytic_B',condition='P_to_B_assisted' if assisted else 'P_to_B',case_id='inverse:'+context,
                teacher=dict(gold=dict(possible_preferences=possible,favored=favored),likelihood=likelihood,posterior=posterior),
                provenance='Authored analytic control; not native BENAC and not structural generalization'))
            requests.append(dict(task_id=tid,request=dict(messages=[dict(role='user',content=prompt)],tools=[dict(type='function',function=dict(name='SUBMIT_BELIEFS',parameters=schema))],tool_choice='auto',parallel_tool_calls=False,max_tokens=1024)))
    assert len({t['id'] for t in tasks})==len(tasks)
    dump(HERE/'tasks.jsonl',tasks);dump(HERE/'requests.jsonl',requests)
    manifest=dict(version='diagnostic-v2-pilot',tasks=len(tasks),missing_cells=missing,model_calls=0,
        selection='Stable hash within predetermined development strata; no model outcome filtering',
        temperature=1,top_p=1,max_tokens=1024,repeats=3,planned_calls_per_model=len(tasks)*3,
        source_sha256=sha(source),source=str(source.relative_to(ROOT)),
        exact_training_input_matches=[t['id'] for t in tasks if t.get('exact_training_input_match')],
        dependencies={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),HERE/'evaluate.py',HERE/'run.py',ROOT/'training/social_mixed/prompt_clarification.py',ROOT/'training/b_sft/social_bp_training.py',ROOT/'training/b_sft/social_named_probe.py']},
        files={n:sha(HERE/n) for n in ('tasks.jsonl','requests.jsonl','composition/certificates.json')})
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
if __name__=='__main__':build()
