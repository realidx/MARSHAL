"""Outcome-only full-game rollout and HTTP smoke test. No optimizer imports.

Reuse native state transitions, the current reset bank and the existing vLLM
HTTP client. Each player receives only its complete observable history; model
reasoning is never shared with other players. Results are INTERNAL artifacts.
"""
from pathlib import Path
import argparse,copy,json,os,time,uuid,hashlib,threading
from itertools import cycle
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from collections import Counter
import numpy as np
from curriculum import HERE,OutcomeRules,Investigate,safe_observation,dump,sha
from benac_p.endgame_diagnose import decode_action
from methods.vllm_client import OpenAICompatibleNegotiationClient

import selfplay_prompt as readable
VERSION='outcome-full-game-rollout-v3'
LEGACY_SYSTEM='''Play the negotiation game as the indicated player. Maximize only your own final utility.
WANT=+1, NEUTRAL=0, AVOID=-1. At the actual game end, utility is the sum of your preference values times each goal completion. Binary goals need all requirements; linear goals score the fraction committed. No intermediate reward.
Commitments are irreversible. OFFER contains complete target vectors, not increments; each party can add at most max_changes commitments. It executes only if accepted. PASS, a resolved offer, or INVESTIGATE consumes one proposal turn. Responses use no additional proposal turn.
Each player can investigate once per game: actor and query target are public, but only the investigator receives the answer. Other players' reasoning and private answers are not visible to you. Your observation includes all public history and your own private results. The public generation rule is common knowledge.
Briefly reason if useful, then call submit_action exactly once with one exact legal native action from your observation. Do not output MENU, beliefs as a separate task, or additional actions.'''
SYSTEM=LEGACY_SYSTEM.replace('Maximize only your own final utility.','Maximize your own final utility plus the protocol score described below.')+"""
Read the explicit_state field before deciding. All IDs are zero-based. A commitment vector is a BIT VECTOR: [1,0] means action_0 is committed and action_1 is NOT committed. [0] means no commitment; it does not mean action_0 is committed.
For a LINEAR goal requiring 3 commitments, 1 met requirement gives completion 1/3 and 2 gives 2/3. It does NOT require all 3 to score. A BINARY goal scores zero until all requirements are met.
max_changes applies SEPARATELY to each party, on EACH accepted offer. With max_changes=1, an offer may add one proposer commitment AND one partner commitment. This is not a lifetime limit and not a one-addition total limit. Existing commitments stay set.
Only the current proposal schedule determines remaining turns. Investigation quota is per player, not shared; inspect YOUR remaining quota. Never infer that PASS is the only action if other legal_actions are listed.
Use a short explanation, preferably at most 3 sentences, then make the ACTUAL submit_action function call. Text resembling a function call is not a tool call. Its arguments wrap the native action, for example {"action":{"action":"PASS"}}. Do not repeat analysis or introduce rules not stated here.
"""
RETRY='Your response did not complete one valid tool call. The game state is unchanged. Briefly finish and make the actual submit_action call; arguments must contain an action object from legal_actions.'

def render_observation(obs):
    result=copy.deepcopy(obs);state=obs['public_state'];game=obs['game'];bits=state['commitments'];p=obs['player']
    goals=[]
    for g in game['goals']:
        required=g['required_actions'];met=sum(bits[a['player_id']][a['action_id']] for a in required)
        goals.append(dict(goal_id=g['goal_id'],completion_type='BINARY_ALL_REQUIRED' if g.get('binary',True) else 'LINEAR_FRACTION',met_requirements=met,total_requirements=len(required),completion=float(met==len(required)) if g.get('binary',True) else met/len(required)))
    result['explicit_state']=dict(you=f'player_{p}',committed_actions_by_player={f'player_{q}':[f'action_{a}' for a,b in enumerate(row) if b] for q,row in enumerate(bits)},goal_completion=goals,your_investigations_remaining=state['investigation_remaining_by_player'][p],max_new_commitments_per_party_per_accepted_offer=game['max_changes'],remaining_proposers=game['round_robin'][state['turn_index']:])
    return result

