"""Held-out local correctness and full native-game utility under the frozen profile."""
from collections import defaultdict
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .common import seed_for
from .evaluate import Evaluator, interval
from .terminal_candidates import sample_member_world
from .terminal_training import StepRollout,execute


class FullGameView:
    def __init__(self,data,parent_ids,split='validation'):
        self.data=data;self.sha=data.sha
        self.by_parent={}
        for row in getattr(data,split):
            self.by_parent.setdefault(row['parent_id'],row)
        parents=[]
        for pid in sorted(parent_ids):
            parent=data.parents[pid];rules=self.rules(parent)
            parents.append(dict(parent,world_weights=world_weights(rules.worlds,parent['raw']['background_prior'])))
        self.parents={split:parents}
    def rules(self,parent):
        rules=PrivateInvestigationRules(parent['raw']);rules.background_prior=parent['raw']['background_prior'];return rules
    def reference(self,parent):return self.data.reference(self.by_parent[parent['id']])[0]


class Validator:
    def __init__(self,data,generate,cfg,repeats=1,limit=None,split='validation',stream_factory=None,stop_check=None):
        if split not in ('validation','test') or repeats<1 or (limit is not None and limit<1):
            raise ValueError('Expected held-out split and positive evaluation limits')
        self.data,self.generate,self.cfg=data,generate,cfg
        self.repeats,self.limit,self.split=repeats,limit,split
        self.stream_factory,self.stop_check=stream_factory,stop_check
        self.last_execution={}
    def run(self):
        cfg=dict(self.cfg,temperature=0.)
        selected=sorted(getattr(self.data,self.split),key=lambda r:r['id'])
        if self.limit is not None:selected=selected[:self.limit]
        by_parent=defaultdict(list)
        for row in selected:by_parent[row['parent_id']].append(row)
        records=[];calls=[]
        def specifications():
            for _,rows in sorted(by_parent.items()):
                for row in rows:
                    for replica in range(self.repeats):yield row,replica
        def make(spec):
            row,replica=spec;tree,cache=self.data.reference(row)
            seed=seed_for(cfg['seed'],'terminal-'+self.split,row['id'],replica)
            reset=sample_member_world(row,np.random.default_rng(seed))
            return StepRollout(tree,row,replica,seed,reset,cache=cache)
        def finish(index,spec,job):
            record=job.record();record.pop('calls');record.update(step_rewards=job.step_rewards)
            cs=[dict(c,oracle_step=d,slice_id=job.row['id'],replica=job.replica,decision_index=i)
                for i,(c,d) in enumerate(zip(job.calls,job.step_details))]
            # Release native trees as soon as this episode finishes. Report
            # ordering is reconstructed from the fixed cohort, not arrival time.
            job.tree=job.node=job.q_cache=None
            results[index]=(record,cs)
        results={}
        if self.stream_factory is not None:
            from .evaluation_refill import execute as refill
            from .terminal_training import check_output
            def accept(job,out,req):check_output(out,cfg);job.accept(out,req)
            self.last_execution['slices']=refill(specifications(),make,lambda j:j.request(cfg),accept,finish,
                self.stream_factory,cfg['workers'],'terminal-'+self.split,stop_check=self.stop_check)
        else:
            # Retain the old wave implementation as the independent CPU/report
            # reference and for standalone callers without a native engine.
            index=0
            for _,rows in sorted(by_parent.items()):
                specs=[(row,r) for row in rows for r in range(self.repeats)]
                jobs=[make(spec) for spec in specs];execute(jobs,self.generate,cfg,cfg['workers'])
                for spec,job in zip(specs,jobs):finish(index,spec,job);index+=1
        for index in sorted(results):
            record,cs=results[index];records.append(record);calls.extend(cs)
        def generate_full(requests):
            return self.generate([dict(r,max_tokens=cfg['max_tokens'],top_p=1.,top_k=-1,repetition_penalty=1.) for r in requests])
        evaluator=Evaluator(FullGameView(self.data,set(by_parent),self.split),generate_full,
            split=self.split,repeats=self.repeats,seed=cfg['seed'],concurrency=cfg['workers'],
            stream_factory=self.stream_factory,request_options=dict(max_tokens=cfg['max_tokens'],top_p=1.,top_k=-1,repetition_penalty=1.),
            stop_check=self.stop_check)
        full=evaluator.run()
        if self.stream_factory is not None:self.last_execution['full_games']=evaluator.last_execution
        # The legacy evaluator describes its old 1024 default; this wrapper
        # supplies the explicit native output budget on every actual request.
        full['protocol']['max_tokens']=cfg['max_tokens']
        rewards=[v for r in records for v in r['step_rewards']]
        completed=[r['utility'] for r in records if r['status']=='terminal']
        def decision_metrics(subset):
            legal=[c['oracle_step']['gap'] for c in subset if c['protocol_status']=='ok']
            # The all-call metric uses exactly the training failure convention;
            # legal-only regret must not conceal failed responses.
            regrets=[c['oracle_step']['gap'] if c['protocol_status']=='ok'
                else float(np.ptp(c['oracle_step']['Q'])) for c in subset]
            return dict(calls=len(subset),legal_calls=len(legal),
                per_decision_accuracy=float(np.mean([c['oracle_step']['reward'] for c in subset])) if subset else None,
                mean_regret_legal=float(np.mean(legal)) if legal else None,
                mean_regret_with_failure_worst_action=float(np.mean(regrets)) if regrets else None)
        information_ids={r['id'] for r in selected if r['information_positive']}
        roots=[c for c in calls if c['decision_index']==0]
        strata=dict(all=decision_metrics(calls),root=decision_metrics(roots),
            information_root=decision_metrics([c for c in roots if c['slice_id'] in information_ids]))
        response_tokens=sum(len(c['response_ids']) for c in calls+full['calls'])
        return dict(protocol=dict(split=self.split,test_loaded_for_scoring=self.split=='test',temperature=0.,max_tokens=cfg['max_tokens'],
            limit=self.limit,repeats=self.repeats,primary_checkpoint='final',selection_candidate=False,
            limitation='No independent strong-acquisition held-out family; native parent horizons remain short.'),
            generated_response_tokens=response_tokens,
            slices=dict(episodes=len(records),completion_rate=len(completed)/len(records),
                per_decision_accuracy=sum(rewards)/len(rewards),terminal_utility_completed=interval(completed),
                decision_metrics=strata,
                full_window_success_rate=sum(r['status']=='terminal' and all(r['step_rewards']) for r in records)/len(records)),
            slice_games=records,slice_calls=calls,full_games=full)
