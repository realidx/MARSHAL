"""CPU-safe online training contract for selected terminal slices.

Same-context candidate groups, continuous oracle regret and node-local GRPO.
Only a uniformly selected original candidate advances the native environment.
"""
from copy import deepcopy
import json
import math
import time
from pathlib import Path

import numpy as np
from .common import decode, digest, file_hash, seed_for
from .terminal_analysis import visible_posterior
from .terminal_candidates import sample_member_world
from .terminal_d import TerminalRollout, load_dataset
from .values import extreme_value

VERSION='terminal-node-regret-grpo-v5'
PROTOCOL_PENALTY=0.2
ORACLE_EPSILON=1e-7
STD_EPSILON=1e-8
CONTRACT=dict(version=VERSION,
    reward='Legal Q-max(Q); invalid/truncated min(Q)-max(Q), over ALL legal actions, native utility scale.',
    epsilon=ORACLE_EPSILON,std_epsilon=STD_EPSILON,std_correction=1,
    baseline='Within the SAME actual node: (reward-mean)/(sample_std+1e-8); range <= oracle epsilon has zero task advantage.',
    weighting='Node groups equal; candidates equal; response tokens averaged. No inverse chain-length weight.',
    failure='Separate protocol advantage=-0.2 on failed calls only; selected failure terminates without retry.',
    protocol_penalty=PROTOCOL_PENALTY,
    batching='Target actual node groups, including zero-signal groups; stop admissions at target and finish admitted chains; one update, one pass.',
    reset='One entrance/world/focal per chain; all candidates at a node share prompt, posterior and remaining k.',
    continuation='Uniform original candidate, duplicates retained, score-independent; saved terminal reference advances partners and focal after k.',
    objective='On-policy sampled-context oracle action-value surrogate; not a terminal-return policy-gradient estimator.',
    infrastructure='Transport, context, missing behavior evidence and oracle failures abort collection without committing cursor.')


def ensure(ok,message):
    if not ok:raise ValueError(message)


class TrainingData:
    def __init__(self,pool,selection):
        self.pool=load_dataset(pool);self.selection=Path(selection)
        complete=json.loads((self.selection/'COMPLETE.json').read_text())
        for name,sha in complete['files'].items():
            ensure(file_hash(self.selection/name)==sha,'Selection file changed: '+name)
        selected=json.loads((self.selection/'SELECTION.json').read_text())
        ensure(selected['dataset_sha256']==file_hash(self.pool.root/'manifest.json'),'Selection pool changed')
        self.train=[json.loads(x) for x in (self.selection/'candidates.jsonl').read_text().splitlines()]
        by_id={r['id']:r for r in self.pool.candidates}
        ensure(len(self.train)==100 and len({r['id'] for r in self.train})==100,'Expected 100 selected train questions')
        ensure(all(r==by_id.get(r['id']) and r['split']=='train' for r in self.train),'Selected question changed or held-out leak')
        self.validation=[r for r in self.pool.candidates if r['split']=='validation']
        self.test=[r for r in self.pool.candidates if r['split']=='test']
        self.parents=self.pool.parents
        self.sha=digest(dict(pool=file_hash(self.pool.root/'manifest.json'),selection=file_hash(self.selection/'COMPLETE.json')))
        self.cache={}
    def reference(self,row):
        tree=self.pool.reference(row)
        # Q tables are only useful while their corresponding reference is cached.
        self.cache={key:value for key,value in self.cache.items() if key in self.pool.cache}
        return tree,self.cache.setdefault(row['reference_id'],{})


class StepRollout(TerminalRollout):
    def __init__(self,tree,row,replica,group_seed,reset,epsilon=1e-7,cache=None):
        # TerminalRollout draws deterministically from a row. Make a local
        # sampling-only view to force the shared reset without changing beliefs
        # or the question/value record used to score decisions.
        forced=deepcopy(row);member_index,world_index=reset
        original=row['members'][member_index]
        member=deepcopy(original);weights=[0.]*len(member['world_weights']);weights[world_index]=1.
        member.update(probability=1.,world_weights=weights,joint_world_masses=weights)
        forced.update(members=[member],V_star=member['V_star'],V_min=member['V_min'],C_span=member['C_span'])
        super().__init__(tree,forced,replica,group_seed)
        self.row=row;self.member=original;self.member_index=member_index
        ensure(self.world_index==world_index,'Shared reset mismatch')
        self.reach=np.asarray(original['world_weights'],dtype=float).copy()
        self.q_cache=cache if cache is not None else {}
        self.epsilon=epsilon;self.step_rewards=[];self.step_details=[]

    def action_values(self):
        weights=visible_posterior(self.tree,self.index,self.ego,self.reach,self.world_index)
        if not self.calls:return np.asarray(self.member['root_Q']),weights
        remaining=self.row['k']-self.controlled
        key=(self.ego,self.index,remaining,tuple(weights))
        if key not in self.q_cache:
            self.q_cache[key]=extreme_value(self.tree,self.ego,self.index,weights,remaining)['root_Q']
        return np.asarray(self.q_cache[key]),weights

    def accept(self,output,req):
        q,weights=self.action_values();before=len(self.steps)
        super().accept(output,req)
        call=self.calls[-1];ai=call['action_index'];valid=call['protocol_status']=='ok'
        gap=float(q.max()-q[ai]) if valid else None
        reward=int(valid and gap<=self.epsilon)
        self.step_rewards.append(reward)
        self.step_details.append(dict(reward=reward,gap=gap,Q=q.tolist(),posterior=weights.tolist(),
            optimal_indices=np.flatnonzero(q.max()-q<=self.epsilon).tolist()))
        for step in self.steps[before:]:
            if step['source']=='saved-reference':self.reach*=self.tree.policy[step['node']][step['action_index']]
        ensure(self.reach[self.world_index]>0,'Impossible saved-reference continuation')


