"""Common four-arm dev selection plus per-case acquisition/retention evidence."""
from collections import defaultdict
from copy import deepcopy
from training.social_mixed.validation import Validator
from training.social_mixed.reasoning_bank import load, panel

VERSION='reasoning-static-obp-v5'


def metrics_and_state(calls, previous=None):
    previous=previous or {}
    old=previous.get('last',{}); ever=previous.get('ever_correct',{})
    current={r['task']['id']:r['score'].get('correct') for r in calls}
    if old and set(old)!=set(current):raise ValueError('Retention panel identity changed')
    grouped=defaultdict(list); metrics={}
    for r in calls:grouped[r['task']['paired_view']].append(r)
    for view,rs in grouped.items():
        total=len(rs)
        masked=[r for r in rs if r['score'].get('semantic_outcome')=='masked']
        metrics[f'reasoning/{view}/semantic_masked']=len(masked)
        metrics[f'reasoning/{view}/scored_coverage']=(total-len(masked))/total
        metrics[f'reasoning/{view}/valid_rate']=sum(r['score']['status'] not in ('format_failure','truncated') for r in rs)/total
        all_ids=[r['task']['id'] for r in rs]
        rs=[r for r in rs if r['score'].get('correct') is not None]
        metrics[f'reasoning/{view}/scored_count']=len(rs)
        if not rs:
            for key in ('forgotten_from_previous','acquired_from_previous','lost_ever_correct'):
                metrics[f'reasoning/{view}/'+key]=0
            metrics[f'reasoning/{view}/previously_correct_now_masked']=sum(old.get(k) is True for k in all_ids)
            continue
        packages=defaultdict(list)
        for r in rs:packages[r['task']['package_id']].append(bool(r['score']['correct']))
        metrics[f'reasoning/{view}/macro_accuracy']=sum(sum(v)/len(v) for v in packages.values())/len(packages)
        metrics[f'reasoning/{view}/'+('conditional_accuracy' if view=='Pplus' else 'accuracy')]=sum(bool(r['score']['correct']) for r in rs)/len(rs)
        ids=[r['task']['id'] for r in rs]
        metrics[f'reasoning/{view}/forgotten_from_previous']=sum(old.get(k) is True and current[k] is False for k in ids)
        metrics[f'reasoning/{view}/forgotten_invalid']=sum(old.get(r['task']['id']) is True and r['score']['correct'] is False and r['score']['status'] in ('format_failure','truncated') for r in rs)
        metrics[f'reasoning/{view}/forgotten_legal']=sum(old.get(r['task']['id']) is True and r['score']['correct'] is False and r['score']['status'] not in ('format_failure','truncated') for r in rs)
        metrics[f'reasoning/{view}/acquired_from_previous']=sum(old.get(k) is False and current[k] is True for k in ids)
        metrics[f'reasoning/{view}/lost_ever_correct']=sum(ever.get(k,False) and current[k] is False for k in ids)
        metrics[f'reasoning/{view}/previously_correct']=sum(old.get(k) is True for k in all_ids)
        metrics[f'reasoning/{view}/previously_correct_now_masked']=sum(old.get(k) is True and current[k] is None for k in all_ids)
        regrets=[r['score']['own_regret'] for r in rs if r['score'].get('own_regret') is not None]
        metrics[f'reasoning/{view}/regret_valid_count']=len(regrets)
        if regrets:metrics[f'reasoning/{view}/conditional_mean_regret']=sum(regrets)/len(regrets)
        for relevant in (True,False):
            subset=[r for r in rs if bool(r['task'].get('belief_action_relevant'))==relevant]
            prefix=f'reasoning/{view}/'+('action_relevant' if relevant else 'control')
            metrics[prefix+'/samples']=len(subset)
            if subset:metrics[prefix+'/accuracy']=sum(bool(r['score']['correct']) for r in subset)/len(subset)
        if view=='B':
            for field in ('set_exact','favored_exact','favored_accepted','strict_correct'):
                metrics[f'reasoning/B/{field}']=sum(bool(r['score'].get(field)) for r in rs)/len(rs)
    by_case=defaultdict(dict)
    for r in calls:by_case[r['task']['canonical_id']][r['task']['paired_view']]=r['score'].get('correct')
    metrics['reasoning/cases']=len(by_case)
    metrics['reasoning/B_Pplus_correct_O_wrong']=sum(v.get('B') is True and v.get('Pplus') is True and v.get('O') is False for v in by_case.values())
    metrics['reasoning/Pplus_correct_O_wrong']=sum(v.get('Pplus') is True and v.get('O') is False for v in by_case.values())
    return metrics,dict(last=current,ever_correct={k:bool(ever.get(k,False) or v is True) for k,v in current.items()})