def v2_system_prompt(penalty):
    return SYSTEM+f' Each invalid tool submission or output-length truncation without a completed action costs you {penalty:g}. You receive at most one retry; a successful retry does not erase the earlier cost. Network/server failures have no penalty.'

def system_prompt(penalty):
    return readable.SYSTEM+f' Each invalid tool submission or output-length truncation without a completed action costs you {penalty:g} in protocol score, recorded separately from your game utility. You receive at most one retry; a successful retry does not erase the earlier cost. Network/server failures have no penalty.'


TOOL=dict(type='function',function=dict(name='submit_action',description='Submit one native legal negotiation action.',parameters=dict(type='object',properties=dict(action=dict(type='object',description='One exact dictionary from legal_actions.')),required=['action'],additionalProperties=False)))

class OutcomeEnv:
    """Player-aware reset/observe/step boundary, independent of the 2-seat manager."""
    def __init__(self,raw,world):
        self.raw=copy.deepcopy(raw);self.rules=OutcomeRules(raw)
        self.world=tuple(tuple(r) for r in world)
        if self.world not in self.rules.worlds:raise ValueError('World outside the full public prior')
        self.reset()
    def reset(self):
        self.node=self.rules.initial();return self.observe()
    @property
    def current_player(self):return self.rules.actor(self.node)
    def observe(self,player=None):
        if player is None:player=self.current_player
        if player is None:return None
        return safe_observation(self.rules,self.node,player,self.world)
    def step(self,action):
        if self.node.state.is_terminal:raise ValueError('Episode already terminated')
        legal={dump(a.to_dict()):a for a in self.rules.actions(self.node)}
        key=dump(action)
        if key not in legal:raise ValueError('Action is not an exact native legal action')
        actor=self.current_player;self.node=self.rules.step(self.node,legal[key],realized_world=self.world)
        done=self.node.state.is_terminal
        rewards=list(self.rules.terminal_payoffs(self.node,self.world)) if done else [0.]*self.rules.spec.n_players
        return dict(actor=actor,next_player=self.current_player,done=done,rewards=rewards,observation=self.observe())

class ScriptedPolicy:
    def __call__(self,messages,observation,seed):
        actions=observation['legal_actions'];rng=np.random.default_rng(seed)
        # Exercise private queries plus ordinary proposal/response paths, without a solver.
        queries=[a for a in actions if a.get('action')=='INVESTIGATE']
        action=queries[0] if queries else actions[int(rng.integers(len(actions)))]
        return dict(action=action,content='CPU protocol probe',raw_message={'scripted_action':action},usage={},finish_reason='scripted')

class HTTPPolicy:
    def __init__(self,*,base_url,model,max_tokens=1024,temperature=.7,timeout=60,client=None):
        self.client=client or OpenAICompatibleNegotiationClient(base_url=base_url,model=model,
            api_key=os.environ.get('VLLM_API_KEY','EMPTY'),max_tokens=max_tokens,temperature=temperature,timeout=timeout)
    def __call__(self,messages,observation,seed):
        self.client.seed=seed
        tools=readable.tools_for(observation)
        r=self.client.complete_with_tools(messages,tools=tools,tool_choice='auto',parallel_tool_calls=False)
        action=None
        if len(r.tool_calls)==1:
            call=r.tool_calls[0]
            action=readable.decode_call(observation,call.name,call.arguments)
        return dict(action=action,content=r.content,raw_message=dict(r.raw_message),usage=dict(r.usage),finish_reason=r.finish_reason,request_options=dict(base_url=getattr(self.client,'base_url',None),model=getattr(self.client,'model',None),seed=seed,max_tokens=getattr(self.client,'max_tokens',None),temperature=getattr(self.client,'temperature',None),tools=tools,tool_choice='auto',parallel_tool_calls=False))

