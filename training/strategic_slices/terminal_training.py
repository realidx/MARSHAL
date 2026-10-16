"""CPU-safe online training contract for selected terminal slices.

Same-context candidate groups, continuous oracle regret and node-local GRPO.
Only a uniformly selected original candidate advances the native environment.
"""
from copy import deepcopy
import json
from collections import deque
from dataclasses import dataclass
import math
import time
from pathlib import Path

import numpy as np
from .common import decode, digest, file_hash, seed_for
from .terminal_analysis import visible_posterior
from .terminal_candidates import sample_member_world
from .terminal_d import TerminalRollout, load_dataset
from .values import cached_extreme_value
from training.social_mixed.cache import ByteLRU,CacheNamespace

VERSION='terminal-node-regret-grpo-refill-v6'
PROTOCOL_PENALTY=0.2
ORACLE_EPSILON=1e-7
STD_EPSILON=1e-8
CONTRACT=dict(version=VERSION,
    scheduler='completion-refill-v1: preselect a uniform original candidate; advance when it finishes, normalize only after all 8; no length-based filtering.',
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
    def __init__(self,pool,selection,tree_cache_mb=512,oracle_cache_mb=128):
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
        ensure(tree_cache_mb>=0 and oracle_cache_mb>=0,'Cache budgets must be nonnegative')
        self.tree_cache=ByteLRU(int(tree_cache_mb*1024**2));self.oracle_cache=ByteLRU(int(oracle_cache_mb*1024**2))
        self.reference_restore_seconds=0.
    def reference(self,row):
        rid=row['reference_id'];tree=self.tree_cache.get(rid)
        if tree is None:
            before=time.perf_counter();tree=self.pool.reference(row)
            self.reference_restore_seconds+=time.perf_counter()-before
            self.tree_cache.put(rid,tree)
            # The training adapter owns retention; remove the loader's separate
            # two-entry LRU so its copies do not bypass the byte budget.
            self.pool.cache.clear()
        return tree,CacheNamespace(self.oracle_cache,rid)
    def cache_metrics(self):
        metrics=dict(reference_restore_seconds_total=self.reference_restore_seconds)
        for name,cache in (('tree_cache',self.tree_cache),('oracle_cache',self.oracle_cache)):
            metrics.update({name+'_'+k:v for k,v in cache.stats().items()})
        return metrics


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
            self.q_cache[key]=cached_extreme_value(self.tree,self.ego,self.index,weights,remaining,cache=self.q_cache)['root_Q']
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


@dataclass
class ScoreContext:
    """Small immutable scoring snapshot; discarded siblings retain no full tree."""
    actions: list
    node: int
    first: bool
    root_Q: list
    V_star: float

    @classmethod
    def capture(cls,job):
        return cls(list(job.tree.rules.actions(job.node)),job.index,not job.calls,
            job.member['root_Q'],job.member['V_star'])


def score_response(job,out,req,q,posterior):
    """Score without executing, changing posterior, or sampling a continuation."""
    check_output(out,dict(max_tokens=req['max_tokens']))
    context=job if isinstance(job,ScoreContext) else ScoreContext.capture(job)
    ai,status=decode(out,context.actions)
    valid=status=='ok';gap=float(q.max()-q[ai]) if valid else None
    reward=float(q[ai]-q.max()) if valid else float(q.min()-q.max())
    detail=dict(reward=int(valid and gap<=ORACLE_EPSILON),gap=gap,Q=q.tolist(),posterior=posterior.tolist(),
        optimal_indices=np.flatnonzero(q.max()-q<=ORACLE_EPSILON).tolist())
    return dict(out,request=req,node=context.node,action_index=ai,protocol_status=status,
        prompt_sha256=digest({k:req[k] for k in ('messages','tools')}),
        first_action_oracle_gap=float(context.V_star-context.root_Q[ai]) if context.first and valid else None,
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
    def __init__(self,data,generate,seed=42,replicas=8,concurrency=32,max_tokens=1024,context=16384,node_groups_per_update=20,stream_factory=None):
        ensure(replicas>=2 and concurrency>=1 and 0<max_tokens<context,'Invalid training limits')
        ensure(type(node_groups_per_update) is int and node_groups_per_update>=1,'Invalid node groups per update')
        self.node_groups_per_update=node_groups_per_update
        self.dataset,self.generate=data,generate
        self.stream_factory=stream_factory
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
        from training.social_mixed.native_stream import BatchStream
        working=deepcopy(self.state);rows=[];units=[];games=[]
        chains={};contexts={};ready=deque();inflight={};created=0;peak=0

        def create_node(chain):
            nonlocal oracle_seconds,created
            cursor,job=chain['cursor'],chain['job'];row=job.row;depth=len(job.calls)
            before=time.perf_counter();q,posterior=job.action_values();oracle_seconds+=time.perf_counter()-before
            ensure(len(q)>0 and np.isfinite(q).all(),'Invalid oracle action values')
            group=f'node:{cursor}:{row["id"]}:{depth}';req=job.request(self.cfg)
            candidates=[dict(req,seed=seed_for(self.cfg['seed'],'terminal-train-candidate',cursor,depth,r)) for r in range(self.replicas)]
            chosen=int(np.random.default_rng(seed_for(self.cfg['seed'],'terminal-train-advance',cursor,depth)).integers(self.replicas))
            context=dict(cursor=cursor,row=row,depth=depth,group=group,q=q,posterior=posterior,candidates=candidates,
                scoring=ScoreContext.capture(job),chosen=chosen,calls=[None]*self.replicas,received=0,
                chain=f'chain:{cursor}:{row["id"]}')
            contexts[group]=context;chain['waiting']=True;created+=1
            ready.extend((group,r) for r in range(self.replicas))

        def admit():
            cursor=working['cursor'];cycle,offset=divmod(cursor,len(self.dataset.train))
            order=np.random.default_rng(seed_for(self.cfg['seed'],'terminal-train-order',cycle)).permutation(len(self.dataset.train))
            row=self.dataset.train[int(order[offset])];tree,cache=self.dataset.reference(row)
            reset_seed=seed_for(self.cfg['seed'],'terminal-train-reset',cursor)
            reset=sample_member_world(row,np.random.default_rng(reset_seed))
            job=StepRollout(tree,row,0,seed_for(self.cfg['seed'],'terminal-train-chain',cursor),reset,cache=cache)
            chain=dict(cursor=cursor,job=job,reset_seed=reset_seed,history=[],waiting=False)
            chains[cursor]=chain;working['cursor']+=1;create_node(chain)

        factory=self.stream_factory or (lambda n:BatchStream(self.generate,n))
        with factory(self.concurrency) as stream:
            while ready or inflight or chains or created<self.node_groups_per_update:
                while len(inflight)<self.concurrency:
                    if not ready:
                        # Created groups already reserve their pending siblings.
                        # Reserve only NOT-YET-created future nodes of live chains.
                        reserved=created+sum(c['job'].row['k']-c['job'].controlled-int(c['waiting']) for c in chains.values())
                        if reserved>=self.node_groups_per_update:break
                        admit()
                    group,replica=ready.popleft();key=f'{group}:r{replica}'
                    stream.submit(key,contexts[group]['candidates'][replica]);inflight[key]=(group,replica)
                    peak=max(peak,len(inflight))
                ensure(bool(inflight),'No runnable request before collection completed')
                before=time.perf_counter();events=stream.poll();generation_seconds+=time.perf_counter()-before
                for key,out in events:
                    ensure(key in inflight,'Unknown/duplicate streaming completion')
                    group,replica=inflight.pop(key);ctx=contexts[group]
                    cursor,row,depth=ctx['cursor'],ctx['row'],ctx['depth'];req=ctx['candidates'][replica]
                    call=score_response(ctx['scoring'],out,req,ctx['q'],ctx['posterior'])
                    ctx['calls'][replica]=call;ctx['received']+=1
                    if replica==ctx['chosen']:
                        chain=chains[cursor];job=chain['job'];chain['waiting']=False
                        chain['history'].append(dict(group=group,replica=replica,task_reward=call['task_reward']))
                        job.accept(out,req)
                        if job.status=='running':create_node(chain)
                        else:
                            record=job.record();record.pop('calls')
                            record.update(chain=ctx['chain'],group=ctx['chain'],cursor=cursor,reset_seed=chain['reset_seed'],
                                selected_nodes=chain['history'],step_rewards=job.step_rewards)
                            games.append(record);del chains[cursor]
                            exposure=working['exposure'].setdefault(row['id'],dict(entries=0,node_groups=0,responses=0,completed=0))
                            exposure['entries']+=1;exposure['completed']+=int(job.status=='terminal')
                    if ctx['received']!=self.replicas:continue
                    calls=ctx['calls'];q,posterior=ctx['q'],ctx['posterior']
                    ensure(len({c['prompt_sha256'] for c in calls})==1,'Node candidates have different prompts')
                    ensure(all(c['prompt_ids']==calls[0]['prompt_ids'] for c in calls),'Node candidate prompt tokens differ')
                    advs,mean,std=group_advantages([c['task_reward'] for c in calls])
                    scoring_sha=digest(dict(prompt=calls[0]['prompt_sha256'],reference_id=row['reference_id'],
                        node=ctx['scoring'].node,player=row['ego'],remaining_k=row['k']-depth,posterior=posterior.tolist(),Q=q.tolist()))
                    for r,(c,adv) in enumerate(zip(calls,advs)):
                        protocol=0. if c['valid'] else -PROTOCOL_PENALTY
                        c.update(kind='slices',task_id=row['id'],parent_id=row['parent_id'],group=group,chain=ctx['chain'],
                            cursor=cursor,unit=f'{group}:r{r}',replica=r,player=row['ego'],decision_index=depth,
                            remaining_k=row['k']-depth,scoring_sha256=scoring_sha,selected_for_continuation=r==ctx['chosen'],
                            reward_mean=mean,reward_std=std,task_advantage=adv,protocol_advantage=protocol,advantage=adv+protocol,
                            task_denominator=0.,loss_weight=1.,task_weight=1.,protocol_weight=1.,kl_weight=1.)
                        rows.append(c)
                    units.append(dict(group=group,chain=ctx['chain'],cursor=cursor,decision_index=depth,slice_id=row['id'],parent_id=row['parent_id'],
                        remaining_k=row['k']-depth,selected_replica=ctx['chosen'],prompt_sha256=calls[0]['prompt_sha256'],scoring_sha256=scoring_sha,
                        task_rewards=[c['task_reward'] for c in calls],reward_mean=mean,reward_std=std,
                        task_active=any(a!=0 for a in advs),protocol_active=any(not c['valid'] for c in calls),
                        binary_correct=sum(c['binary_reward'] for c in calls),
                        unique_legal_actions=len({c['action_index'] for c in calls if c['valid']}),
                        sampled_reward_range=float(np.ptp([c['task_reward'] for c in calls])),oracle_value_span=float(np.ptp(q))))
                    exposure=working['exposure'].setdefault(row['id'],dict(entries=0,node_groups=0,responses=0,completed=0))
                    exposure['node_groups']+=1;exposure['responses']+=self.replicas
                    del contexts[group]
            ensure(not contexts and len(units)==created,'Unfinished node groups at optimizer boundary')
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
            oracle_action_value_seconds=oracle_seconds,generation_seconds=generation_seconds,
            scheduler_peak_inflight=peak,scheduler_native_ticks=getattr(stream,'ticks',0),
            scheduler_prompt_tokenizations=getattr(stream,'tokenizations',0),
            scheduler_prompt_cache_hits=getattr(getattr(stream,'prompt_cache',None),'hits',0))
        if hasattr(self.dataset,'cache_metrics'):self.last_timing.update(self.dataset.cache_metrics())
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
