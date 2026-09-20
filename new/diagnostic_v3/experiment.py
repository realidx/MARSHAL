"""Controlled B/P repair experiment. No model services are started."""
from pathlib import Path
import sys,json,hashlib,math,argparse
from copy import deepcopy
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
HERE=Path(__file__).resolve().parent
from training.b_sft.social_named_probe import present,score
VALUES=('want','neutral','avoid')

def load():
    m=json.loads((HERE/'manifest.json').read_text())
    for n,h in m['files'].items():
        if hashlib.sha256((HERE/n).read_bytes()).hexdigest()!=h:raise ValueError('Frozen artifact changed: '+n)
    return json.loads((HERE/'cases.json').read_text())

def b_request(case):
    r=deepcopy(case['requests']['B'])
    # Explicit full distribution for the only unknown slot: complete joint belief.
    r['messages'][1]['content']=r['messages'][1]['content'].split('RESPONSE INSTRUCTIONS')[0]+(
        '\nRESPONSE INSTRUCTIONS\nFor the queried partner preference, infer the full posterior distribution. '
        'Briefly explain, then call SUBMIT_DISTRIBUTION with want, neutral and avoid probabilities summing to 1. '
        'This numeric interface is only for the controlled diagnostic.')
    r['tools']=[dict(type='function',function=dict(name='SUBMIT_DISTRIBUTION',parameters=dict(type='object',additionalProperties=False,
        required=list(VALUES),properties={k:dict(type='number',minimum=0,maximum=1) for k in VALUES})))]
    return r

def p_request(case,belief):
    r=deepcopy(case['requests']['P_gold']);text=r['messages'][1]['content']
    # Fixed native state/actions, no past evidence with which to bypass injected B.
    before,rest=text.split('EVENTS IN ORDER',1)
    state=rest.split('CURRENT BINDING STATE',1)[1].split('CORRECT CURRENT BELIEF',1)[0]
    instructions=text.split('RESPONSE INSTRUCTIONS',1)[1]
    before=before.replace('Choose your next action using the supplied correct belief.','Choose your next action using the supplied belief.')
    slot=case['task']['input']['queries'][0]
    # Use the named query supplied in the B prompt rather than hidden identifiers.
    from training.b_sft.social_named_probe import Names
    n=Names(case['task']['input'],0)
    target=n.players[slot['player']]+"'s preference for "+n.goals[slot['goal']]
    r['messages'][1]['content']=before+'CURRENT BINDING STATE'+state+'\nSUPPLIED CURRENT BELIEF\n'+(
        'Use this distribution directly for this decision. All other preferences remain as publicly listed. '
        'Past behavioral evidence is intentionally withheld in this controlled planning condition.\n'+target+': '+
        '; '.join(f'{k}={p:.12g}' for k,p in zip(VALUES,belief)))+'\nRESPONSE INSTRUCTIONS'+instructions
    return r

def parse_b(c):
    if c.get('status')=='infrastructure_failure':return None,'infrastructure_failure'
    if c.get('finish_reason')=='length':return None,'truncated'
    try:
        calls=c['raw_message']['tool_calls'];assert len(calls)==1
        f=calls[0]['function'];assert f['name']=='SUBMIT_DISTRIBUTION'
        x=json.loads(f['arguments']);assert set(x)==set(VALUES)
        b=[x[k] for k in VALUES]
        assert all(type(p) in (float,int) and math.isfinite(p) and 0<=p<=1 for p in b)
        assert abs(sum(b)-1)<1e-6
        return [p/sum(b) for p in b],'ok'
    except (ValueError,KeyError,TypeError,AssertionError):return None,'format_failure'

def action_index(case,c):
    t=case['task'];s=score(t,c,'action_tools',0)
    if s['status']!='ok':return None,s['status']
    f=c['raw_message']['tool_calls'][0]['function'];a=json.loads(f['arguments'])
    a={'response' if f['name'] in ('ACCEPT','REJECT') else 'action':f['name'],**a}
    return present(t,0)['legal_actions'].index(a),'ok'

def values(case,b):
    # a x world x player; worlds are certified want/neutral/avoid in that order.
    return [sum(w*p[0] for w,p in zip(b,row)) for row in case['task']['teacher']['per_world_payoffs']]

def reference(case,b):
    own=values(case,b);best=max(own)
    choices=[i for i,v in enumerate(own) if abs(v-best)<1e-9]
    truth=values(case,case['gold_belief']);u=sum(truth[i] for i in choices)/len(choices)
    return dict(status='ok',action_indices=choices,tie_rule='uniform exact own-utility maximizers',utility=u,regret=max(truth)-u)

def model_value(case,c,belief=None):
    i,status=action_index(case,c)
    if i is None:return dict(status=status,utility=None,regret=None,input_belief_planning_regret=None)
    v=values(case,case['gold_belief']);local=values(case,belief if belief is not None else case['gold_belief'])
    return dict(status=status,action_index=i,utility=v[i],regret=max(v)-v[i],input_belief_planning_regret=max(local)-local[i])

