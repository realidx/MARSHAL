"""Three-arm frozen-policy pilot. Native terminal rewards; no optimizer updates.

vLLM completions preserve the exact generated B token prefix when branching P.
Actions are read only from native chat message.tool_calls; no text-action fallback.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from random import Random
import re
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from training.b_sft.social_coupled_credit import NativeEpisode, fixture, normalized_utility, credits
from training.b_sft.social_presentation import present, readable_action
from training.b_sft.social_lm_eval import tool_for

VERSION = 'social-three-arm-pilot-v4'
PROMPT_VERSION = 'social-native-tools-v3'
BELIEF_STOP = '\n\n'
ARMS = ('free_outcome', 'bp_outcome', 'bp_branch')
POLICY = {
    'preferences': 'Partner preferences stay fixed. Before observing partner behavior, all catalogue combinations are equally likely.',
    'proposal': 'On its proposer turn, a partner offers to commit action_0 together with you if that offer is legal and would achieve a goal it wants without achieving a goal it avoids. Otherwise it passes. It only proposes to you.',
    'response': 'A partner accepts an offer only if it would newly achieve a goal it wants without newly achieving a goal it avoids. Otherwise it rejects. It responds to the offer itself, without planning future turns.',
    'history': 'Setup events are imposed independently of preferences. Partner events follow the stated behavior. Your earlier responses are your own choices; do not interpret them using the partner behavior rule.'}
RULES = '''You are the player identified in the input. Choose an available action that helps achieve your wanted goals while avoiding unwanted outcomes.
A goal is achieved only when all of its required actions are committed. Want, neutral, and avoid describe a player's attitude to the whole goal. Goal requirements do not reveal anyone's preferences. own_preferences belongs only to the identified player; each catalogue belongs to its named player.
Offers describe the complete commitments both parties would have after acceptance. A pending offer has not changed commitments. Acceptance makes commitments binding; rejection leaves them unchanged. PASS or resolving an offer consumes the current proposer turn. Resolving the last turn ends the game.
Use the observed partner behavior to judge what the partners want and how they may respond. Keep uncertainty where the evidence is insufficient. Use qualitative judgments about goals and responses. Do not calculate utility, scores, or expected values.
Give only the key grounds for your choice, in at most 120 words of reasoning. Do not restate the rules, catalogues, or action list. Do not enumerate every candidate or write a step-by-step calculation. Use plain prose without headings, lists, or tables.
After your explanation, call SUBMIT_ACTION exactly once. Submit the complete chosen object from legal_actions directly as its arguments, including all fields. Do not submit a list position or action_index. Complete the explanation and tool call together within 1024 tokens.'''
FORMATS = {
    'free': 'Briefly explain the grounds for your choice in your own way. Then use the provided SUBMIT_ACTION tool, with the complete selected legal action object as its arguments.',
    'bp': 'Use two short paragraphs. In the first, state what you infer about the partners from their behavior, including what remains uncertain. After a blank line, write the second paragraph explaining which action you choose and why those partner judgments support it. Start directly with your actual judgment; use no section labels. Then use the provided SUBMIT_ACTION tool, with the complete selected legal action object as its arguments.'}



def canonical(x):
    return json.dumps(x, sort_keys=True, allow_nan=False)


def partner(env, world, rng):
    actor = env.rules.actor(env.node)
    legal = [a.to_dict() for a in env.rules.actions(env.node)]
    before = sum(v*s for v,s in zip(world[actor], env.node.state.goal_satisfaction()))
    if env.node.pending is None:
        candidate = dict(action='OFFER', partner_id=env.raw['ego'], proposer_action=[1], partner_action=[1])
        fallback = dict(action='PASS')
    else:
        candidate = dict(response='ACCEPT'); fallback = dict(response='REJECT')
    if candidate in legal:
        a = next(a for a in env.rules.actions(env.node) if a.to_dict() == candidate)
        child = env.rules._apply(env.node, a)
        after = sum(v*s for v,s in zip(world[actor], child.state.goal_satisfaction()))
        # At proposal time, _apply installs a pending offer; evaluate acceptance.
        if child.pending is not None:
            accept = next(a for a in env.rules.actions(child) if a.to_dict() == {'response':'ACCEPT'})
            child = env.rules._apply(child, accept)
            after = sum(v*s for v,s in zip(world[actor], child.state.goal_satisfaction()))
        if after > before:
            return candidate
    return fallback


def cases():
    """Tiny diagnostic set, deliberately not a generalization/training corpus."""
    raw, imposed = fixture(); base = NativeEpisode(raw, [])
    result = []
    for target in (1, 2):
        world = next(w for w in base.worlds if w[1][0] == (1 if target == 1 else -1)
                     and w[2][1] == (1 if target == 2 else -1))
        env = NativeEpisode(raw, [])
        while env.node.state.turn_index < 2:
            move = ({'response':'REJECT'} if env.rules.actor(env.node) == raw['ego']
                    else partner(env, world, Random(0)))
            env.step(move)
        # Determine history-compatible worlds by replaying the actual declared
        # behavioral policy, not the old shared solver or private labels.
        compatible = []
        for w in base.worlds:
            check = NativeEpisode(raw, []); ok = True
            for action in env.history:
                if check.rules.actor(check.node) != raw['ego'] and partner(check,w,Random(0)) != action:
                    ok = False; break
                check.step(action)
            if ok: compatible.append(w)
        result.append(dict(id=f'evidence_partner_{target}', raw=deepcopy(raw), prefix=env.history,
                           setup_length=0, worlds=compatible, kind='informative'))
    result.append(dict(id='no_evidence', raw=raw, prefix=imposed, setup_length=2,
                       worlds=base.worlds, kind='uncertainty_control'))
    return result


def expanded_cases():
    """Seven diagnostic cases: paired evidence, uncertainty, response, two-round games."""
    result=cases()
    for wanted in (True,False):
        raw,_=fixture()
        raw['game']['round_robin']=[2,0,1]
        raw['own_preferences']=[1 if wanted else -1,1,0]
        raw['type_catalogues']['0']=[raw['own_preferences']]
        prefix=[{'action':'PASS'},{'action':'PASS'},
                dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1])]
        env=NativeEpisode(raw,prefix)
        worlds=[w for w in env.worlds if w[1][0]==1]
        result.append(dict(id='response_'+('wanted' if wanted else 'avoided'),raw=raw,
                           prefix=prefix,setup_length=2,worlds=worlds,kind='terminal_response'))
    for original in cases()[:2]:
        case=deepcopy(original)
        case['id']='two_round_'+original['id']
        case['kind']='multi_decision'
        case['raw']['game']['round_robin']=[1,2,0,1,2,0]
        result.append(case)
    return result


def payload(env, case, mode):
    ctx = env.visible()
    ctx['public_setup'] = {'intervention_prefix':case['prefix'][:case['setup_length']]}
    return present(ctx, 'P', FORMATS[mode], policy_description=POLICY)


def messages(env, case, mode):
    return [dict(role='system',content=RULES+'\n'+FORMATS[mode]),
            dict(role='user',content=json.dumps(payload(env,case,mode),ensure_ascii=True))]


def parse(text, shown, mode, belief_only=False, tool_calls=None):
    """Validate native tool results; ordinary text never supplies an action."""
    calls=tool_calls or []
    if belief_only:
        if calls: raise ValueError('unexpected_tool_during_B')
        if BELIEF_STOP not in text: raise ValueError('missing_B_paragraph_boundary')
        paragraph, remainder=text.split(BELIEF_STOP,1)
        if not paragraph.strip() or remainder.strip(): raise ValueError('invalid_B_paragraph_boundary')
        return None
    if len(calls)!=1: raise ValueError('expected_one_native_tool_call')
    call=calls[0]
    if call.get('type')!='function' or call.get('function',{}).get('name')!='SUBMIT_ACTION':
        raise ValueError('wrong_native_tool')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d: raise ValueError('duplicate_argument_key')
            d[k]=v
        return d
    try: action=json.loads(call['function']['arguments'],object_pairs_hook=unique)
    except (TypeError,KeyError): raise ValueError('invalid_tool_arguments') from None
    if not isinstance(action,dict):raise ValueError('action_must_be_object')
    if canonical(action) not in {canonical(a) for a in shown}:raise ValueError('action_not_in_legal_actions')
    if not text.strip():raise ValueError('missing_reasoning')
    if mode=='bp':
        paragraphs=re.split(r'\n[ \t]*\n',text.strip())
        if len(paragraphs)!=2 or any(not p.strip() for p in paragraphs):
            raise ValueError('invalid_BP_paragraph_boundary')
    return action


class VLLM:
    actual_lm = True
    def __init__(self, endpoint, model, tokenizer):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer, local_files_only=True)
        self.endpoint = endpoint.rstrip('/')+'/chat/completions'; self.model = model
        self.metadata = dict(tokenizer_path=str(tokenizer),
            tokenizer_sha256=hashlib.sha256(self.tokenizer.backend_tokenizer.to_str().encode()).hexdigest(),
            chat_template_sha256=hashlib.sha256(str(self.tokenizer.chat_template).encode()).hexdigest())
        with urlopen(endpoint.rstrip('/')+'/models', timeout=10) as response:
            models=json.load(response)['data']
        matching=[m for m in models if m['id']==model]
        if len(matching)!=1: raise ValueError('Expected exactly one served model with the requested ID')
        self.metadata['served_model']=matching[0]
    def prompt(self, msgs, tools):
        return self.tokenizer.apply_chat_template(msgs, tools=tools, tokenize=True, add_generation_prompt=True)
    def generate(self, prompt, prefix, limit, seed, stop, *, msgs, tools, **context):
        chat=deepcopy(msgs)
        body=dict(model=self.model,messages=chat,tools=tools,tool_choice='auto',parallel_tool_calls=False,
                  max_tokens=limit,temperature=0.7,top_p=1.0,seed=seed,
                  logprobs=True,top_logprobs=0,return_tokens_as_token_ids=True,
                  skip_special_tokens=False,add_special_tokens=False)
        if stop is not None:body.update(stop=[stop],include_stop_str_in_output=True)
        if prefix:
            b_text=self.tokenizer.decode(prefix,skip_special_tokens=False,clean_up_tokenization_spaces=False)
            chat.append(dict(role='assistant',content=b_text))
            # Standard continue_final_message may strip B's trailing blank line.
            # Render the already-established open assistant prefix exactly, keeping
            # native chat tools and server-side tool parsing. Never introduce a user turn.
        rendered=self.tokenizer.decode(prompt+prefix,skip_special_tokens=False,clean_up_tokenization_spaces=False)
        reconstructed=self.tokenizer.encode(rendered,add_special_tokens=False)
        if reconstructed!=prompt+prefix:
            raise RuntimeError('Chat prefix retokenization changes sampled B tokens')
        body.update(chat_template='{{ '+json.dumps(rendered)+' }}',
                    add_generation_prompt=not bool(prefix),continue_final_message=False)
        # Verify exact server tokenization on CPU. Prompt log probabilities are
        # unnecessary and can allocate a large prefill logits buffer on this server.
        token_body={k:body[k] for k in ('model','messages','chat_template','add_generation_prompt',
                                      'continue_final_message','add_special_tokens')}
        token_url=self.endpoint.removesuffix('/chat/completions').removesuffix('/v1')+'/tokenize'
        token_request=Request(token_url,data=json.dumps(token_body).encode(),headers={'Content-Type':'application/json'})
        with urlopen(token_request,timeout=30) as response:tokenized=json.load(response)
        if tokenized['tokens']!=prompt+prefix:
            raise RuntimeError('Server prompt differs from exact B prefix')
        request=Request(self.endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=300) as response:result=json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f'vLLM HTTP {exc.code}: {exc.read().decode()[:1000]}') from exc
        choice=result['choices'][0]; logs=choice['logprobs']['content']
        ids=[int(x['token'].removeprefix('token_id:')) for x in logs]
        count=result['usage']['completion_tokens']
        if len(ids)!=count:raise RuntimeError('Incomplete generated token IDs')
        if result['usage']['prompt_tokens']!=len(prompt+prefix):
            raise RuntimeError('Chat prompt usage differs from verified tokenization')
        decoded=self.tokenizer.decode(ids,skip_special_tokens=False,clean_up_tokenization_spaces=False)
        message=choice['message']
        return dict(text=decoded,content=message.get('content') or '',tool_calls=message.get('tool_calls') or [],
                    raw_message=message,token_ids=ids,logprobs=[x['logprob'] for x in logs],
                    finish_reason=choice['finish_reason'],usage=result['usage'],
                    prompt_verified=True,request=body)


class Scripted:
    actual_lm = False
    model = 'scripted-plumbing-control'
    def prompt(self, msgs, tools): return list(json.dumps({'messages':msgs,'tools':tools}).encode())
    def generate(self, prompt, prefix, limit, seed, stop, *, visible, mode, **context):
        target = next((e['actor'] for e in visible['history']
                       if e['kind']=='partner' and e['action'].get('action')=='OFFER'),1)
        b = f'Partner {target} may accept; its observed proposal is evidence when available.\n\n'
        candidates = [a for a in visible['legal_actions'] if a.get('partner_id')==target
                      and a.get('proposer_committed_action_ids')==['action_0']
                      and a.get('responder_committed_action_ids')==['action_0']]
        if 'response' in visible['legal_actions'][0]:
            action=next(a for a in visible['legal_actions'] if a['response']==('ACCEPT' if seed%2 else 'REJECT'))
        else:
            action = candidates[0] if candidates and seed%2 else next(a for a in visible['legal_actions'] if a.get('action')=='PASS')
        tail = 'This proposal can achieve a wanted goal with a willing partner. '
        text = b if stop==BELIEF_STOP else (('' if prefix else b) if mode=='bp' else '')+tail
        calls=[] if stop==BELIEF_STOP else [dict(type='function',function=dict(name='SUBMIT_ACTION',arguments=json.dumps(action)))]
        ids = list(text.encode())
        return dict(text=text,content=text,tool_calls=calls,token_ids=ids,logprobs=[0.0]*len(ids),finish_reason='stop',
                    usage=dict(prompt_tokens=len(prompt)+len(prefix),completion_tokens=len(ids)))


class Policy:
    def __init__(self, backend, emit): self.backend=backend; self.emit=emit; self.calls=[]
    def draw(self, env, case, mode, seed, *, belief=None, belief_only=False):
        msgs=messages(env,case,mode)
        visible=payload(env,case,mode);tools=[tool_for('P',visible)]
        prompt=self.backend.prompt(msgs,tools)
        prefix=[] if belief is None else belief['token_ids']
        prefix_text='' if belief is None else belief['text']
        visible=payload(env,case,mode)
        limit=1024-len(prefix)
        last=None
        # One retry per complete B/P path, including a retry already used on B.
        remaining_retries=1-(0 if belief is None else belief['retry'])
        for retry in range(remaining_retries+1):
            record=dict(prompt_version=PROMPT_VERSION,case=case['id'], mode=mode, seed=seed+retry*1000000, retry=retry,
                        history_length=len(env.history),phase='response' if env.node.pending else 'proposal',
                        prompt_ids=prompt+prefix, max_tokens=limit, stage='B' if belief_only else 'P' if belief else 'joint')
            start=time.monotonic()
            try:
                if limit<=0: raise ValueError('truncation')
                generated=self.backend.generate(prompt,prefix,limit,record['seed'],
                    BELIEF_STOP if belief_only else None,visible=visible,mode=mode,msgs=msgs,tools=tools)
                record.update(generated)
                if generated['finish_reason']=='length' or len(generated['token_ids'])>limit:
                    raise ValueError('truncation')
                reasoning=generated['text'] if belief_only else prefix_text+generated.get('content','')
                answer=parse(reasoning,visible['legal_actions'],mode,belief_only,generated.get('tool_calls'))
                record.update(status='ok',answer=answer,failure_reward=0)
            except ValueError as exc:
                status='truncation' if str(exc)=='truncation' else 'format_failure'
                record.update(status=status,answer=None,failure_reward=-1,validation_error=str(exc))
            except Exception as exc:
                record.update(status='infrastructure_failure',answer=None,failure_reward=None,error_type=type(exc).__name__)
                if isinstance(exc,RuntimeError):record['interface_error']=str(exc)
            record['seconds']=time.monotonic()-start
            record['call_id']=len(self.calls);self.calls.append(record);self.emit('calls',record)
            last=record
            print(f"CALL {record['call_id']} {case['id']} {record['stage']} retry={retry} "
                  f"{record['status']} tokens={len(record.get('token_ids',[]))}/{limit}"
                  f"{(' reason='+record['validation_error']) if 'validation_error' in record else ''}", flush=True)
            if record['status']=='ok': return record
        return last


def rollout(case, world, action, policy, mode, seed):
    env=NativeEpisode(case['raw'],case['prefix']); future=[]
    if action is None: return dict(started=False,terminal=False,reward=None,history=env.history,future_calls=future)
    try:
        shown=payload(env,case,mode)['legal_actions']
        native=next(a for a,s in zip(env.visible()['legal_actions'],shown) if canonical(s)==canonical(action))
        env.step(native); rng=Random(seed)
        while not env.node.state.is_terminal:
            if env.rules.actor(env.node)==env.raw['ego']:
                draw=policy.draw(env,case,mode,rng.randrange(2**30));future.append(draw['call_id'])
                if draw['status']!='ok': return dict(started=True,terminal=False,reward=None,history=env.history,future_calls=future)
                shown=payload(env,case,mode)['legal_actions']
                action=next(a for a,s in zip(env.visible()['legal_actions'],shown) if canonical(s)==canonical(draw['answer']))
            else: action=partner(env,world,rng)
            env.step(action)
        utility=env.payoff(world)[env.raw['ego']]
        return dict(started=True,terminal=True,reward=normalized_utility(utility,env.raw['own_preferences']),
                    utility=utility,history=env.history,future_calls=future)
    except (ValueError,StopIteration) as exc:
        return dict(started=True,terminal=False,reward=None,history=env.history,error_type=type(exc).__name__,future_calls=future)


def run(out, backend, blocks=1, seed=7, *, arms=ARMS, pack_name='smoke'):
    if blocks<1: raise ValueError('Positive blocks required')
    if not arms or len(set(arms))!=len(arms) or any(a not in ARMS for a in arms):
        raise ValueError('Select distinct known arms')
    if pack_name not in ('smoke','expanded'):raise ValueError('Unknown pack')
    out.mkdir(parents=True,exist_ok=False)
    pack=cases() if pack_name=='smoke' else expanded_cases(); encoded=json.dumps(pack,sort_keys=True)
    # Every case gets exactly K*J*W environment slots per block per arm.
    expected=blocks*sum(4*len(c['worlds']) for c in pack)
    config=dict(version=VERSION,prompt_version=PROMPT_VERSION,model=backend.model,actual_LM=backend.actual_lm,
                optimizer_updates=0,k=2,j=2,blocks=blocks,seed=seed,max_output_tokens=1024,retries=1,
                rollout_slots_per_arm=expected,case_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                purpose='Frozen-policy sampling/credit pilot; not a trained-method comparison',
                budget_unit='One attempted native continuation per root action and hidden world; failed slots are spent',
                output_protocol='Native /chat/completions with SUBMIT_ACTION; action read only from message.tool_calls',
                token_units='model tokens' if backend.actual_lm else 'UTF-8 bytes (scripted control only)')
    config['selected_arms']=list(arms);config['pack']=pack_name
    config['backend_metadata']=getattr(backend,'metadata',{})
    config['source_sha256']={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                            for name in ('social_three_arm.py','social_coupled_credit.py',
                                         'social_presentation.py','shared_teacher.py','catalogues.py')}
    (out/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(pack,indent=2)+'\n')
    results={}
    for arm in arms:
        def emit(name,row):
            with (out/f'{arm}_{name}.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
        policy=Policy(backend,emit); slots=[]; signals=[]
        mode='free' if arm=='free_outcome' else 'bp'
        for block in range(blocks):
            for ci,case in enumerate(pack):
                root=NativeEpisode(case['raw'],case['prefix']); draws=[]; bs=[]; matrix=[]
                for bi in range(2):
                    b=(policy.draw(root,case,mode,seed+block*10000+ci*100+bi,belief_only=True)
                       if arm=='bp_branch' else None)
                    bs.append(b); row=[]
                    for pi in range(2):
                        draw_seed=seed+block*10000+ci*100+pi+(0 if arm=='bp_branch' else bi*2)
                        draw=(None if b and b['status']!='ok' else
                              policy.draw(root,case,mode,draw_seed,belief=b))
                        draws.append(draw); outcomes=[]
                        for wi,world in enumerate(case['worlds']):
                            outcome=rollout(case,world,None if draw is None else draw['answer'],policy,mode,
                                           seed+block*10000+ci*100+wi)
                            outcome.update(case=case['id'],block=block,B_index=bi,P_index=pi,world_index=wi)
                            slots.append(outcome);outcomes.append(outcome);emit('rollouts',outcome)
                        mean=(sum(o['reward'] for o in outcomes)/len(outcomes)
                              if all(o['reward'] is not None for o in outcomes) else None)
                        row.append(mean)
                    matrix.append(row)
                c=credits(matrix) if arm=='bp_branch' else None
                # Diagnostic records only. No token mask/advantage exported as PPO-ready.
                sig=dict(case=case['id'],block=block,outcome_matrix=matrix,credit=c,
                         distinct_B=len({b['text'].strip() for b in bs if b and b['status']=='ok'}),
                         distinct_actions=len({canonical(d['answer']) for d in draws if d and d['status']=='ok'}),
                         root_call_ids=[None if d is None else d['call_id'] for d in draws],
                         B_call_ids=[None if b is None else b['call_id'] for b in bs],
                         outcome_scope='Each successful full trace in outcome arms shares its terminal return; branch arm contrasts root B and P only.',
                         training_ready=False)
                signals.append(sig);emit('signals',sig)
        assert len(slots)==expected
        successful=[s['reward'] for s in slots if s['terminal']]
        statuses=Counter(c['status'] for c in policy.calls)
        per_case={}
        for case in pack:
            subset=[s for s in slots if s['case']==case['id']]
            per_case[case['id']]=dict(rollout_slots=len(subset),terminal_episodes=sum(s['terminal'] for s in subset),
                mean_return=sum(s['reward'] for s in subset)/len(subset) if all(s['terminal'] for s in subset) else None)
        results[arm]=dict(rollout_slots=len(slots),started_episodes=sum(s['started'] for s in slots),terminal_episodes=len(successful),
                         multi_decision_episodes=sum(bool(s['future_calls']) for s in slots),
                         future_decision_count=sum(len(s['future_calls']) for s in slots),
                         failed_episodes=len(slots)-len(successful),
                         mean_terminal_return_complete_only=sum(successful)/len(successful) if successful else None,
                         all_slots_mean_return=sum(successful)/len(slots) if len(successful)==len(slots) else None,
                         requests=len(policy.calls),completion_tokens=sum(c.get('usage',{}).get('completion_tokens',0) for c in policy.calls),
                         prompt_tokens=sum(c.get('usage',{}).get('prompt_tokens',0) for c in policy.calls),
                         generation_seconds=sum(c['seconds'] for c in policy.calls),statuses=dict(statuses),per_case=per_case)
        print(json.dumps(dict(arm=arm,**results[arm])),flush=True)
    (out/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    return results


def preflight(out, backend, seed=7):
    """Four successful requests cover all paths; stop on the first failed path.

    Structural success still requires inspection of the actual natural prose.
    These calls are separate from experiment rollout budgets.
    """
    out.mkdir(parents=True,exist_ok=False)
    case=cases()[0];env=NativeEpisode(case['raw'],case['prefix'])
    def emit(name,row):
        with (out/f'{name}.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    policy=Policy(backend,emit)
    prompts={mode:messages(env,case,mode) for mode in ('free','bp')}
    (out/'prompts.json').write_text(json.dumps(prompts,indent=2)+'\n')
    report=dict(version=VERSION,prompt_version=PROMPT_VERSION,actual_LM=backend.actual_lm,
                model=backend.model,seed=seed,paths=[],format_passed=False,
                semantic_review_required=True,optimizer_updates=0)
    def checkpoint():
        report['requests']=len(policy.calls)
        (out/'preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    def check(name,draw):
        report['paths'].append(dict(path=name,call_id=draw['call_id'],status=draw['status']))
        checkpoint()
        if draw['status']!='ok':
            raise RuntimeError(f'Preflight failed at {name}; inspect calls.jsonl before any full run')
    for mode in ('free','bp'):
        check(mode+'_joint',policy.draw(env,case,mode,seed))
    b=policy.draw(env,case,'bp',seed,belief_only=True);check('branch_B',b)
    check('branch_P',policy.draw(env,case,'bp',seed,belief=b))
    report['format_passed']=True;checkpoint()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--blocks',type=int,default=1)
    p.add_argument('--seed',type=int,default=7);p.add_argument('--scripted',action='store_true')
    p.add_argument('--endpoint',default='http://127.0.0.1:8000/v1');p.add_argument('--model',default='social-base')
    p.add_argument('--arm',choices=('all',)+ARMS,default='all',help='Run one arm on this endpoint, or all arms sequentially')
    p.add_argument('--pack',choices=('smoke','expanded'),default='smoke')
    p.add_argument('--preflight',action='store_true',help='Check three generation paths, stopping on failure; no full experiment')
    p.add_argument('--tokenizer');a=p.parse_args()
    if not a.scripted and not a.tokenizer:p.error('--tokenizer local path is required for exact prompt tokens')
    backend=Scripted() if a.scripted else VLLM(a.endpoint,a.model,a.tokenizer)
    if a.preflight:preflight(a.output,backend,a.seed)
    else:run(a.output,backend,a.blocks,a.seed,arms=ARMS if a.arm=='all' else (a.arm,),pack_name=a.pack)


if __name__=='__main__': main()