def group_advantages(rewards):
    """Sample std as in the original GRPO implementation; oracle ties stay zero."""
    values=np.asarray(rewards,dtype=float)
    ensure(values.ndim==1 and len(values)>=2 and np.isfinite(values).all(),'Need >=2 finite node rewards')
    mean=float(values.mean());std=float(values.std(ddof=1))
    advantages=np.zeros_like(values) if np.ptp(values)<=ORACLE_EPSILON else (values-mean)/(std+STD_EPSILON)
    return advantages.tolist(),mean,std


def check_output(out,cfg):
    if out.get('completion',{}).get('status')=='infrastructure_failure':
        raise RuntimeError('Infrastructure failure is not a model reward')
    ids=out.get('response_ids');logps=out.get('behavior_log_probs')
    ensure(bool(out.get('prompt_ids')) and bool(ids) and logps is not None and len(ids)==len(logps)
        and len(ids)<=cfg['max_tokens'] and all(math.isfinite(p) for p in logps),'Missing/invalid behavior token evidence')


def score_response(job,out,req,q,posterior):
    """Score without executing, changing posterior, or sampling a continuation."""
    check_output(out,dict(max_tokens=req['max_tokens']))
    ai,status=decode(out,job.tree.rules.actions(job.node))
    valid=status=='ok';gap=float(q.max()-q[ai]) if valid else None
    reward=float(q[ai]-q.max()) if valid else float(q.min()-q.max())
    detail=dict(reward=int(valid and gap<=ORACLE_EPSILON),gap=gap,Q=q.tolist(),posterior=posterior.tolist(),
        optimal_indices=np.flatnonzero(q.max()-q<=ORACLE_EPSILON).tolist())
    return dict(out,request=req,node=job.index,action_index=ai,protocol_status=status,
        prompt_sha256=digest({k:req[k] for k in ('messages','tools')}),
        first_action_oracle_gap=float(job.member['V_star']-job.member['root_Q'][ai]) if not job.calls and valid else None,
        binary_reward=detail['reward'],
        oracle_step=detail,task_reward=reward,valid=valid,protocol_failure=None if valid else status)


def execute(jobs,generate,cfg,concurrency):
    # Native ROLL generation returns behavior tokens/logprobs as one batch.
    # Do not call its mutable tokenizer/actor dispatch concurrently via HTTP threads.
    while any(j.status=='running' for j in jobs):
        ready=[j for j in jobs if j.status=='running']
        for offset in range(0,len(ready),concurrency):
            active=ready[offset:offset+concurrency];requests=[j.request(cfg) for j in active]
            outputs=generate(requests)
            ensure(len(outputs)==len(active),'Missing native generation output')
            for job,out,req in zip(active,outputs,requests):
                check_output(out,cfg)
                job.accept(out,req)


