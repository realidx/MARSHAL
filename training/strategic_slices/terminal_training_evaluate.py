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
    def __init__(self,data,generate,cfg,repeats=1,limit=None,split='validation'):
        if split not in ('validation','test') or repeats<1 or (limit is not None and limit<1):
            raise ValueError('Expected held-out split and positive evaluation limits')
        self.data,self.generate,self.cfg=data,generate,cfg
        self.repeats,self.limit,self.split=repeats,limit,split
    def run(self):
        cfg=dict(self.cfg,temperature=0.)
        selected=sorted(getattr(self.data,self.split),key=lambda r:r['id'])
        if self.limit is not None:selected=selected[:self.limit]
        by_parent=defaultdict(list)
        for row in selected:by_parent[row['parent_id']].append(row)
        records=[];calls=[]
        for pid,rows in sorted(by_parent.items()):
            jobs=[]
            for row in rows:
                tree,cache=self.data.reference(row)
                for replica in range(self.repeats):
                    seed=seed_for(cfg['seed'],'terminal-'+self.split,row['id'],replica)
                    reset=sample_member_world(row,np.random.default_rng(seed))
                    jobs.append(StepRollout(tree,row,replica,seed,reset,cache=cache))
            execute(jobs,self.generate,cfg,cfg['workers'])
            for job in jobs:
                record=job.record();record.pop('calls')
                record.update(step_rewards=job.step_rewards)
                records.append(record)
                calls.extend(dict(c,oracle_step=d,slice_id=job.row['id'],replica=job.replica) for c,d in zip(job.calls,job.step_details))
        def generate_full(requests):
            return self.generate([dict(r,max_tokens=cfg['max_tokens'],top_p=1.,top_k=-1,repetition_penalty=1.) for r in requests])
        full=Evaluator(FullGameView(self.data,set(by_parent),self.split),generate_full,
            split=self.split,repeats=self.repeats,seed=cfg['seed'],concurrency=cfg['workers']).run()
        # The legacy evaluator describes its old 1024 default; this wrapper
        # supplies the explicit native output budget on every actual request.
        full['protocol']['max_tokens']=cfg['max_tokens']
        rewards=[v for r in records for v in r['step_rewards']]
        completed=[r['utility'] for r in records if r['status']=='terminal']
        response_tokens=sum(len(c['response_ids']) for c in calls+full['calls'])
        return dict(protocol=dict(split=self.split,test_loaded_for_scoring=self.split=='test',temperature=0.,max_tokens=cfg['max_tokens'],
            limit=self.limit,repeats=self.repeats,primary_checkpoint='final',selection_candidate=False,
            limitation='No independent strong-acquisition held-out family; native parent horizons remain short.'),
            generated_response_tokens=response_tokens,
            slices=dict(episodes=len(records),completion_rate=len(completed)/len(records),
                per_decision_accuracy=sum(rewards)/len(rewards),terminal_utility_completed=interval(completed),
                full_window_success_rate=sum(r['status']=='terminal' and all(r['step_rewards']) for r in records)/len(records)),
            slice_games=records,slice_calls=calls,full_games=full)