def run_episode(reset,policy,*,rollout_index=0,seed=42,max_retries=1,format_penalty=-.1,on_call=None):
    if not np.isfinite(format_penalty) or format_penalty>0:raise ValueError('Penalty must be finite and nonpositive')
    if max_retries not in (0,1):raise ValueError('At most one protocol retry')
    env=OutcomeEnv(reset['raw'],reset['realized_world']);n=env.rules.spec.n_players
    calls=[];transitions=[];players=[dict(player=p,call_indices=[],transition_indices=[],terminal_reward=None,format_penalty=0.,combined_reward=None,group_key=f"{reset['group_id']}:p{p}") for p in range(n)]
    result=dict(version=VERSION,group_id=reset['group_id'],reset_id=reset['id'],rollout_index=rollout_index,seed=seed,
        format_penalty_per_failure=format_penalty,max_retries=max_retries,raw=reset['raw'],realized_world=env.world,players=players,calls=calls,transitions=transitions,status='incomplete',terminal_rewards=None,
        training_started=False,gradient_ready=False,gradient_limitation='HTTP smoke artifacts preserve requests/responses/usage, but do not provide verified token IDs or behavior log-probs for an optimizer.')
    start=time.monotonic()
    for decision in range(2*len(env.rules.spec.round_robin)):
        actor=env.current_player;obs=env.observe();messages=[dict(role='system',content=system_prompt(format_penalty)),dict(role='user',content=readable.render(obs))]
        valid=False
        for attempt in range(max_retries+1):
            call_seed=int(np.random.SeedSequence([seed,decision,attempt]).generate_state(1)[0]);t=time.monotonic()
            record=dict(started_at_utc=datetime.now(timezone.utc).isoformat(),player=actor,decision=decision,attempt=attempt,seed=call_seed,observation=copy.deepcopy(obs),messages=copy.deepcopy(messages),valid=False)
            try:
                reply=policy(copy.deepcopy(messages),copy.deepcopy(obs),call_seed)
                record['response']=reply
                if reply.get('finish_reason')=='length':record['failure']='truncated_response'
                elif dump(reply.get('action')) not in {dump(a) for a in obs['legal_actions']}:record['failure']='invalid_action'
                else:record['valid']=True
            except Exception as exc:
                record.update(failure='client_error',error=f'{type(exc).__name__}: {exc}')
            record['finished_at_utc']=datetime.now(timezone.utc).isoformat()
            record['format_penalty']=format_penalty if record.get('failure') in ('invalid_action','truncated_response') else 0.
            players[actor]['format_penalty']+=record['format_penalty']
            record['seconds']=round(time.monotonic()-t,6);calls.append(record);players[actor]['call_indices'].append(len(calls)-1)
            if on_call:on_call(copy.deepcopy(record))
            if record['valid']:valid=True;break
            if record['failure']=='client_error':break
            # Generic protocol feedback only. No private answer, gold action, or fallback move.
            messages.append(dict(role='user',content=readable.RETRY))
        if not valid:result['status']=record['failure'];break
        action=record['response']['action'];out=env.step(action)
        transition=dict(index=len(transitions),actor=actor,action=action,rewards=out['rewards'],done=out['done'],next_player=out['next_player'],public_state=env.node.state.public_state())
        transitions.append(transition);players[actor]['transition_indices'].append(len(transitions)-1)
        if out['done']:
            result.update(status='terminal',terminal_rewards=out['rewards'],final_commitments=env.node.state.snapshot_commitments(),private_results=env.node.state.private_results)
            for p in range(n):
                players[p]['terminal_reward']=out['rewards'][p]
                players[p]['combined_reward']=out['rewards'][p]+players[p]['format_penalty']
            break
    else:result['status']='decision_budget'
    result['seconds']=round(time.monotonic()-start,6)
    result['replay_verified']=verify_episode(result)
    return result

