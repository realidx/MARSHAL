"""Development evaluation, separate from training collection and advantages.

Small fixed development panel; all game seats use the current policy.
Never selects final-test cases or loads a second opponent model.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from training.social_mixed.core import Episode, seed_for

VERSION='social-validation-v3-greedy-bp'

def select_resets(rows, count=8):
    if any(r['split']!='validation' for r in rows):raise ValueError('Development validation only')
    def features(r):
        g=r['raw']['game'];mode='binary' if all(x['binary'] for x in g['goals']) else 'linear'
        return {('players',r['players']),('rounds',r['rounds']),('mode',mode),('background',r.get('background_profile'))}
    chosen=[];covered=set()
    while len(chosen)<min(count,len(rows)):
        r=min((r for r in rows if r not in chosen),key=lambda r:(-len(features(r)-covered),seed_for(VERSION,r['id'])))
        chosen.append(r);covered|=features(r)
    return chosen

def cells(task):
    mode=task['completion_mode'];kernel=task['kernel'];kind=task['task']
    keys=[kind+'/all',kernel+'/'+mode,kind+'/players/'+str(task['input']['game']['n_players'])]
    if kind=='B':
        role='full_support' if len(task['teacher']['gold']['possible_preferences'])==3 else 'reduced_support'
        keys += ['B/'+role,kernel+'/'+mode+'/'+role]
        if kernel=='B3':keys.extend(['B3/'+task['skill'],'B3/'+mode+'/'+task['skill']])
    else:
        keys += [kernel+'/'+mode+'/'+task.get('information_role','ordinary_only')]
        keys.extend(['P/input/'+task['input'].get('belief_source','supplied'),'P/input/'+mode+'/'+task['input'].get('belief_source','supplied')])
        if kernel=='P4':keys.append('P4/'+(task.get('information_negative_kind') or task.get('information_role','unknown')))
    if kind=='P' and task['input'].get('belief_source')=='history':
        keys.append('P/history_sensitive' if task['teacher'].get('history_changes_acceptable') else 'P/history_control')
    if kernel=='P4':
        if task['input'].get('private_results'):keys.extend(['P4/result_use','P4/'+mode+'/result_use'])
        state=task['input']['current_state']
        if state['turn_index']>=len(state['round_robin'])-1:keys.append('P4/last_opportunity')
    return keys

def summarize_bp(rows):
    groups=defaultdict(list);contrasts=defaultdict(list)
    for r in rows:
        for k in cells(r['task']):groups[k].append(r)
        t=r['task'];contrasts[(t['kernel'],t.get('contrast_group',t['id']),t.get('background_profile'),t['completion_mode'],r['replica'])].append(r)
    out={}
    for k,rs in groups.items():
        prefix='bp/'+k+'/'
        out[prefix+'samples']=len(rs)
        out[prefix+'correct']=sum(bool(r['score']['correct']) for r in rs)
        out[prefix+'accuracy']=sum(bool(r['score']['correct']) for r in rs)/len(rs)
        out[prefix+'truncation_rate']=sum(r['completion']['finish_reason']=='length' for r in rs)/len(rs)
        out[prefix+'format_failure_rate']=sum(r['score']['status']=='format_failure' for r in rs)/len(rs)
        out[prefix+'wrong_fullset_rate']=sum(r['score'].get('predicted_full_set',False) and not r['score']['correct'] for r in rs)/len(rs)
        out[prefix+'investigate_rate']=sum(any(c.get('function',{}).get('name')=='INVESTIGATE' for c in r['completion']['raw_message'].get('tool_calls') or []) for r in rs)/len(rs)
    paired=[rs for rs in contrasts.values() if len({r['task'].get('answer_signature') for r in rs})>1]
    out['bp/contrast_groups']=len(paired)
    if paired:out['bp/contrast_all_correct_rate']=sum(all(r['score']['correct'] for r in rs) for rs in paired)/len(paired)
    by={(r['task']['id'],r['replica']):r for r in rows}
    pairs=[(by[(r['task']['oracle_pair_of'],r['replica'])],r) for r in rows if (r['task'].get('oracle_pair_of'),r['replica']) in by]
    out['bp/history_pairs/count']=len(pairs)
    if pairs:
        for name,index in [('raw',0),('oracle',1)]:out['bp/history_pairs/'+name+'_accuracy']=sum(bool(pair[index]['score']['correct']) for pair in pairs)/len(pairs)
        out['bp/history_pairs/improved']=sum(not raw['score']['correct'] and oracle['score']['correct'] for raw,oracle in pairs)
        out['bp/history_pairs/worsened']=sum(raw['score']['correct'] and not oracle['score']['correct'] for raw,oracle in pairs)
    return out

def select_bp(rows, count=32):
    """Greedy coverage of complete same-mode contrast groups, without outcomes."""
    groups=defaultdict(list)
    for t in rows:
        if t['split']!='validation':raise ValueError('Development BP only')
        if t['kernel'] not in ('B1','B2','B3','P1','P2','P3','P4'):continue
        groups[(t['kernel'],t.get('contrast_group',t['id']),t.get('background_profile'),t['completion_mode'])].append(t)
    units=[sorted(v,key=lambda t:t['id']) for v in groups.values()]
    chosen=[];covered=set()
    while True:
        eligible=[u for u in units if len(chosen)+len(u)<=count and sum(t['task']==u[0]['task'] for t in chosen)+len(u)<= (count//2 if u[0]['task']=='B' else count-count//2)]
        if not eligible:break
        def features(u):return set(k for t in u for k in cells(t))
        unit=min(eligible,key=lambda u:(-len(features(u)-covered)/len(u),-int(len({t['answer_signature'] for t in u})>1),sum(t['kernel']==u[0]['kernel'] for t in chosen),seed_for(VERSION,u[0]['id'])))
        chosen.extend(unit);covered|=features(unit);units.remove(unit)
    return sorted(chosen,key=lambda t:t['id'])


def summarize_games(games,calls):
    out={};strata={'all':games}
    for g in games:
        mode='binary' if all(x['binary'] for x in g['reset']['raw']['game']['goals']) else 'linear'
        strata.setdefault(f'{g["reset"]["players"]}p/{mode}',[]).append(g)
    for name,gs in strata.items():
        if not gs:continue
        prefix=f'games/current_team/{name}/';keys={g['group'] for g in gs}
        cs=[c for c in calls if c['evaluation_game'] in keys];done=[g for g in gs if g['status']=='terminal']
        out[prefix+'episodes']=len(gs);out[prefix+'completed']=len(done);out[prefix+'completion_rate']=len(done)/len(gs)
        for status,n in Counter(g['status'] for g in gs).items():out[prefix+'status/'+status]=n
        out[prefix+'calls']=len(cs)
        for reason in ('truncated','nontruncated_invalid'):
            out[prefix+'invalid/'+reason]=sum(not c['valid'] and (c['completion']['finish_reason']=='length')==(reason=='truncated') for c in cs)
        if cs:
            out[prefix+'invalid_rate']=sum(not c['valid'] for c in cs)/len(cs)
            out[prefix+'truncation_rate']=sum(c['completion']['finish_reason']=='length' for c in cs)/len(cs)
            out[prefix+'mean_output_tokens']=sum(len(c.get('response_ids',[])) or c.get('usage',{}).get('completion_tokens',0) for c in cs)/len(cs)
        if done:
            out[prefix+'terminal_player_utility_mean']=sum(sum(g['terminal_utility'])/len(g['terminal_utility']) for g in done)/len(done)
            out[prefix+'terminal_team_utility_mean']=sum(sum(g['terminal_utility']) for g in done)/len(done)
        for side,fn in [('lower',min),('upper',max)]:
            out[prefix+'cohort_player_utility_'+side]=sum(sum(g['terminal_utility'])/len(g['terminal_utility']) if g['status']=='terminal' else sum(sum(fn(0,v) for v in p) for p in g['reset']['realized_world'])/g['reset']['players'] for g in gs)/len(gs)
        proposals=[c for c in cs if c['valid'] and c.get('action') and 'action' in c['action']]
        if proposals:
            for action in ('OFFER','PASS','INVESTIGATE'):
                out[prefix+action.lower()+'_rate']=sum(c['action']['action']==action for c in proposals)/len(proposals)
    return out


class Validator:
    def __init__(self,data,generate,seed=42,concurrency=16,bp_tasks=32,game_resets=8):
        if min(concurrency,bp_tasks,game_resets)<1:raise ValueError('Positive validation sizes required')
        self.data=data;self.generate=generate;self.seed=seed;self.concurrency=concurrency
        self.tasks=[t for t in data['bp_validation'] if t.get('periodic_validation')] or select_bp(data['bp_validation'],bp_tasks)
        self.resets=select_resets(data['selfplay_validation'],game_resets)

    def run(self):
        from training.social_mixed.prompt_clarification import request
        from training.b_sft.social_bp_training import reward
        bp=[];jobs=[]
        for task in self.tasks:
            if task.get('paired_view'):
                from training.social_mixed.paired_requests import request as render
            else:render=request
            req=render(task,'action_tools',task.get('name_variant',0));req['seed']=seed_for(self.seed,VERSION,'bp',task['id'],0)
            req['temperature']=0.0
            jobs.append((task,req))
        for offset in range(0,len(jobs),self.concurrency):
            batch=jobs[offset:offset+self.concurrency];answers=self.generate([j[1] for j in batch])
            if len(answers)!=len(batch):raise RuntimeError('Missing validation answers')
            for (task,req),answer in zip(batch,answers):
                bp.append(dict(answer,task=task,replica=0,request=req,score=reward(task,answer['completion'])))
        if getattr(self,'static_only',False):
            games=[];calls=[];metrics=summarize_bp(bp)
        elif getattr(self,'calbench_development',False):
            from training.social_mixed.calbench_validation import run
            games,calls,game_metrics,calbench_protocol=run(self.generate,self.seed)
            metrics=summarize_bp(bp)|game_metrics
        else:
            games=[];calls=[]
            episodes=[Episode(r,f'{VERSION}:current_team:{r["id"]}',0,self.seed) for r in self.resets]
            while episodes:
                for offset in range(0,len(episodes),self.concurrency):
                    batch=episodes[offset:offset+self.concurrency]
                    requests=[dict(ep.request(),temperature=0.0) for ep in batch]
                    outputs=self.generate(requests)
                    if len(outputs)!=len(batch):raise RuntimeError('Missing game validation answers')
                    for ep,answer in zip(batch,outputs):
                        ep.accept(answer);c=ep.calls[-1];c.update(evaluation_game=ep.group,evaluation_role='current_team');calls.append(c)
                games.extend(dict(ep.summary(),condition='current_team') for ep in episodes if ep.status!='running')
                episodes=[ep for ep in episodes if ep.status=='running']
            metrics=summarize_bp(bp)|summarize_games(games,calls)
        coverage=Counter(k for t in self.tasks for k in cells(t))
        protocol=dict(bp_temperature=0.0,sp_temperature=0.0,coverage=dict(coverage),missing_diagnostics=[k for k in ('P4/result_use','B3/update') if not coverage[k]],version=VERSION,bp_tasks=len(self.tasks),bp_replicas=1,bp_ids=[t['id'] for t in self.tasks],
            reset_ids=[r['id'] for r in self.resets],condition='current_team',seed=self.seed,
            data_sha256=hashlib.sha256(json.dumps(self.data,sort_keys=True).encode()).hexdigest(),
            caveats='Development only. Team behavior, not fixed-opponent improvement. Terminal means are conditional on completion; report bounds alongside. No B→P composition claim. Infrastructure errors abort validation, never score zero.')
        if getattr(self,'calbench_development',False):
            protocol.update(calbench=calbench_protocol,reset_ids=[],sp_temperature=None)
        if getattr(self,'static_only',False):
            protocol.update(condition='static_obp',reset_ids=[],sp_temperature=None,interaction_enabled=False)
        return dict(protocol=protocol,metrics=metrics,bp_calls=bp,game_calls=calls,games=games)


def persist(root,report,step,training_tokens,tracker):
    folder=Path(root)/'validation';folder.mkdir(exist_ok=True)
    metrics={'eval/'+k:v for k,v in report['metrics'].items()}
    metrics.update({'system/step':step,'eval/completed_updates':step+1,'training_response_tokens':training_tokens})
    report=dict(report,optimizer_step=step,completed_updates=step+1,training_response_tokens=training_tokens)
    (folder/f'step-{step+1}.json').write_text(json.dumps(report)+'\n')
    with (Path(root)/'metrics.jsonl').open('a') as f:f.write(json.dumps(metrics)+'\n')
    tracker.log(metrics,step=step+1)
    return metrics
