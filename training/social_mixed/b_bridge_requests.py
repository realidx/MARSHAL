"""Explicit training scaffolds; unassisted tasks retain byte-identical requests."""
from copy import deepcopy
from training.social_mixed.prompt_clarification import request as original


def request(task,arm='action_tools',variant=0):
    req=original(task,arm,variant)
    bridge=task.get('b_bridge')
    if not bridge:return req
    if task.get('split') not in (None,'train'):raise ValueError('Training scaffold in held-out data')
    req=deepcopy(req)
    text='\n\nTRAINING INFERENCE EXERCISE (same queried preference and observed history).\n'
    if bridge['stage']=='likelihood':
        text+='The table supplies the prior and probability of the observed voluntary event, conditional on each candidate value of the queried preference, under the stated teacher. Other unknown preferences are marginalized. These are inference aids, not the realized hidden preference.\n'
        text+='| Candidate | Prior | Observed-event likelihood |\n|---|---:|---:|\n'
        for r in bridge['table']:text+=f"| {r['preference']} | {r['prior']:.12g} | {r['likelihood']:.12g} |\n"
        text+='Combine prior and likelihood to infer which candidates remain possible and which is favored.\n'
    else:
        text+='For each candidate preference, compare the observed voluntary action with its legal alternatives under the stated partner policy, including its tie rule. An action can be beneficial yet less preferred than an alternative. Retain candidates with positive observed-event likelihood; compare posterior support after accounting for the prior. Do not assume an observation must eliminate a candidate.\n'
    req['messages'][1]['content']+=text
    return req
