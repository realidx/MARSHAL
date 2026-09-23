"""Four-arm training with fixed auxiliary exposure and candidate-normalized losses."""
from collections import Counter, defaultdict
from copy import deepcopy
import math
import random

from training.social_mixed.core import Collector, centered, seed_for
from training.social_mixed.stabilization import StableCollector

VERSION = 'social-reasoning-tristate-exposure-v5'
SP_ADVANTAGE_VERSION = 'reset-seat-completed-standard-v1'
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


def assign_sp_completed_advantages(rows, units, metrics):
    """Compare completed replicas only, independently for each reset-seat group."""
    groups=defaultdict(list)
    by_unit=defaultdict(list)
    for row in rows:by_unit[row['unit']].append(row)
    for unit in units:groups[unit['group']].append(unit)
    mixed=0
    for members in groups.values():
        complete=[u for u in members if u['utility'] is not None]
        values=[u['utility'] for u in complete]
        if any(not math.isfinite(v) for v in values):
            raise ValueError('Non-finite SP terminal utility')
        mean=sum(values)/len(values) if values else 0.
        std=math.sqrt(sum((v-mean)**2 for v in values)/len(values)) if values else 0.
        advantages=dict(zip((u['unit'] for u in complete),centered(values) if values else []))
        mixed+=int(bool(values) and max(values)>min(values))
        for unit in members:
            rs=by_unit[unit['unit']]
            for row in rs:
                row['task_advantage']=advantages.get(unit['unit'],0.) if not row['protocol_failure'] else 0.
                row['task_weight']=len(rows)/len(by_unit)/len(rs)
                row['protocol_weight']=row['loss_weight']
                row['kl_weight']=row['loss_weight']
                row['task_denominator']=0.
                row['baseline']=mean
                row['group_reward_std']=std
                row['completed_replicas']=len(complete)
                row['sp_advantage_version']=SP_ADVANTAGE_VERSION
                row['advantage']=row['task_advantage']+row['protocol_advantage']
    # Original collector metrics describe the legacy all-complete calculation.
    for key in list(metrics):
        if 'mixed_groups' in key or 'task_abs_weighted_mass' in key or 'nonzero_task_calls' in key:
            metrics['legacy_group/'+key]=metrics.pop(key)
    metrics.update({'selfplay/completed_mixed_groups':mixed,
                    'selfplay/completed_player_episodes':sum(u['utility'] is not None for u in units),
                    'selfplay/censored_player_episodes':sum(u['utility'] is None for u in units),
                    'selfplay/nonzero_task_calls':sum(abs(r['task_advantage'])>1e-9 for r in rows)})