def selection_score(metrics):
    # Keep unassisted O as the selection criterion; B/P remain diagnostic.
    return [metrics['reasoning/O/macro_accuracy']]


class ReasoningValidator(Validator):
    def __init__(self,data,generate,seed=42,concurrency=16,**kwargs):
        if concurrency<1:raise ValueError('Positive validation concurrency required')
        self.data=data;self.generate=generate;self.seed=seed;self.concurrency=concurrency
        self.static_only=True
        self.resets=[]
        self.tasks=[t for t in panel() if t.get('paired_view')!='Pplus' or t.get('p_pool_status')!='quarantined']

    def run_static_o(self):
        """Frozen O panel only; current actor, no interaction partners or selection."""
        from training.social_mixed.paired_requests import request
        from training.social_mixed.reasoning_scoring import score, decision_metrics
        from training.social_mixed.core import seed_for
        from training.social_mixed.validation import VERSION as BASE_VERSION
        jobs=[]; calls=[]
        for task in self.tasks:
            if task['paired_view']!='O':continue
            req=request(task,'action_tools',task.get('name_variant',0))
            req.update(seed=seed_for(self.seed,BASE_VERSION,'bp',task['id'],0),temperature=0.0)
            jobs.append((task,req))
        for offset in range(0,len(jobs),self.concurrency):
            batch=jobs[offset:offset+self.concurrency]
            answers=self.generate([req for _,req in batch])
            if len(answers)!=len(batch):raise RuntimeError('Missing static O answers')
            for (task,req),answer in zip(batch,answers):
                scored=score(task,answer['completion'])
                scored.update(decision_metrics(task,answer['completion']))
                calls.append(dict(answer,task=task,request=req,replica=0,score=scored))
        return calls

    def run(self):
        report=super().run()
        from training.social_mixed.reasoning_scoring import decision_metrics, score
        from training.social_mixed.validation import summarize_bp
        for r in report['bp_calls']:
            r['score']=score(r['task'],r['completion'])
            r['score'].update(decision_metrics(r['task'],r['completion']))
        # Generic legacy bp metrics assume binary correctness; use them only for O/B.
        report['metrics']={k:v for k,v in report['metrics'].items() if not k.startswith('bp/')}
        report['metrics'].update(summarize_bp([r for r in report['bp_calls'] if r['task']['paired_view']!='Pplus']))
        report['metrics'].update(metrics_and_state(report['bp_calls'])[0])
        indexed={(r['task']['canonical_id'],r['task']['paired_view']):r for r in report['bp_calls']}
        for view in ('O','Pplus'):
            for kind in ('must_change','same_optimal_set','overlapping_optima'):
                relations=[r for r in load('validation','relations.jsonl') if r['relation']==kind and r['fixed_continuation_payoffs_match'] and
                           (r['left'],view) in indexed and (r['right'],view) in indexed]
                report['metrics'][f'reasoning/{view}/{kind}/pairs']=len(relations)
                if relations:
                    scored=[r for r in relations if all(indexed[r[k],view]['score'].get('correct') is not None for k in ('left','right'))]
                    report['metrics'][f'reasoning/{view}/{kind}/scored_pair_coverage']=len(scored)/len(relations)
                    relations=scored
                if relations:
                    report['metrics'][f'reasoning/{view}/{kind}/both_correct']=sum(
                        indexed[r['left'],view]['score']['correct'] and indexed[r['right'],view]['score']['correct']
                        for r in relations)/len(relations)
        for view in ('O','B','Pplus'):
            links=[r for r in load('validation','relations.jsonl') if r.get('isolated_B_action_pair') and all((r[k],view) in indexed for k in ('left','right'))]
            scored=[r for r in links if all(indexed[r[k],view]['score'].get('correct') is not None for k in ('left','right'))]
            report['metrics'][f'reasoning/{view}/isolated_B_action_pairs']=len(links)
            report['metrics'][f'reasoning/{view}/isolated_B_scored_pairs']=len(scored)
            if scored:report['metrics'][f'reasoning/{view}/isolated_B_both_correct']=sum(all(indexed[r[k],view]['score']['correct'] is True for k in ('left','right')) for r in scored)/len(scored)
        report['protocol'].update(version=VERSION,selection='Static O parent-macro; earlier tie',
            package_ids=sorted({t['package_id'] for t in self.tasks}),
            auxiliary_scores_for_selection=False,
            caveats='Static O/B/P only; no interaction evaluation. P receives state and qualitative beliefs without history. P masked coverage is reported. Temperature zero does not guarantee batch-invariant inference.')
        return report
