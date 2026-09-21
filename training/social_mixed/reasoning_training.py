"""Four-arm training with fixed auxiliary exposure and candidate-normalized losses."""
from collections import Counter, defaultdict
from copy import deepcopy
import math
import random

from training.social_mixed.core import seed_for
from training.social_mixed.stabilization import StableCollector

VERSION = 'social-reasoning-tristate-exposure-v5'
ARMS = ('selfplay', 'outcome', 'conditioned', 'decomposed')
WEIGHTS = {'outcome': {'O':1.}, 'conditioned': {'O':2/3, 'Pplus':1/3},
           'decomposed': {'O':1/3, 'B':1/3, 'Pplus':1/3}}
NORMALIZATIONS = ('centered_fixed', 'standard_sequence')


def case_schedule(tasks, seed):
    """Round-robin structural cells; parent members stay adjacent, all are visited."""
    packages=defaultdict(list)
    for t in tasks:
        if t['split'] != 'train':
            raise ValueError('Training sampler received non-training case')
        if t['paired_view']=='O':packages[t['package_id']].append(t)
    cells=defaultdict(list)
    for key,rs in sorted(packages.items()):
        first=rs[0]
        cells[(first['completion_mode'],first['source_kernel'])].append((key,rs))
    rng=random.Random(seed_for(seed,VERSION,'schedule'))
    for values in cells.values():rng.shuffle(values)
    result=[]
    while any(cells.values()):
        for key in sorted(cells):
            if cells[key]:
                _,rs=cells[key].pop()
                result.extend(t['canonical_id'] for t in sorted(rs,key=lambda x:x['canonical_id']))
    if not result or len(result)!=len(set(result)):
        raise ValueError('Empty or duplicated canonical schedule')
    return result


def group_advantages(scores, outputs, normalization):
    valid=[s['status']!='format_failure' and o['completion']['finish_reason']!='length' for s,o in zip(scores,outputs)]
    values=[s['reward'] for s in scores]
    if any(v is None or not math.isfinite(v) for v in values):
        raise ValueError('Infrastructure/unscorable response cannot enter training')
    semantic=[ok and s.get('semantic_eligible',True) for ok,s in zip(valid,scores)]
    legal=[v for v,ok in zip(values,semantic) if ok]
    mean=sum(legal)/len(legal) if legal else 0.
    std=math.sqrt(sum((v-mean)**2 for v in legal)/len(legal)) if legal else 0.
    scale=std+1e-6 if normalization=='standard_sequence' else 1.
    return [(v-mean)/scale if ok else 0. for v,ok in zip(values,semantic)],valid


