"""Adversarial v2 native rollouts and shared-Q0 focal scoring."""
from pathlib import Path
import json,random
from training.social_mixed.core import Episode,seed_for,sp_prompt
from examples.final_evaluation.adversarial_checks import prefix_bounds,ownership_graph
SEED=2026091902

def scripted(ep,rng):
    actions=sp_prompt.visible(ep.observation())['legal_actions']
    name,args=sp_prompt.action_call(rng.choice(actions))
    return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop'))

def witnesses(reset):
    graph=ownership_graph(reset['raw']['game'])
    if not graph['has_cross_player_goal']:raise ValueError('No cross-player dependency')
    proofs=[{} for _ in range(3)]
    for attempt in range(256):
        ep=Episode(reset,reset['id'],attempt,SEED);rng=random.Random(seed_for(SEED,reset['id'],'witness',attempt))
        while ep.status=='running':ep.accept(scripted(ep,rng))
        assert ep.status=='terminal'
        for seat in range(3):
            if len(proofs[seat])<2:proofs[seat].setdefault(ep.terminal[seat],dict(utility=ep.terminal[seat],actions=[c['action'] for c in ep.calls]))
        if all(len(p)==2 for p in proofs):break
    if not all(len(p)==2 for p in proofs):raise ValueError('No utility-variation witness within fixed CPU budget: '+reset['id'])
    return dict(graph=graph,per_seat=[list(p.values()) for p in proofs],attempts=attempt+1)

def failures(calls):
    from collections import Counter
    from training.b_sft.social_named_probe import validate
    counts=Counter()
    for c in calls:
        if c['valid']:continue
        if c['completion']['finish_reason']=='length':counts['truncated']+=1;continue
        try:
            tools=c['completion']['raw_message']['tool_calls']
            if len(tools)!=1:raise ValueError('one call required')
            f=tools[0]['function'];args=json.loads(f['arguments'])
            schemas={t['function']['name']:t['function']['parameters'] for t in sp_prompt.tools_for(c['observation'])}
            validate(args,schemas[f['name']])
        except (KeyError,ValueError,TypeError):counts['format_or_schema']+=1
        else:counts['state_or_action']+=1
    return dict(counts)

def play(reset,seat,replica,routes,output,generate,shared=False,oracle=None):
    ep=Episode(reset,reset['id'],replica,SEED)
    tid=f"{reset['id']}-r{replica}-"+('shared-q0' if shared else f'seat{seat}')
    folder=Path(output)/tid;folder.mkdir()
    error=None
    with (folder/'calls.jsonl').open('w') as log:
        while ep.status=='running':
            actor=ep.rules.actor(ep.node);role='q0' if shared or actor!=seat else 'focal'
            request=ep.request()
            try:
                response=oracle.choose(ep) if oracle is not None and actor!=seat else generate(routes[role],request)
            except Exception as exc:
                ep.status='infrastructure_failure';error=repr(exc)
                log.write(json.dumps(dict(status=ep.status,error=error,request=request,actor=actor))+'\n');break
            response['role']='oracle' if oracle is not None and actor!=seat else role;ep.accept(response)
            if oracle is not None and ep.calls[-1]['valid']:oracle.observe(ep.calls[-1]['action'])
            log.write(json.dumps(ep.calls[-1])+'\n');log.flush()
    scores=[]
    for focal in range(ep.rules.spec.n_players) if shared else (seat,):
        bounds=prefix_bounds(reset['raw']['game'],ep.node.state.snapshot_commitments(),ep.world[focal])
        if ep.terminal is not None:bounds.update(lower=ep.terminal[focal],upper=ep.terminal[focal])
        calls=[c for c in ep.calls if c['player']==focal]
        scores.append(dict(trajectory_id=tid,shared_trajectory=shared,case_id=reset['id'],focal_seat=focal,replica=replica,
            split=reset['evaluation_split'],structure_family=reset['structure_family'],status=ep.status,error=error,
            mode='binary' if reset['raw']['game']['goals'][0]['binary'] else 'linear',
            focal_utility=None if ep.terminal is None else ep.terminal[focal],utilities=ep.terminal,
            total_utility=None if ep.terminal is None else sum(ep.terminal),
            missing_utility_bounds=None if error else bounds,last_commitments=ep.node.state.snapshot_commitments(),
            stopped_by_player=ep.calls[-1]['player'] if ep.status in ('invalid_action','truncated_response') else None,
            focal_failure_types=failures(calls),opponent_failure_types=failures([c for c in ep.calls if c['player']!=focal]),
            focal_calls=len(calls),focal_invalid_calls=sum(not c['valid'] for c in calls),
            focal_truncated_calls=sum(c['completion']['finish_reason']=='length' for c in calls),
            opponent_invalid_calls=sum(not c['valid'] for c in ep.calls if c['player']!=focal)))
    (folder/'results.json').write_text(json.dumps(scores,indent=2)+'\n')
    return scores
