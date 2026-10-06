"""CPU-safe online training contract for selected terminal slices.

Binary correctness at each controlled decision; shared reset per replica group;
leave-one-trajectory-out baseline. Oracle values never enter model requests.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

import numpy as np
from .common import digest, file_hash, seed_for
from .terminal_analysis import visible_posterior
from .terminal_candidates import sample_member_world
from .terminal_d import TerminalRollout, load_dataset
from .values import extreme_value

VERSION='terminal-step-binary-shared-reset-loo-fixed-questions-v3'
PROTOCOL_PENALTY=0.2
CONTRACT=dict(version=VERSION,reward='Per-controlled-decision oracle correctness, 0/1; all tied optimal actions accepted.',
    epsilon=1e-7,baseline='Mean trajectory-average step reward of the OTHER replicas in this reset group; no std normalization.',
    weighting='Each trajectory equal weight; average over its actually generated decisions and response tokens.',
    failure='Failed call binary reward=0 and separate protocol advantage=-0.2; stop episode; preserve earlier local rewards; no retry.',
    protocol_penalty=PROTOCOL_PENALTY,
    batching='Fixed question groups per optimizer update; token budget only stops training after a complete update.',
    reset='One entrance, hidden world and focal player per group; independent model/reference RNG streams per replica.',
    continuation='Same frozen initial terminal oracle for partners and focal after k; early native terminal ends episode.',
    objective='On-policy local decision correctness, not an equivalent estimator of terminal-utility policy gradient.',
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


def binary_advantages(rewards):
    """Other trajectories provide an action-independent scalar baseline.

    Each reward is scored locally, so valid prefixes of failed trajectories
    remain meaningful. No padding rewards for unvisited decisions are invented.
    """
    ensure(len(rewards)>=2 and all(rs and all(r in (0,1) for r in rs) for rs in rewards),'Need >=2 nonempty binary trajectories')
    means=[sum(rs)/len(rs) for rs in rewards]
    baselines=[sum(means[j] for j in range(len(means)) if j!=i)/(len(means)-1) for i in range(len(means))]
    return [[r-b for r in rs] for rs,b in zip(rewards,baselines)],baselines


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
                ids=out.get('response_ids');logps=out.get('behavior_log_probs')
                ensure(bool(out.get('prompt_ids')) and bool(ids) and logps is not None and len(ids)==len(logps)
                    and len(ids)<=cfg['max_tokens'] and all(math.isfinite(p) for p in logps),'Missing/invalid behavior token evidence')
                job.accept(out,req)


class Collector:
    def __init__(self,data,generate,seed=42,replicas=8,concurrency=32,max_tokens=1024,context=16384,questions_per_update=4):
        ensure(replicas>=2 and concurrency>=1 and 0<max_tokens<context,'Invalid training limits')
        ensure(type(questions_per_update) is int and 1<=questions_per_update<=len(data.train),'Invalid questions per update')
        self.questions_per_update=questions_per_update
        self.dataset,self.generate=data,generate
        self.replicas,self.concurrency=replicas,concurrency
        self.cfg=dict(seed=seed,replicas=replicas,workers=concurrency,max_tokens=max_tokens,context=context,
            temperature=1.,top_p=1.,top_k=-1,repetition_penalty=1.)
        self.state=dict(version=VERSION,dataset_sha256=data.sha,seed=seed,replicas=replicas,
            questions_per_update=questions_per_update,
            config=self.cfg,contract=CONTRACT,cursor=0,consumed=0,exposure={},step=0)
    def restore(self,state):
        for key in ('version','dataset_sha256','seed','replicas','questions_per_update','config','contract'):
            ensure(state[key]==self.state[key],'Collector resume contract changed: '+key)
        self.state=deepcopy(state)
    def collect(self,step,arm,token_target=1,validation=False):
        # The shared driver passes a remaining token budget; this collector
        # always finishes its fixed number of question groups before updating.
        ensure(arm=='slices' and not validation and token_target>0 and step==self.state['step'],'Invalid terminal collection request')
        working=deepcopy(self.state);rows=[];units=[];games=[];tokens=0;group_count=0;active_groups=0
        task_active_groups=protocol_active_groups=0
        while group_count<self.questions_per_update:
            specs=[];jobs=[]
            # Fill up to the native concurrency with complete shared-reset groups.
            for _ in range(min(max(1,self.concurrency//self.replicas),self.questions_per_update-group_count)):
                cursor=working['cursor'];cycle,offset=divmod(cursor,len(self.dataset.train))
                order=np.random.default_rng(seed_for(self.cfg['seed'],'terminal-train-order',cycle)).permutation(len(self.dataset.train))
                row=self.dataset.train[int(order[offset])];tree,cache=self.dataset.reference(row)
                reset_seed=seed_for(self.cfg['seed'],'terminal-train-reset',cursor)
                reset=sample_member_world(row,np.random.default_rng(reset_seed))
                group_seed=seed_for(self.cfg['seed'],'terminal-train-rollout',cursor)
                group=[StepRollout(tree,row,r,group_seed,reset,cache=cache) for r in range(self.replicas)]
                specs.append((cursor,row,group,reset_seed));jobs.extend(group);working['cursor']+=1
            execute(jobs,self.generate,self.cfg,self.concurrency)
            for cursor,row,group,reset_seed in specs:
                group_id=f'terminal:{cursor}:{row["id"]}'
                advantages,baselines=binary_advantages([j.step_rewards for j in group])
                task_active=any(abs(v)>1e-12 for vs in advantages for v in vs)
                protocol_active=any(j.status in ('truncated','invalid_action') for j in group)
                task_active_groups+=int(task_active);protocol_active_groups+=int(protocol_active)
                active_groups+=int(task_active or protocol_active);group_count+=1
                for replica,(job,advs,baseline) in enumerate(zip(group,advantages,baselines)):
                    unit=f'{group_id}:r{replica}'
                    units.append(dict(unit=unit,group=group_id,parent_id=row['parent_id'],slice_id=row['id'],
                        player=row['ego'],replica=replica,utility=job.utility[row['ego']] if job.utility is not None else None,
                        status=job.status,step_rewards=job.step_rewards,baseline=baseline))
                    for call,detail,adv in zip(job.calls,job.step_details,advs):
                        protocol=-PROTOCOL_PENALTY if call['protocol_status'] in ('truncated','invalid_action') else 0.
                        rows.append(dict(call,kind='slices',task_id=row['id'],parent_id=row['parent_id'],
                            group=group_id,unit=unit,replica=replica,player=row['ego'],
                            binary_reward=detail['reward'],oracle_step=detail,baseline=baseline,
                            valid=call['protocol_status']=='ok',protocol_failure=None if call['protocol_status']=='ok' else call['protocol_status'],
                            task_advantage=adv,protocol_advantage=protocol,advantage=adv+protocol,task_denominator=0.,
                            trajectory_length=len(job.calls)))
                    record=job.record();record.update(group=group_id,reset_seed=reset_seed,step_rewards=job.step_rewards)
                    record.pop('calls');games.append(record)
                    tokens+=sum(len(c['response_ids']) for c in job.calls)
                exposure=working['exposure'].setdefault(row['id'],dict(groups=0,trajectories=0,completed=0))
                exposure['groups']+=1;exposure['trajectories']+=len(group);exposure['completed']+=sum(j.status=='terminal' for j in group)
        for row in rows:
            weight=len(rows)/(len(units)*row['trajectory_length'])
            row.update(loss_weight=weight,task_weight=weight,protocol_weight=weight,kl_weight=weight)
        working['consumed']+=tokens;working['step']+=1;self.state=working
        return rows,units,games,dict(generated_tokens=tokens,rows=len(rows),groups=group_count,active_groups=active_groups,
            task_active_groups=task_active_groups,protocol_active_groups=protocol_active_groups,
            binary_correct_calls=sum(r['binary_reward'] for r in rows),decision_calls=len(rows),
            completion_rate=sum(g['status']=='terminal' for g in games)/len(games),
            truncated_calls=sum(r['protocol_failure']=='truncated' for r in rows),
            invalid_calls=sum(r['protocol_failure']=='invalid_action' for r in rows),
            skip_optimizer=False,step_binary_reward=True,terminal_utility_used_for_training=False)


def mock_generate(requests):
    from .terminal_d import mock_generate as generate
    outputs=generate(requests)
    for req,out in zip(requests,outputs):
        # Synthetic token evidence is only for CPU plumbing; never model evidence.
        out.update(prompt_ids=[1,2],response_ids=[3,4],behavior_log_probs=[-.5,-.5],text='MOCK',finish_reason='stop')
    return outputs
