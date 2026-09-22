"""Eight fixed CalBench stream development cases, using the resident actor."""
from copy import deepcopy
import json
from examples.final_evaluation.calbench_local import verify_source, separate_reasoning, InfrastructureFailure
from examples.final_evaluation.calbench_stream import load_frozen
from examples.final_evaluation.calbench_stream_metrics import diagnose
from training.social_mixed.core import seed_for

VERSION='calbench-training-dev8-v1'
CASE_IDS=[f'{family}_{cost}_s1' for family in ('loose','dense','blocked','replan') for cost in ('uniform','varied')]

def run(generate,seed):
    source=verify_source()
    from calendar_game.game import CalendarGame
    import calendar_game.game as module
    manifest,cases=load_frozen()
    selected={c['id']:c for c in cases}
    calls=[];games=[]
    original=module.make_llm_client
    class Transport:
        def __init__(self,aid,case_id):self.aid=aid;self.case_id=case_id;self.index=0
        def streaming_with_retry(self,messages,**kwargs):
            request=dict(messages=messages,tools=[],temperature=0.,raw_text=True,
                         seed=seed_for(seed,VERSION,self.case_id,self.aid,self.index))
            self.index+=1
            try:
                output=generate([request])[0]
                text,reasoning,_=separate_reasoning(output['text'])
            except Exception as exc:
                raise InfrastructureFailure(f'CalBench resident inference failed: {exc}') from exc
            valid=False
            try:
                obj=json.loads(text)
                valid=isinstance(obj,dict) and set(obj)=={'thinking','actions'} and isinstance(obj['thinking'],str) and isinstance(obj['actions'],list) and all(isinstance(a,dict) for a in obj['actions'])
            except (ValueError,TypeError):pass
            calls.append(dict(case_id=self.case_id,agent_id=self.aid,call_index=self.index-1,
                              request=request,text=output['text'],finish_reason=output['finish_reason'],
                              strict_envelope_valid=valid))
            return dict(text=text,reasoning=reasoning,duration_s=0.,finish_reason=output['finish_reason'],
                        prompt_tokens=len(output.get('prompt_ids',[])),completion_tokens=len(output['response_ids']),
                        total_tokens=len(output.get('prompt_ids',[]))+len(output['response_ids']))
    try:
        for case_id in CASE_IDS:
            print(f'CALBENCH_DEV_START {case_id}',flush=True)
            case=selected[case_id]
            module.make_llm_client=lambda spec:Transport(spec['agent_id'],case_id)
            config=dict(manifest['config'],seed=case['scenario']['seed'],
                        agents=[dict(type='llm',model='resident',agent_id=i) for i in range(4)])
            trace=CalendarGame(config).run_with_scenario(deepcopy(case['scenario']))
            raw=json.loads(trace.model_dump_json())
            case_calls=[r for r in calls if r['case_id']==case_id]
            diagnostics=diagnose(raw,case['scenario'],case_calls,case['family']=='replan')
            success=diagnostics['full_stream_completion']
            games.append(dict(case_id=case_id,formal_test=False,trace=raw,diagnostics=diagnostics,
                              success=success,optimal=success and raw['metrics']['realized_cost']==case['reference']['minimum_team_cost']))
    except InfrastructureFailure as exc:
        raise RuntimeError(str(exc)) from exc
    finally:module.make_llm_client=original
    metrics={'calbench/headline':sum(g['trace']['metrics']['headline_score'] for g in games)/8,
             'calbench/success_rate':sum(g['success'] for g in games)/8,
             'calbench/optimal_rate':sum(g['optimal'] for g in games)/8,
             'calbench/meeting_completion_rate':sum(g['diagnostics']['final_valid_meetings'] for g in games)/24,
             'calbench/strict_format_failures':sum(not c['strict_envelope_valid'] for c in calls),
             'calbench/truncations':sum(c['finish_reason']=='length' for c in calls)}
    for family in ('loose','dense','blocked','replan'):
        subset=[g for g in games if g['case_id'].startswith(family+'_')]
        metrics[f'calbench/{family}/success_rate']=sum(g['success'] for g in subset)/len(subset)
    protocol=dict(version=VERSION,case_ids=CASE_IDS,source_hash=source,temperature=0.,batch_invariant=False,
                  max_new_tokens=1024,formal_test=False,all_seats='current_actor',
                  note='s1 cases are development data; do not report the original 24 as independent held-out evaluation')
    return games,calls,metrics,protocol