class ReasoningCollector(StableCollector):
    def __init__(self,*args,normalization='standard_sequence',**kwargs):
        super().__init__(*args,**kwargs)
        if normalization not in NORMALIZATIONS:raise ValueError('Unknown normalization')
        self.normalization=normalization
        self.sp_replicas=4
        self.sp_initial_groups=8  # 32 active trajectories, independent of inference chunk size.
        self.state=dict(version=VERSION,normalization=normalization,questions={},baselines={},
                        block=0,consumed=0,fill_cursor=0,sp_cursor=0,sp_advantage_version=SP_ADVANTAGE_VERSION)
        from training.social_mixed.coverage_sampling import VERSION as coverage_version
        self.state.update(coverage_version=coverage_version,coverage={})
        self.schedule=case_schedule(self.data['bp_train'],self.seed)
        self.views={(t['canonical_id'],t['paired_view']):t for t in self.data['bp_train']}
        if any(t.get('paired_view')=='Pplus' and 'teacher' in t and 'p_supervision' not in t for t in self.data['bp_train']):
            raise ValueError('Real P tasks require the audited tri-state policy before training')
        if any((c,v) not in self.views for c in self.schedule for v in ('O','B','Pplus')):
            raise ValueError('Incomplete reasoning package')
        self.informative=[c for c in self.schedule if self.views[c,'O']['belief_action_relevant'] and self.views[c,'Pplus'].get('p_train_eligible',True)]
        self.controls=[c for c in self.schedule if not self.views[c,'O']['belief_action_relevant'] and self.views[c,'Pplus'].get('p_train_eligible',True)]
        self.feedback_windows={}
        self.p_categories={}
        if 'compact_metadata' in self.data:
            self.p_categories=self.data['compact_metadata']['categories']
            self.feedback_windows=self.data['compact_metadata']['windows']
            from training.social_mixed.feedback_sampling import VERSION as feedback_version
            self.state.update(feedback_version=feedback_version,compact_bank_sha256=self.data['compact_bank_sha256'])
        elif all('canonical_action_task' in t for t in self.data['bp_train']):
            from training.social_mixed.reasoning_bank import load
            from training.social_mixed.feedback_sampling import build_windows, VERSION as feedback_version
            from training.social_mixed.p_task_categories import inventory
            self.p_categories=inventory(self.data['bp_train'],load('train','cases.jsonl'))
            self.feedback_windows=build_windows(self.data['bp_train'],load('train','relations.jsonl'))
            if not all(self.feedback_windows.values()):
                raise ValueError('Feedback recipe requires certified update, maintain and action pairs')
            self.state['feedback_version']=feedback_version
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

    def restore(self,state,arm=None):
        if state.get('version')!=VERSION or state.get('normalization')!=self.normalization:
            raise ValueError('Reasoning recipe changed on resume')
        if arm not in ('outcome','conditioned','decomposed') and state.get('sp_advantage_version')!=SP_ADVANTAGE_VERSION:
            raise ValueError('SP advantage recipe changed; start a new stage, do not silently resume historical baseline')
        if self.feedback_windows and arm!='selfplay' and state.get('feedback_version')!=self.state.get('feedback_version'):
            raise ValueError('Feedback sampling changed; start a new stage')
        if arm in ('outcome','conditioned','decomposed'):
            from training.social_mixed.coverage_sampling import VERSION as coverage_version
            if state.get('coverage_version')!=coverage_version:
                raise ValueError('Coverage/difficulty recipe changed; start a new stage')
        if state.get('compact_bank_sha256') != self.state.get('compact_bank_sha256'):
            raise ValueError('Training pool changed; start a new stage')
        self.state=deepcopy(state)

    def collect(self,step,arm,token_target=65536,validation=False):
        if validation:raise ValueError('Use the independent reasoning validator')
        if arm not in ARMS:raise ValueError('Unknown four-arm condition')
        if arm=='selfplay':
            boundary=(self.state['block']+1)*token_target
            rows,units,games,metrics=Collector.collect(self,step,arm,max(1,boundary-self.state['consumed']))
            assign_sp_completed_advantages(rows,units,metrics)
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
        if arm!='decomposed' and token_target < 7*8*1024:
            raise ValueError('Token block must fit six auxiliary groups plus one O group at max length')
        block=self.state['block']; rows=[]; units=[]; counts=Counter(); effective=Counter(); tokens=0
        boundary=(block+1)*token_target
        start=self.state['consumed']
        def collect_group(canonical,view,slot):
            nonlocal tokens
            task=self.views[canonical,view]
            from training.social_mixed.task_difficulty import describe
            difficulty=describe(task)
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
            if view+':'+canonical in self.state['coverage']:
                entry=self.state['coverage'][view+':'+canonical]
                entry['effective']=entry.get('effective',0)+int(any(abs(a)>1e-12 for a in advantages))
            for replica,(o,s,a,ok) in enumerate(zip(outputs,scores,advantages,valid)):
                unit=f'{group}:r{replica}'
                rows.append(dict(o,kind=view,skill=task['pool'],kernel=task['kernel'],group=group,unit=unit,
                    replica=replica,task_id=task['id'],canonical_id=canonical,package_id=task['package_id'],
                    belief_action_relevant=task['belief_action_relevant'],
                    exposure_slot=slot,difficulty=difficulty,token_block=block,score=s,task_advantage=a,
                    protocol_advantage=0. if ok else -self.protocol_coefficient,
                    protocol_failure=None if ok else 'truncated' if o['completion']['finish_reason']=='length' else 'invalid_action',
                    selected_task_group=any(abs(x)>1e-12 for x in advantages),
                    task_denominator=0. if self.normalization=='standard_sequence' else 1024.,advantage_version=VERSION))
                units.append(dict(group=group,unit=unit,replica=replica,kind=view,utility=s['reward']))
                tokens+=len(o['response_ids'])
        if arm=='decomposed':
            from training.social_mixed.coverage_sampling import plan
            for canonical,view,slot in plan(self):collect_group(canonical,view,slot)
        else:
            # O/C retain their token boundary and task weights; share D's global coverage rule.
            from training.social_mixed.coverage_sampling import choose_view
            if arm=='conditioned':
                for canonical,view,slot in choose_view(self,'Pplus',3):collect_group(canonical,view,slot)
            for canonical,view,slot in choose_view(self,'O',6 if arm=='outcome' else 3):
                collect_group(canonical,view,slot)
            while start+tokens<boundary:
                for canonical,view,slot in choose_view(self,'O',1):collect_group(canonical,view,slot)
        n=len(rows)
        for r in rows:
            w=n*WEIGHTS[arm][r['kind']]/(8*counts[r['kind']])
            r.update(task_weight=w,protocol_weight=w,kl_weight=w,loss_weight=w,
                     advantage=r['task_advantage']+r['protocol_advantage'])
        self.state.update(block=block+1,consumed=start+tokens)
        metrics=dict(generated_tokens=tokens,rows=n,games=0,candidate_groups=sum(counts.values()),
                     skip_optimizer=False,token_block=block,token_boundary=boundary,
                     token_overshoot=start+tokens-boundary)
        if arm=='decomposed':
            metrics.pop('token_boundary');metrics.pop('token_overshoot')
            metrics['fixed_candidate_groups']=12
            metrics['coverage_unique_tasks']=len(self.state['coverage'])
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