class Collector:
    def __init__(self,data,generate,seed=42,replicas=8,concurrency=32,max_tokens=1024,context=16384,node_groups_per_update=20):
        ensure(replicas>=2 and concurrency>=1 and 0<max_tokens<context,'Invalid training limits')
        ensure(type(node_groups_per_update) is int and node_groups_per_update>=1,'Invalid node groups per update')
        self.node_groups_per_update=node_groups_per_update
        self.dataset,self.generate=data,generate
        self.replicas,self.concurrency=replicas,concurrency
        self.cfg=dict(seed=seed,replicas=replicas,workers=concurrency,max_tokens=max_tokens,context=context,
            temperature=1.,top_p=1.,top_k=-1,repetition_penalty=1.)
        self.state=dict(version=VERSION,dataset_sha256=data.sha,seed=seed,replicas=replicas,
            node_groups_per_update=node_groups_per_update,
            config=self.cfg,contract=CONTRACT,cursor=0,consumed=0,exposure={},step=0)
    def restore(self,state):
        for key in ('version','dataset_sha256','seed','replicas','node_groups_per_update','config','contract'):
            ensure(state.get(key)==self.state[key],'Collector resume contract changed: '+key)
        self.state=deepcopy(state)
    def collect(self,step,arm,token_target=1,validation=False):
        ensure(arm=='slices' and not validation and token_target>0 and step==self.state['step'],'Invalid terminal collection request')
        started=time.perf_counter();oracle_seconds=generation_seconds=0.
        working=deepcopy(self.state);rows=[];units=[];games=[];active=[]
        # Reserve every admitted chain's remaining k. Even if all survive, total
        # groups overshoot by at most max(k)-1, independently of concurrency.
        capacity=max(1,self.concurrency//self.replicas)
        while len(units)<self.node_groups_per_update or active:
            reserved=len(units)+sum(j.row['k']-j.controlled for _,j,_,_ in active)
            while len(active)<capacity and reserved<self.node_groups_per_update:
                cursor=working['cursor'];cycle,offset=divmod(cursor,len(self.dataset.train))
                order=np.random.default_rng(seed_for(self.cfg['seed'],'terminal-train-order',cycle)).permutation(len(self.dataset.train))
                row=self.dataset.train[int(order[offset])];tree,cache=self.dataset.reference(row)
                reset_seed=seed_for(self.cfg['seed'],'terminal-train-reset',cursor)
                reset=sample_member_world(row,np.random.default_rng(reset_seed))
                job=StepRollout(tree,row,0,seed_for(self.cfg['seed'],'terminal-train-chain',cursor),reset,cache=cache)
                active.append((cursor,job,reset_seed,[]));working['cursor']+=1;reserved+=row['k']
            requests=[];contexts=[]
            for cursor,job,reset_seed,history in active:
                depth=len(job.calls);before=time.perf_counter();q,posterior=job.action_values()
                oracle_seconds+=time.perf_counter()-before
                ensure(len(q)>0 and np.isfinite(q).all(),'Invalid oracle action values')
                group=f'node:{cursor}:{job.row["id"]}:{depth}'
                req=job.request(self.cfg)
                candidates=[dict(req,seed=seed_for(self.cfg['seed'],'terminal-train-candidate',cursor,depth,r)) for r in range(self.replicas)]
                contexts.append((cursor,job,reset_seed,history,group,q,posterior,candidates))
                requests.extend(candidates)
            outputs=[]
            for offset in range(0,len(requests),self.concurrency):
                chunk=requests[offset:offset+self.concurrency];before=time.perf_counter();received=self.generate(chunk)
                generation_seconds+=time.perf_counter()-before
                ensure(len(received)==len(chunk),'Missing native generation output')
                for out in received:check_output(out,self.cfg)
                outputs.extend(received)
            still_active=[]
            for index,(cursor,job,reset_seed,history,group,q,posterior,candidates) in enumerate(contexts):
                row=job.row;depth=len(job.calls);chain=f'chain:{cursor}:{row["id"]}'
                outs=outputs[index*self.replicas:(index+1)*self.replicas]
                calls=[score_response(job,out,req,q,posterior) for out,req in zip(outs,candidates)]
                ensure(len({c['prompt_sha256'] for c in calls})==1,'Node candidates have different prompts')
                ensure(all(c['prompt_ids']==calls[0]['prompt_ids'] for c in calls),'Node candidate prompt tokens differ')
                advs,mean,std=group_advantages([c['task_reward'] for c in calls])
                # A separate, deterministic RNG, independent of rewards and model
                # sampling: duplicates have their original sampling multiplicity.
                chosen=int(np.random.default_rng(seed_for(self.cfg['seed'],'terminal-train-advance',cursor,depth)).integers(self.replicas))
                scoring_sha=digest(dict(prompt=calls[0]['prompt_sha256'],reference_id=row['reference_id'],
                    node=job.index,player=job.ego,remaining_k=row['k']-depth,posterior=posterior.tolist(),Q=q.tolist()))
                for replica,(call,adv) in enumerate(zip(calls,advs)):
                    protocol=0. if call['valid'] else -PROTOCOL_PENALTY
                    call.update(kind='slices',task_id=row['id'],parent_id=row['parent_id'],group=group,chain=chain,
                        cursor=cursor,unit=f'{group}:r{replica}',replica=replica,player=row['ego'],decision_index=depth,
                        remaining_k=row['k']-depth,scoring_sha256=scoring_sha,selected_for_continuation=replica==chosen,
                        reward_mean=mean,reward_std=std,task_advantage=adv,protocol_advantage=protocol,advantage=adv+protocol,
                        task_denominator=0.,loss_weight=1.,task_weight=1.,protocol_weight=1.,kl_weight=1.)
                    rows.append(call)
                units.append(dict(group=group,chain=chain,cursor=cursor,decision_index=depth,slice_id=row['id'],parent_id=row['parent_id'],
                    remaining_k=row['k']-depth,selected_replica=chosen,prompt_sha256=calls[0]['prompt_sha256'],scoring_sha256=scoring_sha,
                    task_rewards=[c['task_reward'] for c in calls],reward_mean=mean,reward_std=std,
                    task_active=any(a!=0 for a in advs),protocol_active=any(not c['valid'] for c in calls),
                    binary_correct=sum(c['binary_reward'] for c in calls),
                    unique_legal_actions=len({c['action_index'] for c in calls if c['valid']}),
                    sampled_reward_range=float(np.ptp([c['task_reward'] for c in calls])),oracle_value_span=float(np.ptp(q))))
                history.append(dict(group=group,replica=chosen,task_reward=calls[chosen]['task_reward']))
                job.accept(outs[chosen],candidates[chosen])
                exposure=working['exposure'].setdefault(row['id'],dict(entries=0,node_groups=0,responses=0,completed=0))
                exposure['node_groups']+=1;exposure['responses']+=self.replicas
                if job.status=='running':still_active.append((cursor,job,reset_seed,history))
                else:
                    record=job.record();record.pop('calls')
                    record.update(chain=chain,group=chain,cursor=cursor,reset_seed=reset_seed,selected_nodes=history,step_rewards=job.step_rewards)
                    games.append(record);exposure['entries']+=1;exposure['completed']+=int(job.status=='terminal')
            active=still_active
        rows.sort(key=lambda r:(r['cursor'],r['decision_index'],r['replica']))
        units.sort(key=lambda u:(u['cursor'],u['decision_index']));games.sort(key=lambda g:g['cursor'])
        tokens=sum(len(r['response_ids']) for r in rows)
        roots=[r for r in rows if r['decision_index']==0]
        root_units=[u for u in units if u['decision_index']==0]
        info_ids={r['id'] for r in self.dataset.train if r['information_positive']}
        information=[r for r in roots if r['task_id'] in info_ids]
        working['consumed']+=tokens;working['step']+=1;self.state=working
        # Diagnostic wall times are deliberately outside deterministic sampler
        # state/results, so they cannot affect resume or candidate selection.
        self.last_timing=dict(collection_seconds=time.perf_counter()-started,
            oracle_action_value_seconds=oracle_seconds,generation_seconds=generation_seconds)
        return rows,units,games,dict(generated_tokens=tokens,rows=len(rows),groups=len(units),entry_chains=len(games),
            target_node_groups=self.node_groups_per_update,node_group_overshoot=len(units)-self.node_groups_per_update,
            active_groups=sum(u['task_active'] or u['protocol_active'] for u in units),
            task_active_groups=sum(u['task_active'] for u in units),protocol_active_groups=sum(u['protocol_active'] for u in units),
            zero_task_groups=sum(not u['task_active'] for u in units),
            single_legal_action_groups=sum(u['unique_legal_actions']==1 for u in units),
            flat_oracle_groups=sum(u['oracle_value_span']<=ORACLE_EPSILON for u in units),
            root_correct_calls=sum(r['binary_reward'] for r in roots),root_decision_calls=len(roots),
            root_reward_contrast_groups=sum(0<u['binary_correct']<self.replicas for u in root_units),
            information_positive_root_calls=len(information),information_positive_root_correct_calls=sum(r['binary_reward'] for r in information),
            binary_correct_calls=sum(r['binary_reward'] for r in rows),decision_calls=len(rows),
            mean_task_reward=float(np.mean([r['task_reward'] for r in rows])),
            legal_mean_regret=float(np.mean([r['oracle_step']['gap'] for r in rows if r['valid']])) if any(r['valid'] for r in rows) else None,
            completion_rate=sum(g['status']=='terminal' for g in games)/len(games),
            truncated_calls=sum(r['protocol_failure']=='truncated' for r in rows),
            invalid_calls=sum(r['protocol_failure']=='invalid_action' for r in rows),
            skip_optimizer=False,step_binary_reward=False,terminal_utility_used_for_training=False)


def mock_generate(requests):
    from .terminal_d import mock_generate as generate
    outputs=generate(requests)
    for req,out in zip(requests,outputs):
        # Synthetic token evidence is only for CPU plumbing; never model evidence.
        out.update(prompt_ids=[1,2],response_ids=[3,4],behavior_log_probs=[-.5,-.5],text='MOCK',finish_reason='stop')
    return outputs
