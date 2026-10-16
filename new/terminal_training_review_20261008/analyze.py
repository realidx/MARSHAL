"""Reproduce the 915731 review from its hash-verified original archive.

python new/terminal_training_review_20261008/analyze.py --run /tmp/.../terminal-train-... \
    --output new/terminal_training_review_20261008
Use --extract to verify/extract the checked-in training archive first.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import statistics
import tarfile

ROOT = Path(__file__).resolve().parents[2]
RUN_NAME = 'terminal-train-qwen3-4b-instruct-single96-full-20261006'


def jsonl(path):
    with path.open() as f:
        for line in f:
            yield json.loads(line)


def extract(dest):
    base = ROOT / 'new/terminal_hf_test_calbench_20261008/raw'
    bundle = next(b for b in json.loads((base/'MANIFEST.json').read_text())['bundles'] if b['name']=='training-915731')
    archives = []
    for spec in bundle['archives']:
        blob = (base/spec['path']).read_bytes()
        assert len(blob)==spec['bytes'] and hashlib.sha256(blob).hexdigest()==spec['sha256']
        archives.append(blob)
    files = {f['path']: f for f in bundle['files']}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(b''.join(archives))) as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.removeprefix('./')
            target = dest/name
            assert target.resolve().is_relative_to(dest.resolve())
            blob = tar.extractfile(member).read(); spec = files[name]
            assert len(blob)==spec['bytes'] and hashlib.sha256(blob).hexdigest()==spec['sha256'], name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob); seen.add(name)
    assert seen==set(files)
    return dest/RUN_NAME


def frac(a, b):
    return a/b if b else None


def call_stats(calls):
    counts = Counter(); by_question = defaultdict(lambda: [0, 0]); roots = []
    seen = set()
    for c in calls:
        counts['calls'] += 1
        counts['tokens'] += len(c['response_ids'])
        counts['correct'] += c.get('binary_reward', c['oracle_step']['reward'])
        counts[c['protocol_status']] += 1
        q = c['oracle_step']['Q']; nonflat = max(q)-min(q)>1e-7
        counts['nonflat_calls'] += nonflat
        counts['nonflat_correct'] += nonflat*c['oracle_step']['reward']
        counts['task_nonzero_calls'] += abs(c.get('task_advantage', 0))>1e-12
        counts['act_only'] += c['text'].lstrip().startswith('<tool_call>')
        sid = c.get('task_id', c.get('slice_id'))
        by_question[sid][0] += c['oracle_step']['reward']; by_question[sid][1] += 1
        unit = c.get('unit', (sid, c['replica']))
        if unit not in seen:
            seen.add(unit); roots.append(c)
    root_valid = [c for c in roots if c['protocol_status']=='ok']
    root_actions = Counter(c['action_index'] for c in root_valid)
    return dict(counts, accuracy=frac(counts['correct'],counts['calls']),
        valid_accuracy=frac(counts['correct'],counts['ok']),
        nonflat_accuracy=frac(counts['nonflat_correct'],counts['nonflat_calls']),
        tokens_per_call=frac(counts['tokens'],counts['calls']),
        act_only_rate=frac(counts['act_only'],counts['calls']),
        question_macro_accuracy=statistics.mean(a/b for a,b in by_question.values()),
        distinct_questions=len(by_question), root_action_counts=dict(root_actions),
        root_calls=len(roots),root_flat_calls=sum(max(c['oracle_step']['Q'])-min(c['oracle_step']['Q'])<=1e-7 for c in roots))


def games_stats(games, metadata):
    by_kind = defaultdict(list); by_k = defaultdict(list)
    by_parent = defaultdict(list);by_information=defaultdict(list)
    for g in games:
        row = metadata[g['slice_id']]
        ok = int(g['status']=='terminal' and all(g['step_rewards']))
        by_kind[row['decision_kind']].append(ok); by_k[row['k']].append(ok)
        by_parent[g['parent_id']].append(ok)
        by_information['positive' if row['information_positive'] else 'other'].append(ok)
    return dict(episodes=len(games), completion_rate=sum(g['status']=='terminal' for g in games)/len(games),
        window_success=sum(g['status']=='terminal' and all(g['step_rewards']) for g in games)/len(games),
        by_entry_kind={k:dict(n=len(v),success=statistics.mean(v)) for k,v in by_kind.items()},
        by_k={k:dict(n=len(v),success=statistics.mean(v)) for k,v in by_k.items()},
        by_information={k:dict(n=len(v),success=statistics.mean(v)) for k,v in by_information.items()},
        parent_macro_success=statistics.mean(statistics.mean(v) for v in by_parent.values()))


def information_root_stats(calls,metadata):
    selected=[c for c in calls if metadata[c.get('task_id',c.get('slice_id'))]['information_positive']]
    roots={};groups=defaultdict(list)
    for c in selected:
        roots.setdefault(c['unit'],c)
        groups[c['group']].append(c)
    return dict(calls=len(selected),correct=sum(c['oracle_step']['reward'] for c in selected),
        root_calls=len(roots),root_correct=sum(c['oracle_step']['reward'] for c in roots.values()),
        groups=len(groups),task_active_groups=sum(any(abs(c['task_advantage'])>1e-12 for c in cs) for cs in groups.values()))


def plot(output, train, validation):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True, constrained_layout=True)
    x = [v['completed_updates'] for v in validation]
    for key, label in [('window_success','Window success'),('completion_rate','Completion'),('valid_accuracy','Accuracy on valid calls')]:
        axes[0].plot(x, [100*v[key] for v in validation], label=label)
    axes[0].set_ylabel('Validation (%)'); axes[0].legend(loc='lower right')
    for key, label in [('accuracy','Decision correctness'),('completion_rate','Completion'),('task_active_rate','Task-active groups')]:
        y = [100*statistics.mean(t[key] for t in train[max(0,i-24):i+1]) for i in range(len(train))]
        axes[1].plot(range(1,len(train)+1), y, label=label)
    axes[1].set_ylabel('Training, 25-update mean (%)'); axes[1].legend(loc='lower right')
    axes[2].plot(x,[v['tokens_per_call'] for v in validation],label='Validation tokens / call')
    axes[2].plot(range(1,len(train)+1),[statistics.mean(t['tokens_per_call'] for t in train[max(0,i-24):i+1]) for i in range(len(train))],label='Training tokens / call, 25-update mean')
    axes[2].set_ylabel('Response length (tokens)'); axes[2].set_xlabel('Completed optimizer updates');axes[2].legend()
    for ax in axes:
        ax.axvspan(140,240,color='orange',alpha=.10);ax.axvline(380,color='grey',ls=':',lw=1);ax.grid(alpha=.2)
    fig.suptitle('Job 915731: output instability, recovery and late validation drift')
    fig.savefig(output/'trend.png',dpi=180);fig.savefig(output/'trend.pdf');plt.close(fig)


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--run',type=Path)
    parser.add_argument('--extract',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent)
    parser.add_argument('--no-plot',action='store_true')
    args=parser.parse_args()
    run=extract(args.extract) if args.extract else args.run
    if run is None:parser.error('Supply --run or --extract')
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    from training.strategic_slices.common import digest, file_hash
    pool=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    selection=ROOT/'new/local_data/strategic_slices_terminal_selected_v4'
    experiment=json.loads((run/'experiment.json').read_text())
    assert digest(dict(pool=file_hash(pool/'manifest.json'),selection=file_hash(selection/'COMPLETE.json')))==experiment['checks']['dataset_sha256']
    metadata={r['id']:r for r in jsonl(pool/'candidates.jsonl')}
    train_metrics=[m for m in jsonl(run/'metrics.jsonl') if 'generated_tokens' in m]
    validation=[]
    for path in sorted((run/'validation').glob('step-*.json'),key=lambda p:int(p.stem.split('-')[-1])):
        report=json.loads(path.read_text())
        stats=call_stats(report['slice_calls'])
        stats.update(games_stats(report['slice_games'],metadata))
        stats.update(completed_updates=report['completed_updates'],training_response_tokens=report['training_response_tokens'],
            generated_response_tokens=report['generated_response_tokens'],
            per_decision_accuracy=report['slices']['per_decision_accuracy'],
            full_game_metrics=report['full_games']['metrics'])
        validation.append(stats)
    blocks=[(0,100),(100,140),(140,240),(240,340),(340,400),(400,550)]
    block_calls={a:[] for a,b in blocks};block_games={a:[] for a,b in blocks};train=[];exposure=Counter()
    for m in train_metrics:
        step=m['system/step'];calls=list(jsonl(run/f'calls/step-{step}.jsonl'));games=list(jsonl(run/f'games/step-{step}.jsonl'))
        stats=call_stats(calls);stats.update(games_stats(games,metadata))
        stats.update(completed_updates=step+1,task_active_rate=m['task_active_groups']/m['groups'],
            protocol_active_rate=m['protocol_active_groups']/m['groups'],
            training_response_tokens=m['training_response_tokens'],all_task_zero=m['task_active_groups']==0,
            all_protocol_zero=m['protocol_active_groups']==0)
        train.append(stats);exposure.update({g['group'] for g in games})
        # Keep only compact score evidence; do not duplicate prompts/token arrays.
        compact=[{k:c[k] for k in ('response_ids','binary_reward','oracle_step','protocol_status','task_advantage','text','task_id','unit','group','replica','action_index')} for c in calls]
        for a,b in blocks:
            if a<=step<b:block_calls[a].extend(compact);block_games[a].extend(games)
    block_results=[];contrast_counts=Counter()
    for path in (run/'units').glob('step-*.jsonl'):
        groups=defaultdict(list)
        for unit in jsonl(path):groups[unit['group']].append(unit)
        for units in groups.values():
            averages=[statistics.mean(u['step_rewards']) for u in units]
            active=any(abs(v-u['baseline'])>1e-12 for u in units for v in u['step_rewards'])
            contrast=max(averages)-min(averages)>1e-12
            contrast_counts['trajectory_mean_contrast_groups']+=int(contrast)
            contrast_counts['task_active_without_mean_contrast_groups']+=int(active and not contrast)
            contrast_counts['all_rewards_one_groups']+=int(all(v==1 for u in units for v in u['step_rewards']))
            contrast_counts['all_rewards_zero_groups']+=int(all(v==0 for u in units for v in u['step_rewards']))
    for a,b in blocks:
        ms=train_metrics[a:b];stats=call_stats(block_calls[a]);stats.update(games_stats(block_games[a],metadata))
        groups=sum(m['groups'] for m in ms)
        stats.update(updates=[a+1,b],task_active_rate=sum(m['task_active_groups'] for m in ms)/groups,
            protocol_active_rate=sum(m['protocol_active_groups'] for m in ms)/groups,
            probability_warnings=sum(m['behavior_probability_warning'] for m in ms),
            mean_kl_weighted=statistics.mean(m['actor/kl_weighted'] for m in ms),
            mean_grad_norm=statistics.mean(m['actor_train/grad_norm'] for m in ms))
        stats['information_positive']=information_root_stats(block_calls[a],metadata)
        block_results.append(stats)
    # Remove nested checkpoint time from validation to avoid double counting.
    phase_records=list(jsonl(run/'phases.jsonl'));stack=[];exclusive=Counter();counts=Counter()
    for p in phase_records:
        if p['event']=='begin':stack.append([p['phase'],p['utc'],0.])
        elif p['event']=='end':
            name,start,nested=stack.pop();assert name==p['phase']
            duration=p['seconds'];exclusive[name]+=duration-nested;counts[name]+=1
            if stack:stack[-1][2]+=duration
    assert not stack
    selected=list(jsonl(selection/'candidates.jsonl'))
    summary=dict(run='915731',dataset_sha256=experiment['checks']['dataset_sha256'],
        result=json.loads((run/'RESULT.json').read_text()),best=json.loads((run/'BEST_VALIDATION.json').read_text()),
        validation_passes=len(validation),post_baseline_validation_passes=len(validation)-1,
        phase_counts=dict(counts),phase_exclusive_seconds=dict(exclusive),
        phase_wall_seconds=phase_records[-1]['utc']-phase_records[0]['utc'],
        validation_response_tokens=sum(v['generated_response_tokens'] for v in validation),
        training_calls=sum(t['calls'] for t in train),groups=sum(m['groups'] for m in train_metrics),
        task_active_groups=sum(m['task_active_groups'] for m in train_metrics),
        reward_contrast=dict(contrast_counts),
        all_task_zero_updates=sum(t['all_task_zero'] for t in train),
        all_task_and_protocol_zero_updates=sum(t['all_task_zero'] and t['all_protocol_zero'] for t in train),
        groups_per_cycle=dict(Counter(int(k.split(':')[1])//100 for k in exposure)),
        per_question_exposure_distribution=dict(Counter(Counter(k.split(':')[2] for k in exposure).values())),
        selection_information_positive=sum(bool(r['information_positive']) for r in selected),
        validation_information_positive=sum(bool(r['information_positive']) for r in metadata.values() if r['split']=='validation'),
        blocks=block_results,validation=validation)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (output/'training_updates.json').write_text(json.dumps(train,indent=2)+'\n')
    fields=['completed_updates','training_response_tokens','window_success','completion_rate','accuracy','valid_accuracy','nonflat_accuracy','tokens_per_call','act_only_rate','parent_macro_success']
    with (output/'validation.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(validation)
    if not args.no_plot:plot(output,train,validation)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('blocks','validation','best','groups_per_cycle')},indent=2))


if __name__=='__main__':main()