def verify_episode(result):
    """Reconstruct every call's information boundary and native terminal reward."""
    env=OutcomeEnv(result['raw'],result['realized_world']);transitions=iter(result['transitions'])
    legacy=result['version']=='outcome-full-game-rollout-v1'
    modern=result['version']==VERSION
    penalty=result.get('format_penalty_per_failure',0.)
    for call in result['calls']:
        assert call['player']==env.current_player and call['observation']==env.observe()
        assert call['messages'][0]==dict(role='system',content=system_prompt(penalty) if modern else LEGACY_SYSTEM if legacy else v2_system_prompt(penalty))
        assert call['messages'][1]==dict(role='user',content=readable.render(env.observe()) if modern else dump(env.observe() if legacy else render_observation(env.observe())))
        for retry in call['messages'][2:]:assert retry==dict(role='user',content=readable.RETRY if modern else 'No valid action was received. Call submit_action exactly once with one exact legal action. The game state has not changed.' if legacy else RETRY)
        if modern and 'request_options' in call.get('response',{}):
            assert call['response']['request_options']['tools']==readable.tools_for(env.observe())
        if not call['valid']:continue
        tr=next(transitions);out=env.step(call['response']['action'])
        assert tr['actor']==call['player'] and tr['action']==call['response']['action']
        assert tr['rewards']==out['rewards'] and tr['done']==out['done'] and tr['next_player']==out['next_player']
        assert tr['public_state']==env.node.state.public_state()
    assert next(transitions,None) is None
    if result['status']=='terminal':
        assert env.node.state.is_terminal
        bits=env.node.state.snapshot_commitments()
        sat=[float(all(bits[a.player_id][a.action_id] for a in g.required_actions)) if g.binary else sum(bits[a.player_id][a.action_id] for a in g.required_actions)/len(g.required_actions) for g in env.rules.spec.goals]
        expected=(np.array(env.world)@sat).tolist();assert np.allclose(result['terminal_rewards'],expected)
        assert [p['terminal_reward'] for p in result['players']]==result['terminal_rewards']
        assert list(map(list,bits))==list(map(list,result['final_commitments']))
    else:assert result['terminal_rewards'] is None and all(p['terminal_reward'] is None for p in result['players'])
    if not legacy:
        for player in result['players']:
            expected=sum(penalty for c in result['calls'] if c['player']==player['player'] and c.get('failure') in ('invalid_action','truncated_response'))
            assert np.isclose(player['format_penalty'],expected)
            if result['status']=='terminal':assert np.isclose(player['combined_reward'],player['terminal_reward']+expected)
            else:assert player['combined_reward'] is None
    return True

def select_resets(suite):
    m=json.loads((HERE/'curriculum.json').read_text());records=[]
    instances={i['id']:i for i in m['instances']}
    if suite=='smoke':ids=['cooperate_a-r2','partner_type_choice-r2','third_party_uncertainty-r2']
    else:ids=[x['id'] for x in m['instances']]
    for gid,iid in enumerate(ids):
        reset=next(r for r in m['resets'] if r['instance_id']==iid)
        records.append(dict(id=reset['id'],group_id=f'group-{gid}',raw=instances[iid]['raw'],realized_world=reset['realized_world']))
    return records