class ReasoningCollector(StableCollector):
    def __init__(self,*args,normalization='standard_sequence',**kwargs):
        super().__init__(*args,**kwargs)
        if normalization not in NORMALIZATIONS:raise ValueError('Unknown normalization')
        self.normalization=normalization
        self.sp_replicas=4
        self.sp_initial_groups=8  # 32 active trajectories, independent of inference chunk size.
        self.state=dict(version=VERSION,normalization=normalization,questions={},baselines={},
                        block=0,consumed=0,fill_cursor=0,sp_cursor=0)
        self.schedule=case_schedule(self.data['bp_train'],self.seed)
        self.views={(t['canonical_id'],t['paired_view']):t for t in self.data['bp_train']}
        if any(t.get('paired_view')=='Pplus' and 'teacher' in t and 'p_supervision' not in t for t in self.data['bp_train']):
            raise ValueError('Real P tasks require the audited tri-state policy before training')
        if any((c,v) not in self.views for c in self.schedule for v in ('O','B','Pplus')):
            raise ValueError('Incomplete reasoning package')
        self.informative=[c for c in self.schedule if self.views[c,'O']['belief_action_relevant'] and self.views[c,'Pplus'].get('p_train_eligible',True)]
        self.controls=[c for c in self.schedule if not self.views[c,'O']['belief_action_relevant'] and self.views[c,'Pplus'].get('p_train_eligible',True)]
        if not self.informative or not self.controls:
            raise ValueError('Both decision-relevant beliefs and control cases are required')

    def next_training_reset(self, candidates):
        # Keep curriculum quotas, but continue the schedule across optimizer blocks.
        # Regenerate deterministically each cycle; cursor is checkpointed with baselines.
        from training.social_mixed.curriculum_sampling import reset_order
        cursor=self.state['sp_cursor']
        initial=reset_order(candidates,random.Random(seed_for(self.seed,VERSION,'sp',0)))
        cycle,offset=divmod(cursor,len(initial))
        order=initial if cycle==0 else reset_order(candidates,random.Random(seed_for(self.seed,VERSION,'sp',cycle)))
        self.state['sp_cursor']=cursor+1
        return candidates[order[offset]]

    def restore(self,state):
        if state.get('version')!=VERSION or state.get('normalization')!=self.normalization:
            raise ValueError('Reasoning recipe changed on resume')
        self.state=deepcopy(state)

    def collect(self,step,arm,token_target=65536,validation=False):
        if validation:raise ValueError('Use the independent reasoning validator')
        if arm not in ARMS:raise ValueError('Unknown four-arm condition')
        if arm=='selfplay':
            boundary=(self.state['block']+1)*token_target
            rows,units,games,metrics=super().collect(step,arm,max(1,boundary-self.state['consumed']))
            self.state['block']+=1
            self.state['consumed']+=metrics['generated_tokens']
            metrics.update(token_boundary=boundary,token_overshoot=self.state['consumed']-boundary,
                           sp_reset_cursor=self.state['sp_cursor'],
                           sp_unique_resets_in_block=len({r['reset_id'] for r in rows}))
            for r in rows:r['advantage_version']=VERSION
            return rows,units,games,metrics
        return self.collect_paired(step,arm,token_target)

    def collect_paired(self,step,arm,token_target):
        from training.social_mixed.paired_requests import request
        from training.social_mixed.reasoning_scoring import score as reward
        if token_target < 7*8*1024:
            raise ValueError('Token block must fit six auxiliary groups plus one O group at max length')
        block=self.state['block']; rows=[]; units=[]; counts=Counter(); effective=Counter(); tokens=0
        boundary=(block+1)*token_target
        start=self.state['consumed']
        def collect_group(canonical,view,slot):
            nonlocal tokens
            task=self.views[canonical,view]
            group=f'block{block}:{slot}:{task["id"]}'
            requests=[]
            for replica in range(8):
                req=request(task,'action_tools',task.get('name_variant',0))
                req['seed']=seed_for(self.seed,VERSION,block,slot,canonical,view,replica)
                requests.append(req)
            outputs=[]
            for offset in range(0,8,self.concurrency):outputs.extend(self.generate(requests[offset:offset+self.concurrency]))
            if len(outputs)!=8:raise ValueError('Missing rollout outputs')
            if any(not 0<len(o['response_ids'])<=1024 for o in outputs):raise ValueError('Response length outside frozen contract')
            scores=[reward(task,o['completion']) for o in outputs]
            if 'teacher' in task:
                from training.social_mixed.reasoning_scoring import decision_metrics
                for s,o in zip(scores,outputs):s.update(decision_metrics(task,o['completion']))
            advantages,valid=group_advantages(scores,outputs,self.normalization)
            counts[view]+=1;effective[view]+=int(any(abs(a)>1e-12 for a in advantages))
            for replica,(o,s,a,ok) in enumerate(zip(outputs,scores,advantages,valid)):
                unit=f'{group}:r{replica}'
                rows.append(dict(o,kind=view,skill=task['pool'],kernel=task['kernel'],group=group,unit=unit,
                    replica=replica,task_id=task['id'],canonical_id=canonical,package_id=task['package_id'],
                    belief_action_relevant=task['belief_action_relevant'],
                    exposure_slot=slot,token_block=block,score=s,task_advantage=a,
                    protocol_advantage=0. if ok else -self.protocol_coefficient,
                    protocol_failure=None if ok else 'truncated' if o['completion']['finish_reason']=='length' else 'invalid_action',
                    selected_task_group=any(abs(x)>1e-12 for x in advantages),
                    task_denominator=0. if self.normalization=='standard_sequence' else 1024.,advantage_version=VERSION))
                units.append(dict(group=group,unit=unit,replica=replica,kind=view,utility=s['reward']))
                tokens+=len(o['response_ids'])
        # C/D see identical Pplus cases, seeds and slots. B replaces C's O slots.
        anchors=[self.informative[(2*block+j)%len(self.informative)] for j in range(2)]
        anchors.append(self.controls[block%len(self.controls)])
        for slot in range(6):
            canonical=self.schedule[block%len(self.schedule)] if slot==5 else anchors[slot%3]
            view='Pplus' if slot<3 and arm!='outcome' else 'B' if slot>=3 and arm=='decomposed' else 'O'
            collect_group(canonical,view,f'paired-{slot}')
        # O has a separate deterministic full-coverage stream; no reward-dependent resampling.
        while counts['O']==0 or start+tokens<boundary:
            cursor=self.state['fill_cursor']
            if counts['O']==0:
                collect_group(anchors[block%3],'O','paired-O-anchor')
            else:
                collect_group(self.schedule[cursor%len(self.schedule)],'O',f'fill-{cursor}')
                self.state['fill_cursor']=cursor+1
        n=len(rows)
        for r in rows:
            w=n*WEIGHTS[arm][r['kind']]/(8*counts[r['kind']])
            r.update(task_weight=w,protocol_weight=w,kl_weight=w,loss_weight=w,
                     advantage=r['task_advantage']+r['protocol_advantage'])
        self.state.update(block=block+1,consumed=start+tokens)
        metrics=dict(generated_tokens=tokens,rows=n,games=0,candidate_groups=sum(counts.values()),
                     skip_optimizer=False,token_block=block,token_boundary=boundary,
                     token_overshoot=start+tokens-boundary)
        for view in WEIGHTS[arm]:
            rs=[r for r in rows if r['kind']==view]
            metrics.update({f'{view}/candidate_groups':counts[view],f'{view}/semantic_contrast_groups':effective[view],
                f'{view}/response_tokens':sum(len(r['response_ids']) for r in rs),
                f'{view}/correct':sum(r['score']['reward'] for r in rs),
                f'{view}/valid':sum(r['protocol_failure'] is None for r in rs),
                f'{view}/semantic_masked':sum(r['score'].get('semantic_outcome')=='masked' for r in rs),
                f'{view}/semantic_scored':sum(r['protocol_failure'] is None and r['score'].get('semantic_eligible',True) for r in rs),
                f'{view}/task_coefficient_mass':sum(abs(r['task_advantage'])*r['task_weight']*len(r['response_ids'])/(r['task_denominator'] or len(r['response_ids'])) for r in rs)/n})
            for relevant in (True,False):
                selected=[r for r in rs if r['belief_action_relevant']==relevant]
                prefix=f'{view}/'+('action_relevant' if relevant else 'control')
                metrics[prefix+'/samples']=len(selected)
                metrics[prefix+'/correct']=sum(r['score']['reward'] for r in selected)
        return rows,units,[],metrics
