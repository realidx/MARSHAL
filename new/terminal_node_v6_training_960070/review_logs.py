"""Audit job 960070 directly from its archive; do not unpack large call logs.

Run from the repository root with Python 3.10+ (numpy required).
Outputs contain aggregates and compact per-question records, not raw prompts.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import tarfile

import numpy as np


def read_jsonl(data):
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def plot_review(result, metrics, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    bins=[]
    for start in range(0,len(metrics),10):
        rows=metrics[start:start+10]
        bins.append(dict(x=sum(r['system/step']+1 for r in rows)/len(rows),
            active=sum(r['task_active_groups'] for r in rows)/sum(r['groups'] for r in rows),
            accuracy=sum(r['binary_correct_calls'] for r in rows)/sum(r['rows'] for r in rows),
            root=sum(r['root_correct_calls'] for r in rows)/sum(r['root_decision_calls'] for r in rows),
            length=sum(r['generated_tokens'] for r in rows)/sum(r['rows'] for r in rows)))
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    x=[b['x'] for b in bins]
    a=axes[0,0]
    a.plot(x,[b['accuracy']*100 for b in bins],label='Train all decisions')
    a.plot(x,[b['root']*100 for b in bins],label='Train entry decisions')
    a.plot([v['completed_updates'] for v in result['validations']],
        [v['window_success']*100 for v in result['validations']],'o-',label='Validation window success')
    a.set(ylabel='Percent',xlabel='Completed optimizer updates',ylim=(0,100),title='Learning on different cohorts')
    a.legend(fontsize=8)
    a=axes[0,1]
    a.plot(x,[b['active']*100 for b in bins],color='tab:red')
    a.set(ylabel='Groups with nonzero task advantage (%)',xlabel='Completed optimizer updates',
        title='Task-signal rate rapidly falls',ylim=(0,35))
    a=axes[1,0]
    a.plot(x,[b['length'] for b in bins])
    a.set(xlabel='Completed optimizer updates',ylabel='Response tokens / answer',title='Answers become short tool calls')
    a=axes[1,1]
    ph=result['phase_seconds']
    restore=result['last_cache']['reference_restore_seconds_total']
    labels=['Rollout','Optimizer','Weight sync','Reference log-probs','Validation + save']
    values=[ph['rollout'],ph['optimizer_update'],ph['weight_sync'],
        ph['reference_log_probs'],ph['terminal_validation']+ph['checkpoint']]
    a.barh(labels[::-1],[v/3600 for v in values[::-1]],color='tab:blue')
    a.set(xlabel='Hours',title='Time by phase (no double-counting)')
    a.text(.98,.08,f'Tree restore counter: {restore/3600:.2f} h*\n(shared training/validation counter)',
        ha='right',va='bottom',transform=a.transAxes,fontsize=8)
    for ax in axes.flat:ax.grid(alpha=.2,axis='x' if ax==axes[1,1] else 'y')
    fig.savefig(output/'training_review.png',dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='new/terminal_node_v6_training_960070/review_20261017')
    parser.add_argument('--plot', action='store_true', help='Also render the summary figure (matplotlib).')
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    selected = {r['id']: r for r in read_jsonl(Path('new/local_data/strategic_slices_terminal_selected_v4/candidates.jsonl').read_bytes())}
    units, games, metrics, phases, warnings, validations = {}, {}, [], [], [], []
    call_stats, group_stats, failures = {}, {}, Counter()
    examples = []
    source = {}
    with tarfile.open(bundle/'raw/training-960070.tar.gz.part000', 'r|gz') as archive:
        for member in archive:
            name = member.name
            if name.startswith('run/calls/'):
                step = int(Path(name).stem.split('-')[-1])
                calls = read_jsonl(archive.extractfile(member).read())
                groups = defaultdict(list)
                cs = Counter(calls=len(calls))
                group_stats[step] = gs = []
                for call in calls:
                    groups[call['group']].append(call)
                    q = call['oracle_step']['Q']
                    ai = call['action_index']
                    valid = call['valid']
                    expected_reward = (q[ai] if valid else min(q)) - max(q)
                    if abs(call['task_reward'] - expected_reward) > 1e-10:
                        failures['reward'] += 1
                    if call['binary_reward'] != int(valid and max(q)-q[ai] <= 1e-7):
                        failures['binary'] += 1
                    if call['decision_index'] == 0 and q != selected[call['task_id']]['members'][0]['root_Q']:
                        failures['frozen_root_Q'] += 1
                    if len(call['response_ids']) != len(call['behavior_log_probs']):
                        failures['behavior_length'] += 1
                    if not np.isfinite(call['behavior_log_probs']).all():
                        failures['nonfinite_behavior'] += 1
                    if call['request']['temperature'] != 1.:
                        failures['temperature'] += 1
                    if any(call[k] != 1. for k in ('loss_weight', 'task_weight', 'protocol_weight', 'kl_weight')):
                        failures['weight'] += 1
                    state = json.loads(call['request']['messages'][-1]['content'])
                    action = state['legal_actions'][ai]['action'] if valid else {}
                    kind = action.get('response', action.get('action', 'INVALID'))
                    cs['action/'+kind] += 1
                    cs['tokens'] += len(call['response_ids'])
                    cs['prompt_tokens'] += len(call['prompt_ids'])
                    cs['correct'] += call['binary_reward']
                    cs['valid'] += valid
                    cs['action_index_1'] += valid and ai == 1
                    cs['truncated'] += call['protocol_status'] == 'truncated'
                    cs['sum_response_logp'] += sum(call['behavior_log_probs'])
                    cs['root_calls'] += call['decision_index'] == 0
                    cs['root_correct'] += call['decision_index'] == 0 and call['binary_reward']
                    cs['root_info_calls'] += call['decision_index'] == 0 and selected[call['task_id']]['information_positive']
                    cs['root_info_correct'] += call['decision_index'] == 0 and selected[call['task_id']]['information_positive'] and call['binary_reward']
                for group, candidates in groups.items():
                    candidates.sort(key=lambda c: c['replica'])
                    first = candidates[0]
                    rewards = np.array([c['task_reward'] for c in candidates])
                    binary = [c['binary_reward'] for c in candidates]
                    std = float(rewards.std(ddof=1))
                    advantages = np.zeros(len(candidates)) if np.ptp(rewards) <= 1e-7 else (rewards-rewards.mean())/(std+1e-8)
                    if len(candidates) != 8 or [c['replica'] for c in candidates] != list(range(8)):
                        failures['group_size'] += 1
                    for key in ('prompt_ids', 'prompt_sha256', 'scoring_sha256', 'oracle_step'):
                        if key == 'oracle_step':
                            same = all(c[key]['Q'] == first[key]['Q'] and c[key]['posterior'] == first[key]['posterior'] for c in candidates)
                        else:
                            same = all(c[key] == first[key] for c in candidates)
                        if not same:
                            failures['same_context/'+key] += 1
                    if len({c['request']['seed'] for c in candidates}) != 8:
                        failures['independent_seeds'] += 1
                    for c, expected in zip(candidates, advantages):
                        if abs(c['task_advantage']-expected) > 1e-9:
                            failures['advantage'] += 1
                        if c['protocol_advantage'] != (0. if c['valid'] else -.2):
                            failures['protocol_advantage'] += 1
                    chosen = [c for c in candidates if c['selected_for_continuation']]
                    if len(chosen) != 1:
                        failures['selected_count'] += 1
                    first_state = json.loads(first['request']['messages'][-1]['content'])
                    kind = 'response' if first_state['pending_offer'] else 'proposal'
                    menu = [a['action'] for a in first_state['legal_actions']]
                    action_kind = lambda a: a.get('response', a.get('action', 'UNKNOWN'))
                    unique = len({c['action_index'] for c in candidates if c['valid']})
                    q = first['oracle_step']['Q']
                    g = dict(step=step, group=group, slice_id=first['task_id'], parent_id=first['parent_id'],
                        depth=first['decision_index'], remaining_k=first['remaining_k'], node=first['node'],
                        kind=kind, n_players=first_state['public_state']['n_players'],
                        prompt_sha256=first['prompt_sha256'], scoring_sha256=first['scoring_sha256'],
                        task_active=bool(np.ptp(rewards)>1e-7), protocol_active=any(not c['valid'] for c in candidates),
                        all_correct=all(binary), all_wrong=not any(binary), binary_mixed=min(binary)!=max(binary),
                        unique_sampled_actions=unique, legal_menu_size=len(q), oracle_span=max(q)-min(q),
                        regret_mean=float(-rewards.mean()), valid_calls=sum(c['valid'] for c in candidates),
                        correct_calls=sum(binary), sampled_actions=[c['action_index'] for c in candidates],
                        optimal_action_kinds=sorted({action_kind(menu[i]) for i,v in enumerate(q) if max(q)-v<=1e-7}),
                        sampled_action_kinds=[action_kind(menu[c['action_index']]) if c['valid'] else 'INVALID' for c in candidates],
                        selected_replica=chosen[0]['replica'], info_positive=bool(selected[first['task_id']]['information_positive']))
                    gs.append(g)
                    if step >= 250 and g['all_wrong'] and not g['task_active'] and g['oracle_span']>1e-7 and len(examples)<8:
                        examples.append(dict(g, Q=q, text=first['text'][:300], legal_actions=first_state['legal_actions']))
                call_stats[step] = dict(cs)
            elif name.startswith('run/units/'):
                units[int(Path(name).stem.split('-')[-1])] = read_jsonl(archive.extractfile(member).read())
            elif name.startswith('run/games/'):
                games[int(Path(name).stem.split('-')[-1])] = read_jsonl(archive.extractfile(member).read())
            elif name.startswith('run/validation/'):
                validations.append(json.loads(archive.extractfile(member).read()))
            elif name in ('run/metrics.jsonl', 'run/phases.jsonl', 'run/probability_warnings.jsonl'):
                data = read_jsonl(archive.extractfile(member).read())
                if name.endswith('/metrics.jsonl'):
                    metrics = data
                elif name.endswith('/phases.jsonl'):
                    phases = data
                else:
                    warnings = data
            elif name == 'run/source_manifest.json':
                source = json.loads(archive.extractfile(member).read())
    training = [m for m in metrics if 'generated_tokens' in m]
    completed = {m['system/step'] for m in training}
    all_groups = [g for step in sorted(completed) for g in group_stats[step]]
    per_question = []
    for sid in sorted(selected):
        question = selected[sid]
        groups = [g for g in all_groups if g['slice_id'] == sid]
        roots = [g for g in groups if g['depth'] == 0]
        tail = [g for g in roots if g['step'] >= 250]
        per_question.append(dict(slice_id=sid, parent_id=question['parent_id'], k=question['k'],
            information_positive=question['information_positive'], entries=len(roots), node_groups=len(groups),
            task_active_groups=sum(g['task_active'] for g in groups), root_active_groups=sum(g['task_active'] for g in roots),
            distinct_root_prompts=len({g['prompt_sha256'] for g in roots}),
            distinct_root_scoring=len({g['scoring_sha256'] for g in roots}),
            root_accuracy=sum(g['correct_calls'] for g in roots)/(8*len(roots)) if roots else None,
            tail_entries=len(tail), tail_active=sum(g['task_active'] for g in tail),
            tail_correct=sum(g['correct_calls'] for g in tail), tail_calls=len(tail)*8,
            tail_all_wrong=bool(tail) and all(g['all_wrong'] for g in tail),
            tail_all_correct=bool(tail) and all(g['all_correct'] for g in tail)))
    for m in training:
        step=m['system/step'];cs=call_stats[step];gs=group_stats[step]
        if cs['tokens']!=m['generated_tokens'] or cs['calls']!=m['rows'] or len(gs)!=m['groups']:
            failures['metric_totals']+=1
        unit_by_id={u['group']:u for u in units[step]}
        for g in gs:
            u=unit_by_id[g['group']]
            if u['task_active']!=g['task_active'] or u['binary_correct']!=g['correct_calls'] or u['unique_legal_actions']!=g['unique_sampled_actions'] or u['selected_replica']!=g['selected_replica']:
                failures['unit_totals']+=1

    def aggregate(lo,hi):
        ms=[m for m in training if lo<=m['system/step']<hi]
        gs=[g for g in all_groups if lo<=g['step']<hi]
        total=lambda key:sum(m.get(key,0) for m in ms)
        calls=total('rows')
        return dict(start_step=lo,end_step_exclusive=hi,updates=len(ms),groups=len(gs),responses=calls,
            tokens=total('generated_tokens'),mean_response_tokens=total('generated_tokens')/calls,
            strict_accuracy=total('binary_correct_calls')/calls,
            task_active_groups=sum(g['task_active'] for g in gs),
            task_active_rate=sum(g['task_active'] for g in gs)/len(gs),
            zero_all_wrong_groups=sum(g['all_wrong'] and not g['task_active'] for g in gs),
            zero_all_correct_groups=sum(g['all_correct'] and not g['task_active'] for g in gs),
            flat_oracle_groups=sum(g['oracle_span']<=1e-7 for g in gs),
            single_sampled_action_groups=sum(g['unique_sampled_actions']==1 for g in gs),
            truly_single_legal_action_groups=sum(g['legal_menu_size']==1 for g in gs),
            continuous_only_active_groups=sum(g['task_active'] and not g['binary_mixed'] for g in gs),
            zero_task_updates=sum(m['task_active_groups']==0 for m in ms),
            kl_only_updates=sum(m['active_groups']==0 for m in ms),
            zero_task_updates_with_protocol=sum(m['task_active_groups']==0 and m['protocol_active_groups']>0 for m in ms),
            response_actions=dict(sum((Counter({k[7:]:v for k,v in call_stats[m['system/step']].items() if k.startswith('action/')}) for m in ms),Counter())),
            info_root_calls=total('information_positive_root_calls'),info_root_correct=total('information_positive_root_correct_calls'),
            collection_seconds=total('collection_seconds'),poll_seconds=total('generation_seconds'),q_seconds=total('oracle_action_value_seconds'))
    val_summaries=[]
    for d in sorted(validations,key=lambda v:v['training_response_tokens']):
        calls=d['slice_calls'];roots=[c for c in calls if c['decision_index']==0]
        val_summaries.append(dict(completed_updates=d['completed_updates'],tokens=d['training_response_tokens'],
            window_success=d['slices']['full_window_success_rate'],accuracy=d['slices']['per_decision_accuracy'],
            root_accuracy=d['slices']['decision_metrics']['root']['per_decision_accuracy'],
            mean_regret=d['slices']['decision_metrics']['all']['mean_regret_with_failure_worst_action'],
            completion=d['slices']['completion_rate'],root_information_calls=d['slices']['decision_metrics']['information_root']['calls'],
            all_action_1_root_accuracy=sum(len(c['oracle_step']['Q'])>1 and max(c['oracle_step']['Q'])-c['oracle_step']['Q'][1]<=1e-7 for c in roots)/len(roots),
            full_games={mode:vals['all'] for mode,vals in d['full_games']['metrics'].items()},
            evaluation_response_tokens=d['generated_response_tokens'],execution=d['execution']))
    phase_totals=Counter();phase_counts=Counter()
    for p in phases:
        if p['event']=='end':phase_totals[p['phase']]+=p['seconds'];phase_counts[p['phase']]+=1
    changed_source=[p for p,h in source.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
    result=dict(completed_updates=len(completed),tokens=sum(m['generated_tokens'] for m in training),
        unmatched_collection_steps=sorted(set(call_stats)-completed),audit_failures=dict(failures),
        source_files=len(source),local_source_different=changed_source,
        intervals=[aggregate(a,b) for a,b in [(0,10),(10,50),(50,100),(100,150),(150,200),(200,250),(250,307),(0,307)]],
        validations=val_summaries,phase_seconds=dict(phase_totals),phase_counts=dict(phase_counts),
        last_cache={k:v for k,v in training[-1].items() if k.startswith(('tree_cache','oracle_cache','reference_restore'))},
        warnings=[dict(step=w['step'],metrics={k:v for k,v in w['metrics'].items() if k.startswith('behavior_')}) for w in warnings],
        late_wrong_examples=examples,
        question_summary=dict(questions=len(per_question),entries_min=min(q['entries'] for q in per_question),
            entries_max=max(q['entries'] for q in per_question),
            task_never_active=sum(q['task_active_groups']==0 for q in per_question),
            tail_all_wrong=sum(q['tail_all_wrong'] for q in per_question),tail_all_correct=sum(q['tail_all_correct'] for q in per_question)))
    information = [g for g in all_groups if g['info_positive'] and g['depth']==0 and g['step']>=50]
    result['information_roots_from_step_50'] = dict(groups=len(information),
        correct=sum(g['correct_calls'] for g in information), calls=len(information)*8,
        optimal_action_kinds=dict(Counter(','.join(g['optimal_action_kinds']) for g in information)),
        sampled_action_kinds=dict(Counter(k for g in information for k in g['sampled_action_kinds'])))
    (output/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    with (output/'questions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(per_question[0]));w.writeheader();w.writerows(per_question)
    with (output/'groups.jsonl').open('w') as f:
        for g in all_groups:f.write(json.dumps(g,separators=(',',':'))+'\n')
    if args.plot:
        plot_review(result,training,output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('late_wrong_examples','warnings','validations')},indent=2))


if __name__=='__main__':
    main()