def run_batch(resets,policy_factory,*,rollouts=4,concurrency=4,seed=42,output_dir=None,metadata=None,format_penalty=-.1):
    if rollouts<1 or concurrency<1:raise ValueError('Positive rollout and concurrency counts required')
    if len({r['group_id'] for r in resets})!=len(resets):raise ValueError('Unique group IDs required')
    directory=Path(output_dir) if output_dir else None
    if directory:
        directory.mkdir(parents=True,exist_ok=False)
        paths=[Path(__file__),Path(readable.__file__),Path(readable.__file__).with_name('bp_display.py'),HERE/'curriculum.py',HERE/'outcome_rules.py',HERE.parents[1]/'third_party/negotiation_benchmark/src/methods/vllm_client.py',HERE.parents[1]/'training/b_sft/social_private_teacher.py']
        manifest=dict(version=VERSION,seed=seed,rollouts_per_group=rollouts,concurrency=concurrency,training_started=False,format_penalty_per_failure=format_penalty,metadata=metadata or {},source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},reset_hashes={r['group_id']:sha(r) for r in resets})
        (directory/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    jobs=[(i,j,r,int(np.random.SeedSequence([seed,i,j,811]).generate_state(1)[0])) for i,r in enumerate(resets) for j in range(rollouts)]
    start=time.monotonic();results=[]
    def task(i,j,reset,local_seed):
        trace=open(directory/f'group-{i}-rollout-{j}.calls.jsonl','x') if directory else None
        def record(call):
            if trace:trace.write(dump(call)+'\n');trace.flush()
        try:r=run_episode(reset,policy_factory(),rollout_index=j,seed=local_seed,format_penalty=format_penalty,on_call=record)
        finally:
            if trace:trace.close()
        if directory:(directory/f'group-{i}-rollout-{j}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
        return r
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures=[executor.submit(task,*job) for job in jobs]
        for future in as_completed(futures):
            r=future.result();results.append(r)
            if directory:print(dump(dict(group=r['group_id'],rollout=r['rollout_index'],status=r['status'],decisions=len(r['transitions']),seconds=r['seconds'])),flush=True)
    results.sort(key=lambda r:(r['group_id'],r['rollout_index']));groups=[]
    for reset in resets:
        rows=[r for r in results if r['group_id']==reset['group_id']]
        assert len(rows)==rollouts and all(sha(r['raw'])==sha(reset['raw']) and dump(r['realized_world'])==dump(reset['realized_world']) for r in rows)
        complete=all(r['status']=='terminal' for r in rows)
        groups.append(dict(group_id=reset['group_id'],complete=complete,rollouts=len(rows),players=reset['raw']['game']['n_players'],combined_returns_by_player=[[r['players'][p]['combined_reward'] for r in rows] for p in range(reset['raw']['game']['n_players'])],format_penalties_by_player=[[r['players'][p]['format_penalty'] for r in rows] for p in range(reset['raw']['game']['n_players'])],own_returns_by_player=[[r['players'][p]['terminal_reward'] for r in rows] for p in range(reset['raw']['game']['n_players'])]))
    calls=[c for r in results for c in r['calls']];elapsed=time.monotonic()-start
    summary=dict(version=VERSION,training_started=False,gradient_ready=False,groups=groups,games=len(results),statuses=dict(Counter(r['status'] for r in results)),calls=len(calls),invalid_calls=sum(not c['valid'] for c in calls),retries=sum(c['attempt']>0 for c in calls),seconds=round(elapsed,3),complete_games_per_second=sum(r['status']=='terminal' for r in results)/elapsed,completion_tokens=sum(c.get('response',{}).get('usage',{}).get('completion_tokens',0) for c in calls),all_replays_verified=all(r['replay_verified'] for r in results))
    if directory:(directory/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary,results

def main():
    p=argparse.ArgumentParser();p.add_argument('--backend',choices=['scripted','http'],default='scripted');p.add_argument('--suite',choices=['smoke','all'],default='smoke');p.add_argument('--rollouts',type=int,default=4);p.add_argument('--concurrency',type=int,default=4);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--base-urls',nargs='+');p.add_argument('--base-url',default=os.environ.get('BENAC_P_VLLM_BASE_URL',os.environ.get('VLLM_BASE_URL')));p.add_argument('--model',default=os.environ.get('VLLM_MODEL'));p.add_argument('--max-tokens',type=int,default=1024);p.add_argument('--timeout',type=float,default=60);p.add_argument('--output-dir');p.add_argument('--format-penalty',type=float,default=-.1);a=p.parse_args()
    urls=a.base_urls or ([a.base_url] if a.base_url else [])
    if a.backend=='http' and (not urls or not a.model):p.error('HTTP rollout requires --base-url and --model (or corresponding environment variables)')
    output=a.output_dir or str(HERE/'rollouts'/f'{a.backend}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex[:6]}')
    local=threading.local();endpoint_cycle=cycle(urls);endpoint_lock=threading.Lock()
    def factory():
        if a.backend=='scripted':return ScriptedPolicy()
        if not hasattr(local,'url'):
            with endpoint_lock:local.url=next(endpoint_cycle)
        return HTTPPolicy(base_url=local.url,model=a.model,max_tokens=a.max_tokens,timeout=a.timeout)
    summary,_=run_batch(select_resets(a.suite),factory,rollouts=a.rollouts,concurrency=a.concurrency,seed=a.seed,output_dir=output,format_penalty=a.format_penalty,metadata=dict(backend=a.backend,model=a.model,base_urls=urls,max_tokens=a.max_tokens,timeout=a.timeout,suite=a.suite))
    print(dump(dict(output_dir=output,**summary)),flush=True)
    return 0 if all(g['complete'] for g in summary['groups']) else 2

if __name__=='__main__':raise SystemExit(main())
