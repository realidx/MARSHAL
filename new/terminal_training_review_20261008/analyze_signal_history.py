"""Track each selected question through all 22 sampled exposure cycles.

No model calls or oracle re-solving. Reads the original 915731 units/calls/games
and checks their hashes against the frozen training manifest.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def entropy(counts):
    import math
    total=sum(counts.values())
    return -sum(n/total*math.log2(n/total) for n in counts.values()) if total else None


def classify(events):
    states=[e['signal'] for e in events]
    if 'active' not in states:
        return 'always_all_correct' if set(states)=={'all_correct'} else 'always_all_zero' if set(states)=={'all_zero'} else 'always_inactive_reward_switches'
    return 'intermittent' if any(s!='active' for s in states) else 'always_active'


def aggregate_actions(events):
    out=Counter()
    for e in events:out.update(e['root_valid_action_counts'])
    return dict(sorted(out.items()))


def modes(counts):
    return sorted(k for k,v in counts.items() if v==max(counts.values())) if counts else []


def plot(question_records,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Patch
    order={'always_all_zero':0,'always_all_correct':1,'always_inactive_reward_switches':2,'intermittent':3,'always_active':4}
    ordered=sorted(question_records,key=lambda r:(order[r['classification']],r['active_exposures'],r['slice_id']))
    states={'all_zero':0,'active':1,'all_correct':2}
    fig,axes=plt.subplots(1,2,figsize=(14,11),sharey=True,constrained_layout=True)
    colors=['#d66b58','#407bb5','#70a774']
    axes[0].imshow([[states[e['signal']] for e in r['events']] for r in ordered],
        cmap=ListedColormap(colors),norm=BoundaryNorm([-.5,.5,1.5,2.5],3),aspect='auto',interpolation='nearest')
    im=axes[1].imshow([[e['root_correct']/8 for e in r['events']] for r in ordered],
        cmap='viridis',vmin=0,vmax=1,aspect='auto',interpolation='nearest')
    axes[0].set_title('Whole-group task signal');axes[1].set_title('Root decision correctness, out of 8 replicas')
    axes[0].legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,['All rewards 0; task A=0','Task A nonzero','All rewards 1; task A=0'])],
        loc='upper left',bbox_to_anchor=(0,1.11),fontsize=8,ncol=1)
    fig.colorbar(im,ax=axes[1],label='Root correct fraction',shrink=.5)
    for ax in axes:
        ax.set_xticks(range(22),range(1,23));ax.set_xlabel('Question exposure cycle (100 questions per cycle)')
        for boundary in [13.5,20.5,26.5,97.5]:ax.axhline(boundary,color='white',lw=1)
    axes[0].set_yticks(range(0,100,5),[str(i+1)+': '+ordered[i]['slice_id'][:8]+(' *' if ordered[i]['information_positive'] else '') for i in range(0,100,5)],fontsize=8)
    axes[0].set_ylabel('Question row; * denotes information-positive entrance')
    fig.suptitle('Job 915731: 100 questions tracked through all 22 exposures',fontsize=14)
    fig.savefig(out/'history.png',dpi=180);fig.savefig(out/'history.pdf');plt.close(fig)
    (out/'heatmap_row_order.json').write_text(json.dumps([dict(row=i+1,slice_id=r['slice_id'],classification=r['classification']) for i,r in enumerate(ordered)],indent=2)+'\n')


def main():
    cli=argparse.ArgumentParser(__doc__)
    cli.add_argument('--run',type=Path,required=True)
    cli.add_argument('--output',type=Path,default=Path(__file__).parent/'signal_history')
    cli.add_argument('--no-plot',action='store_true')
    args=cli.parse_args();run=args.run;out=args.output;out.mkdir(parents=True,exist_ok=True)
    bundle=next(b for b in json.loads((ROOT/'new/terminal_hf_test_calbench_20261008/raw/MANIFEST.json').read_text())['bundles'] if b['name']=='training-915731')
    specs={s['path']:s for s in bundle['files']}
    def checked(path):
        blob=path.read_bytes();key=str(Path(run.name)/path.relative_to(run));spec=specs[key]
        assert len(blob)==spec['bytes'] and hashlib.sha256(blob).hexdigest()==spec['sha256'],key
        return [json.loads(line) for line in blob.splitlines()]
    selection=ROOT/'new/local_data/strategic_slices_terminal_selected_v4'
    complete=json.loads((selection/'COMPLETE.json').read_text())
    for name,sha in complete['files'].items():assert hashlib.sha256((selection/name).read_bytes()).hexdigest()==sha,name
    metadata={r['id']:r for r in rows(selection/'candidates.jsonl')}
    d_metrics={r['measurement']['slice_id']:r for r in rows(selection/'metrics.jsonl')}
    protected=set(json.loads((selection/'SELECTION.json').read_text())['protected_ids'])
    history=defaultdict(list);prompt_values={}
    for step in range(550):
        units=defaultdict(list);calls=defaultdict(list);games=defaultdict(list)
        for u in checked(run/f'units/step-{step}.jsonl'):units[u['group']].append(u)
        for c in checked(run/f'calls/step-{step}.jsonl'):calls[c['group']].append(c)
        for g in checked(run/f'games/step-{step}.jsonl'):games[g['group']].append(g)
        for gid,us in units.items():
            sid=us[0]['slice_id'];cs=calls[gid];gs=games[gid]
            assert len(us)==8 and len(gs)==8
            roots={}
            for c in cs:roots.setdefault(c['unit'],c)
            assert len(roots)==8
            assert len({c['request']['seed'] for c in roots.values()})==8
            assert all(c['request']['temperature']==1. for c in cs)
            assert len({c['prompt_sha256'] for c in roots.values()})==1
            assert len({(g['member_index'],g['world_index']) for g in gs})==1
            rs=[r for u in us for r in u['step_rewards']]
            active=any(abs(r-u['baseline'])>1e-12 for u in us for r in u['step_rewards'])
            assert active==any(abs(c['task_advantage'])>1e-12 for c in cs)
            signal='active' if active else 'all_correct' if all(rs) else 'all_zero'
            valid_roots=[c for c in roots.values() if c['protocol_status']=='ok']
            ac=Counter(str(c['action_index']) for c in valid_roots)
            root_rewards=[c['binary_reward'] for c in roots.values()]
            hashes={c['prompt_sha256'] for c in roots.values()}
            for c in roots.values():
                key=(sid,c['prompt_sha256']);q=c['oracle_step']['Q']
                if key in prompt_values:assert len(q)==len(prompt_values[key]) and max(abs(a-b) for a,b in zip(q,prompt_values[key]))<1e-7
                else:prompt_values[key]=q
            cursor=int(gid.split(':')[1]);history[sid].append(dict(
                completed_updates=step+1,cursor=cursor,cycle=cursor//100+1,group=gid,signal=signal,
                protocol_active=any(c['protocol_status']!='ok' for c in cs),
                root_reward_contrast=min(root_rewards)!=max(root_rewards),root_correct=sum(root_rewards),
                root_prompt_sha256=next(iter(hashes)),root_valid_action_counts=dict(ac),root_modal_actions=modes(ac),
                root_unique_request_seeds=len({c['request']['seed'] for c in roots.values()}),
                root_exact_response_variants=len({tuple(c['response_ids']) for c in roots.values()}),
                root_optimal_actions=sorted({str(a) for c in roots.values() for a in c['oracle_step']['optimal_indices']}),
                root_Q_span=max(next(iter(roots.values()))['oracle_step']['Q'])-min(next(iter(roots.values()))['oracle_step']['Q']),
                root_valid_gap_counts=dict(Counter(str(round(c['oracle_step']['gap'],8)) for c in valid_roots)),
                root_status_counts=dict(Counter(c['protocol_status'] for c in roots.values())),
                root_mean_response_tokens=sum(len(c['response_ids']) for c in roots.values())/8,
                decision_calls=len(cs),correct_calls=sum(rs),call_status_counts=dict(Counter(c['protocol_status'] for c in cs)),
                member_index=gs[0]['member_index'],world_index=gs[0]['world_index']))
    question_records=[]
    for sid,events in sorted(history.items()):
        events.sort(key=lambda e:e['cycle']);assert [e['cycle'] for e in events]==list(range(1,23))
        row=metadata[sid];ds=d_metrics[sid];first=aggregate_actions(events[:4]);last=aggregate_actions(events[-4:])
        combined=aggregate_actions(events);per_prompt=defaultdict(set)
        for e in events:per_prompt[e['root_prompt_sha256']].update(e['root_valid_action_counts'])
        window=list(e['signal']!='active' for e in events)
        streak=best_streak=0
        for zero in window:
            streak=streak+1 if zero else 0;best_streak=max(streak,best_streak)
        rec=dict(slice_id=sid,parent_id=row['parent_id'],family=row['family'],k=row['k'],entry_kind=row['decision_kind'],
            information_positive=row['information_positive'],protected=sid in protected,classification=classify(events),
            states=''.join('+' if e['signal']=='active' else '1' if e['signal']=='all_correct' else '0' for e in events),
            active_exposures=sum(e['signal']=='active' for e in events),
            all_correct_exposures=sum(e['signal']=='all_correct' for e in events),all_zero_exposures=sum(e['signal']=='all_zero' for e in events),
            protocol_active_exposures=sum(e['protocol_active'] for e in events),
            root_contrast_exposures=sum(e['root_reward_contrast'] for e in events),root_correct=sum(e['root_correct'] for e in events),
            root_valid=sum(sum(e['root_valid_action_counts'].values()) for e in events),
            last5_active=sum(e['signal']=='active' for e in events[-5:]),max_inactive_streak=best_streak,
            distinct_root_prompts=len(per_prompt),same_prompt_multiple_valid_actions=any(len(actions)>1 for actions in per_prompt.values()),
            first4_root_action_counts=first,last4_root_action_counts=last,all_root_action_counts=combined,
            first4_root_modal_actions=modes(first),last4_root_modal_actions=modes(last),
            first_last_modal_sets_disjoint=bool(first and last and set(modes(first)).isdisjoint(modes(last))),
            root_action_entropy_bits=entropy(combined),
            D_root_value_contrast=ds['measurement']['root_value_contrast'],
            D_root_mixed_optimal_suboptimal=ds['measurement']['root_mixed_optimal_suboptimal'],
            D_any_step_value_contrast=ds['trajectory']['any_step_value_contrast'],
            D_gap_completion_contrast=ds['trajectory']['decision_gap_or_completion_contrast'],events=events)
        question_records.append(rec)
    cycles=[];last_zero=set();last_states={};total_transitions=Counter()
    for cycle in range(1,23):
        current={r['slice_id']:r['events'][cycle-1]['signal'] for r in question_records}
        zero={sid for sid,s in current.items() if s!='active'}
        transitions=Counter((last_states[sid],s) for sid,s in current.items()) if cycle>1 else Counter()
        total_transitions.update(transitions)
        cycles.append(dict(cycle=cycle,states=dict(Counter(current.values())),
            became_inactive=len(zero-last_zero) if cycle>1 else None,became_active=len(last_zero-zero) if cycle>1 else None,
            inactive_jaccard=len(zero&last_zero)/len(zero|last_zero) if cycle>1 else None,
            transitions={a+' -> '+b:n for (a,b),n in transitions.items()}))
        last_zero=zero;last_states=current
    forever=[r for r in question_records if r['active_exposures']==0]
    wrong=[r for r in forever if r['classification']=='always_all_zero']
    info=[r for r in question_records if r['information_positive']]
    summary=dict(protocol='Question-level observed histories, no inference or oracle recomputation; reward zero includes protocol failure.',
        questions=len(question_records),cycles=22,classification=dict(Counter(r['classification'] for r in question_records)),
        active_exposure_histogram=dict(sorted(Counter(r['active_exposures'] for r in question_records).items())),
        last5_inactive_questions=sum(r['last5_active']==0 for r in question_records),
        last5_inactive_but_previously_active=sum(r['last5_active']==0 and r['active_exposures']>0 for r in question_records),
        permanent_inactive_group_share=len(forever)*22/1501,
        always_all_zero_details=dict(questions=len(wrong),root_calls=len(wrong)*176,
            valid_root_calls=sum(r['root_valid'] for r in wrong),
            last4_exactly_one_valid_action_questions=sum(len(r['last4_root_action_counts'])==1 and sum(r['last4_root_action_counts'].values())==32 for r in wrong),
            proposal_questions_with_multiple_sampled_Q_gaps=sum(len({gap for e in r['events'] for gap in e['root_valid_gap_counts']})>1 for r in wrong if r['entry_kind']=='proposal'),
            groups_with_sampled_Q_gap_contrast=sum(len(e['root_valid_gap_counts'])>1 for r in wrong for e in r['events']),
            D_root_mixed_optimal_suboptimal=sum(r['D_root_mixed_optimal_suboptimal'] for r in wrong)),
        information_root_signal=dict(questions=len(info),task_active_groups=sum(r['active_exposures'] for r in info),
            never_root_correct_questions=sum(r['root_correct']==0 for r in info),
            root_correct=sum(r['root_correct'] for r in info),root_reward_contrast_groups=sum(r['root_contrast_exposures'] for r in info)),
        forever_inactive=dict(questions=len(forever),protected=sum(r['protected'] for r in forever),
            D_root_value_contrast=sum(r['D_root_value_contrast'] for r in forever),
            D_root_mixed_optimal_suboptimal=sum(r['D_root_mixed_optimal_suboptimal'] for r in forever),
            D_any_step_value_contrast=sum(r['D_any_step_value_contrast'] for r in forever),
            same_prompt_multiple_valid_actions=sum(r['same_prompt_multiple_valid_actions'] for r in forever),
            first_last_modal_sets_disjoint=sum(r['first_last_modal_sets_disjoint'] for r in forever),
            by_class={c:dict(n=sum(r['classification']==c for r in forever),
                same_prompt_multiple_valid_actions=sum(r['same_prompt_multiple_valid_actions'] for r in forever if r['classification']==c),
                first_last_modal_sets_disjoint=sum(r['first_last_modal_sets_disjoint'] for r in forever if r['classification']==c),
                protocol_active_exposures=sum(r['protocol_active_exposures'] for r in forever if r['classification']==c),
                k_counts=dict(Counter(r['k'] for r in forever if r['classification']==c)))
                for c in sorted({r['classification'] for r in forever})}),
        transitions={a+' -> '+b:n for (a,b),n in total_transitions.items()},cycles_detail=cycles,
        information_positive=[{k:v for k,v in r.items() if k!='events'} for r in question_records if r['information_positive']])
    assert sum(r['active_exposures'] for r in question_records)==699
    assert sum(r['all_correct_exposures'] for r in question_records)==865
    assert sum(r['all_zero_exposures'] for r in question_records)==636
    (out/'questions.json').write_text(json.dumps(question_records,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    fields=['slice_id','classification','states','active_exposures','all_correct_exposures','all_zero_exposures','root_contrast_exposures','root_correct','root_valid','last5_active','same_prompt_multiple_valid_actions','first_last_modal_sets_disjoint','D_root_value_contrast','D_root_mixed_optimal_suboptimal','D_any_step_value_contrast','protected','k','entry_kind','information_positive']
    with (out/'questions.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(question_records)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('cycles_detail','information_positive')},indent=2))
    if not args.no_plot:plot(question_records,out)


if __name__=='__main__':main()