def run_case(case,call):
    bc=call('B',b_request(case));b,status=parse_b(bc)
    gp=model_value(case,call('correct_B_model_P',p_request(case,case['gold_belief'])))
    cells={'correct_B_model_P':gp,'correct_B_reference_P':reference(case,case['gold_belief'])}
    if b is not None:
        cells['model_B_model_P']=model_value(case,call('model_B_model_P',p_request(case,b)),b)
        cells['model_B_reference_P']=reference(case,b)
    else:
        for k in ('model_B_model_P','model_B_reference_P'):cells[k]=dict(status='blocked_by_'+status,utility=None,regret=None)
    def gain(repaired,original):
        x,y=cells[repaired]['utility'],cells[original]['utility'];return None if x is None or y is None else x-y
    result = dict(case_id=case['id'],B_status=status,model_belief=b,gold_belief=case['gold_belief'],
        B_total_variation=None if b is None else sum(abs(x-y) for x,y in zip(b,case['gold_belief']))/2,
        cells=cells,B_repair_gain=gain('correct_B_model_P','model_B_model_P'),
        P_repair_gain=gain('model_B_reference_P','model_B_model_P'),
        P_repair_given_correct_B=gain('correct_B_reference_P','correct_B_model_P'),
        B_repair_with_reference_P=gain('correct_B_reference_P','model_B_reference_P'))
    complete=all(c['utility'] is not None for c in cells.values())
    result['four_cells_complete']=complete
    result['interaction_gamma']=(result['B_repair_with_reference_P']-result['B_repair_gain']) if complete else None
    result['total_gap']=gain('correct_B_reference_P','model_B_model_P')
    for key in ('P_repair_given_correct_B','B_repair_with_reference_P'):
        assert result[key] is None or result[key]>=-1e-9
    if complete:
        assert abs(result['total_gap']-result['B_repair_gain']-result['P_repair_given_correct_B'])<1e-9
        assert abs(result['total_gap']-result['P_repair_gain']-result['B_repair_with_reference_P'])<1e-9
    v=values(case,case['gold_belief']);lower=[x for x in v if max(v)-x>1e-9]
    result['decision_gap']=max(v)-max(lower) if lower else None
    result['near_optimal_tolerance']=case['task']['teacher'].get('own_tolerance',.1)
    return result

def audit_cases(cases):
    """Freeze the decision problem, not just its current commitments."""
    first=cases[0]
    for c in cases:
        assert c['task']['input']['legal_actions']==first['task']['input']['legal_actions']
        assert c['task']['teacher']['per_world_payoffs']==first['task']['teacher']['per_world_payoffs']
        # This certified last-proposal problem has no later hidden-type-aware
        # focal continuation. Only the partner response remains.
        state=c['task']['input']['current_state']
        assert state['turn_index']==len(state['round_robin'])-1
        assert c['task']['input']['pending_offer'] is None
        for belief in ([1/3]*3,[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],first['gold_belief']):
            assert p_request(c,belief)==p_request(first,belief)
            assert reference(c,belief)['action_indices']==reference(first,belief)['action_indices']
    return dict(cases=len(cases),same_prompt_actions_payoffs=True,last_proposal_only=True,
                continuation='Certified fixed partner responses; no re-solving on injected belief')

def summarize(rows,planned):
    from collections import Counter
    keys=('B_repair_gain','P_repair_gain','P_repair_given_correct_B','B_repair_with_reference_P','interaction_gamma','total_gap')
    def stat(xs):
        xs=[x for x in xs if x is not None]
        return dict(valid_pairs=len(xs),mean=sum(xs)/len(xs) if xs else None)
    return dict(planned=planned,returned=len(rows),missing=planned-len(rows),
        complete_four_cells=sum(r['four_cells_complete'] for r in rows),
        gains={k:stat([r[k] for r in rows]) for k in keys},
        cell_coverage={k:dict(valid=sum(r['cells'][k]['utility'] is not None for r in rows),
            statuses=dict(Counter(r['cells'][k]['status'] for r in rows))) for k in rows[0]['cells']} if rows else {},
        note='Means use each gain own paired subset; do not subtract means with different coverage. Two repair paths decompose one gap, not four additive contributions.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--model',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--max-tokens',type=int,default=4096)
    a=p.parse_args()
    if a.repeats<1 or a.max_tokens<1:p.error('repeats and max-tokens must be positive')
    a.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((HERE/'manifest.json').read_text())
    (a.output/'protocol.json').write_text(json.dumps(dict(model=a.model,base_url=a.base_url,repeats=a.repeats,temperature=1,top_p=1,max_tokens=a.max_tokens,manifest=manifest),indent=2))
    cases=load();audit_cases(cases)
    rows=[]
    with (a.output/'calls.jsonl').open('w') as log:
        for case in cases:
            for replica in range(a.repeats):
                def call(condition,request):
                    seed_condition='P' if condition.endswith('_model_P') else condition
                    seed=int(hashlib.sha256(f"v3:{case['id']}:{replica}:{seed_condition}".encode()).hexdigest()[:8],16)
                    body=dict(request,model=a.model,temperature=1,top_p=1,max_tokens=a.max_tokens,seed=seed)
                    try:
                        req=Request(a.base_url.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                        with urlopen(req,timeout=180) as response:raw=json.load(response)
                        choice=raw['choices'][0];c=dict(raw_message=choice['message'],finish_reason=choice['finish_reason'])
                    except Exception as exc:c=dict(status='infrastructure_failure',error_type=type(exc).__name__)
                    log.write(json.dumps(dict(case_id=case['id'],replica=replica,condition=condition,request=body,completion=c))+'\n');log.flush()
                    return c
                rows.append(dict(run_case(case,call),replica=replica))
                (a.output/'results.json').write_text(json.dumps(rows,indent=2))
                (a.output/'summary.json').write_text(json.dumps(summarize(rows,len(cases)*a.repeats),indent=2))
if __name__=='__main__':main()
