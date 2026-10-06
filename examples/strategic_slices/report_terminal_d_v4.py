"""Summarize completed offline audits and the train-only selection."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.common import file_hash, write_json
from training.strategic_slices.terminal_d import load_dataset
from training.strategic_slices.terminal_analysis import EPS, require


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data',type=Path,default=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4'))
    cli.add_argument('--analysis',type=Path,default=Path('new/local_data/strategic_slices_terminal_d_v4_analysis'))
    cli.add_argument('--selection',type=Path,default=Path('new/local_data/strategic_slices_terminal_selected_v4'))
    cli.add_argument('--output',type=Path,default=Path('new/local_data/strategic_slices_terminal_d_v4_review'))
    args=cli.parse_args()
    for folder in (args.analysis,args.selection):
        for name,sha in json.loads((folder/'COMPLETE.json').read_text())['files'].items():
            require(file_hash(folder/name)==sha,'Evidence changed: '+name)
    data=load_dataset(args.data);rows={r['id']:r for r in data.candidates}
    metrics={r['slice_id']:r for r in map(json.loads,(args.analysis/'trajectory_metrics.jsonl').read_text().splitlines())}
    measured={r['slice_id']:r for r in map(json.loads,(args.analysis/'merged_slices.jsonl').read_text().splitlines())}
    trajectories=defaultdict(list)
    for p in (args.analysis/'parents').glob('*.json'):
        for game in json.loads(p.read_text())['result']['trajectories']:trajectories[game['slice_id']].append(game)
    # Same visible prompt within a fixed question must yield the same Q vector,
    # regardless of hidden-world realization or replica.
    checked=0
    for games in trajectories.values():
        prompts={}
        for game in games:
            for call in game['decisions']:
                prior=prompts.setdefault(call['prompt_sha256'],call['Q'])
                require(np.allclose(prior,call['Q'],atol=1e-10,rtol=0),'Same prompt acquired hidden-world-dependent Q')
                checked+=1
    strong_ids={cid for cid,m in metrics.items() if m['strong_acquisition']}
    strong_games=[g for cid in strong_ids for g in trajectories[cid]]
    calls=[c for g in strong_games for c in g['decisions']]
    queries=[c for c in calls if c['action'] and c['action'].get('action')=='INVESTIGATE']
    query_information=Counter();world_tables={}
    for game in strong_games:
        row=rows[game['slice_id']];pid=row['parent_id']
        if pid not in world_tables:world_tables[pid]=PrivateInvestigationRules(data.parents[pid]['raw']).worlds
        for call in game['decisions']:
            action=call['action']
            if not action or action.get('action')!='INVESTIGATE':continue
            support={world[action['player']][action['goal']] for wi,world in enumerate(world_tables[pid])
                     if call['posterior'][wi]>1e-12}
            key=('already_known' if len(support)==1 else 'uncertain')+('_suboptimal' if call['gap']>EPS else '_optimal')
            query_information[key]+=1
    strict=[c for c in calls if c['answer_sensitive']]
    acquisition=dict(slices=len(strong_ids),trajectories=len(strong_games),query_calls=len(queries),
        queried_preference_information=dict(query_information),
        optimal_query_calls=sum(c['gap']<=EPS for c in queries),suboptimal_query_calls=sum(c['gap']>EPS for c in queries),
        post_query_valid_calls=sum(c['after_model_query'] and c['gap'] is not None for c in calls),
        post_query_suboptimal_calls=sum(c['after_model_query'] and c['gap'] is not None and c['gap']>EPS for c in calls),
        answer_sensitive_calls=len(strict),answer_sensitive_valid=sum(c['gap'] is not None for c in strict),
        answer_sensitive_correct=sum(c['gap'] is not None and c['gap']<=EPS for c in strict),
        answer_sensitive_failures=sum(c['gap'] is None for c in strict))
    groups=[]
    for relation in data.entry_answer_relations:
        value=0.;valid_count=0
        for member in relation['members']:
            cs=[g['decisions'][0] for g in trajectories[member['candidate_id']] if g['decisions'][0]['gap'] is not None]
            require(cs,'Entry-answer member has no valid actions')
            qs=np.array(member['root_Q'])
            for c in cs:require(np.allclose(c['Q'],qs,atol=1e-9,rtol=0),'Entry group Q mismatch')
            value+=member['probability']*np.mean([qs[c['action_index']] for c in cs]);valid_count+=len(cs)
        groups.append(dict(id=relation['id'],split=relation['split'],S=relation['S'],
            valid_actions=valid_count,attempts=8*len(relation['members']),
            V_model_valid_actions_only=float(value),V_masked=relation['V_masked'],V_full=relation['V_full'],
            advantage_over_best_shared_action=float(value-relation['V_masked'])))
    selection=json.loads((args.selection/'SELECTION.json').read_text())
    selected={r['id'] for r in map(json.loads,(args.selection/'candidates.jsonl').read_text().splitlines())}
    counts={}
    for label in ('train','validation','test','all','selected'):
        ids=selected if label=='selected' else {cid for cid,r in rows.items() if label=='all' or r['split']==label}
        counts[label]=dict(slices=len(ids),completed_trajectories=sum(metrics[cid]['completed'] for cid in ids),
            complete_slices=sum(metrics[cid]['completed']==8 for cid in ids),
            mixed_completion=sum(metrics[cid]['mixed_completion'] for cid in ids),
            root_value_contrast=sum(measured[cid]['root_value_contrast'] for cid in ids),
            any_step_value_contrast=sum(metrics[cid]['any_step_value_contrast'] for cid in ids),
            later_step_value_contrast=sum(metrics[cid]['later_step_value_contrast'] for cid in ids),
            additional_over_root=sum(metrics[cid]['any_step_value_contrast'] and not measured[cid]['root_value_contrast'] for cid in ids),
            decision_gap_or_completion_contrast=sum(metrics[cid]['decision_gap_or_completion_contrast'] for cid in ids),
            no_observed_decision_or_completion_contrast=sum(not(metrics[cid]['decision_gap_or_completion_contrast'] or metrics[cid]['any_step_value_contrast']) for cid in ids))
    args.output.mkdir(parents=True,exist_ok=True)
    result=dict(counts=counts,acquisition=acquisition,entry_answer_groups=groups,
        prompt_value_consistency_calls_checked=checked,selection={k:selection[k] for k in ('eligible','protected','targets','actual','selected_parents','selected_families','strong_acquisition_slices','entry_answer_groups','family_cap_exceptions','rule')},
        files=dict(analysis_complete=file_hash(args.analysis/'COMPLETE.json'),selection_complete=file_hash(args.selection/'COMPLETE.json')),
        caveats=['Eight samples are exploratory, not a causal proof or a precise estimate of policy value.',
            'Per-trajectory summed conditional action gaps are not the definition of D, C, or S. They exclude environment reward noise at each decision, but visited information sets still vary.',
            'Invalid/truncated outcomes retain null utilities; mixed completion is a separate training signal.',
            'Entry-answer model values use valid actions only and can have missing-output selection bias.',
            'Selected windows are frozen candidates, not generated supervision traces or a training-runtime export.',
            'New strong acquisition families remain train-only; this run does not validate acquisition generalization.'])
    write_json(args.output/'REVIEW.json',result)
    table='| Scope | Questions | All 8 complete | Mixed completion | Root contrast | Any-step contrast | Added beyond root | Gap/completion contrast |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
    for label,c in counts.items():table+='| '+label+' | '+' | '.join(str(c[k]) for k in ('slices','complete_slices','mixed_completion','root_value_contrast','any_step_value_contrast','additional_over_root','decision_gap_or_completion_contrast'))+' |\n'
    report=f'''# v4 D merge, full-window audit and 100-slice selection

The v4 panel now has real D evidence for all 800 candidates: 722 unchanged
questions reused from v2 and 78 from job 915300. All 6,400 original game records
retain their source archive/member/protocol checksums. No model run or training
was launched by this analysis.

{table}

Selection: **100 train questions, {selection['selected_parents']} parents,
{selection['selected_families']} structural families**. All 12 strong acquisition
windows and all nine complete train entry-answer groups (27 member questions)
are protected. Test/validation outcomes are excluded from selection. Protection
preserves information contrasts; it does not assert every protected member has
within-question sampled contrast.

Actual distribution: `{json.dumps(selection['actual'],sort_keys=True)}`.
Soft targets from train candidate metadata: `{json.dumps(selection['targets'],sort_keys=True)}`.
Maximum four selected questions per parent and eight per family, except the
minimum required to retain protected groups: `{selection['family_cap_exceptions']}`.
The recorded
optimization weights favor family/parent diversity and same-prompt value contrast;
D/C is a clipped ranking feature, including explicitly named completed-only D
for incomplete questions. These are transparent design choices, not a uniquely
optimal dataset or validated training recipe.

## Acquisition behavior

Across 96 trajectories from the 12 strong-S windows, the model executed
{acquisition['query_calls']} investigations: {acquisition['optimal_query_calls']}
had optimal finite-window action value and {acquisition['suboptimal_query_calls']}
were suboptimal investigation choices. This judges target choice against the
same saved terminal continuation; the oracle still optimizes only the focal k
controlled decisions.

The chosen query targets have information-status counts
`{dict(query_information)}`. "Already known" means the queried preference has
only one supported value in the model-visible information cell. Thus every
suboptimal investigation observed here asks for a preference that was already
inferable, rather than buying information about the uncertain preference. This
is a concrete input-reading/query-target error; executing INVESTIGATE by itself
does not demonstrate information gathering.

There were {acquisition['post_query_valid_calls']} valid subsequent model actions,
of which {acquisition['post_query_suboptimal_calls']} had positive conditional
value gap. At actually visited public histories, only
{acquisition['answer_sensitive_calls']} calls had disjoint optimal action sets
across feasible answers to the model's query: {acquisition['answer_sensitive_valid']}
valid actions, {acquisition['answer_sensitive_correct']} optimal, and
{acquisition['answer_sensitive_failures']} failed outputs. This small denominator
cannot establish reliable answer-use competence. It also shows why counting
INVESTIGATE alone is insufficient.

## Method and limits

Every recorded request, action, RNG reset and terminal path was independently
replayed with the frozen native reference, without equilibrium re-solving.
Only terminal payoff comparisons allow 1e-12 cross-platform floating-point
roundoff; actions, statuses, prompts and seeds match exactly. At each model
call the posterior uses entrance belief, fixed-reference action likelihoods,
and observed private answers. The model's controlled actions are interventions,
not hidden-world evidence. The remaining k-window optimal continuation supplies
all action values. All {checked} audited calls passed the check that identical
visible prompts within a question have identical Q vectors across replicas.

The sum of sampled decision gaps is a trajectory diagnostic, **not D or C/S**.
Primary D and its missing-outcome bounds retain the original definition. Failed
trajectories have null full-window loss/utility, with valid-prefix gaps kept
separately. Reward differences alone are not sufficient evidence because resets
and reference actions are stochastic. No minimum eight-completion rule is used
for selection, and no negative Monte Carlo D is silently clipped in the data.

The ten entry-answer groups are analyzed separately in REVIEW.json. Their
observed action values are weighted by the oracle group probabilities and use
valid actions only; missing outputs can bias this diagnostic. Collective S is
never copied onto an individual question. Strong acquisition held-out coverage
and long-horizon transfer remain unvalidated.

## Artifacts and reproduction

- `new/local_data/strategic_slices_terminal_d_v4_analysis`: merged D, question-level
  provenance, 100 parent replay audits, per-decision Q/posterior/gap, and checksums.
- `new/local_data/strategic_slices_terminal_selected_v4`: exactly 100 original
  candidate records, selected D/trajectory metrics, protected answer relations,
  selection rationale, reference hashes and checksums. References remain in v4.
- `new/local_data/strategic_slices_terminal_d_v4_review/REVIEW.json`: this report's
  detailed counts and entry-answer group measurements.

```bash
python -m examples.strategic_slices.analyze_terminal_d_v4
python -m examples.strategic_slices.select_terminal_d_v4
python -m examples.strategic_slices.report_terminal_d_v4
```

Use `--resume` for an interrupted unchanged audit; use fresh `--output` paths
for an independent rerun. These commands perform no model inference, job
submission, weight training or supervision generation. Four focused tests cover
native replay, hidden-world information isolation, later-step/failure signals,
and train-only protected-group selection.
'''
    (args.output/'REPORT.md').write_text(report)
    print(json.dumps(dict(counts=counts,acquisition=acquisition,entry_groups=groups),indent=2))


if __name__=='__main__':main()
