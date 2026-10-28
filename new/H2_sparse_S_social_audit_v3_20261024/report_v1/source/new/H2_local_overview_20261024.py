"""Coverage-aware reporting and query-entry diagnostics, without label changes."""
import argparse
import gzip
import json
from pathlib import Path

from new.three_player_complexity_v1_20261023.common import ROOT, snapshot, identity, write, sha, stable
from new.strategic_game_v1_20261021.rules import StrategicRules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', nargs='+', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = {r['original_index']: r for r in json.loads(args.baseline.read_text())['games']}
    inputs = {'script': identity(__file__), 'baseline': identity(args.baseline)}
    jobs, chosen, attempts = {}, {}, []
    for n, run in enumerate(args.runs):
        for name in ('COMPLETE.json','results.json','pipeline_snapshot.json','jobs.json'):
            inputs[f'{n}:{name}'] = identity(run/name)
        run_jobs = {j['index']:j for j in json.loads((run/'jobs.json').read_text())}
        for index, job in run_jobs.items():
            if index in jobs:
                assert job['id'] == jobs[index]['id'] and stable(job['raw']) == stable(jobs[index]['raw'])
            else:
                jobs[index] = job
        for row in json.loads((run/'results.json').read_text()):
            attempts.append(dict(run=str(run),index=row['index'],original_index=row['original_index'],
                status=row['status'],reference_accepted=row.get('reference_accepted',False),labels=row.get('labels')))
            # Never choose the profile with the largest Q/S. Preserve the first
            # accepted reference, even if a later attempt has different labels.
            if row.get('reference_accepted') and row['index'] not in chosen:
                chosen[row['index']] = (run,row)
    snapshot(args.output,dict(operation='H2 local full-pool paired overview and query-entry posterior diagnostic',
        runs_in_priority_order=[str(p)for p in args.runs],
        profile_selection='First accepted reference in chronological declared run order; no Q/S selection',
        denominator='All requested games; missing labels remain missing',
        positive_threshold='Stored positive counts at1e-8; query optimal actions use stored own_optimal',
        posterior_support='Exactly positive stored weights; no inference-based pruning or new action rule',
        caution='A strictly preferred query may be signalling, not acquisition; inference depends on the frozen reference'),inputs)
    measured = [(run,r)for run,r in chosen.values() if r.get('labels')=='MEASURED']
    scopes = {}
    for scope in ('counterfactual','on_reference'):
        scopes[scope] = {}
        for name,group in (('H2',[r for _,r in measured]),('baseline',[base[r['original_index']]for _,r in measured])):
            s = {}
            for metric in ('private_S_positive','history_S_positive','query_strictly_better',
                           'optimal_offer_type_dependent','static_dynamic_offer_disjoint'):
                s[metric] = sorted(r['original_index']for r in group if r['summary'][scope][metric]>0)
            s['any_S_positive'] = sorted(set(s['private_S_positive']) | set(s['history_S_positive']))
            scopes[scope][name] = s
    query_rows = []
    for run,result in measured:
        folder = run/Path(result['result_path']).parent
        worlds = StrategicRules(jobs[result['index']]['raw']).worlds
        path = folder/'labels.jsonl.gz'
        assert sha(path)==result['labels_sha256']
        with gzip.open(path,'rt') as stream:
            for line in stream:
                row = json.loads(line)
                if row['query_gap'] is None or row['query_gap']<=1e-8:continue
                queries = []
                for ai in row['own_optimal']:
                    action = row['actions'][ai]
                    if action['action']!='INVESTIGATE':continue
                    belief = {}
                    for wi,m in zip(row['world_ids'],row['posterior']):
                        if m>0:
                            value = str(worlds[wi][action['player']][action['goal']])
                            belief[value] = belief.get(value,0.)+m
                    queries.append(dict(action=action,target_belief=belief,already_inferred=len(belief)==1))
                assert queries
                query_rows.append(dict(original_index=result['original_index'],node=row['node'],
                    cell=row['cell'],own_type=row['own_type'],reference_mass=row['reference_mass'],
                    query_gap=row['query_gap'],best_queries=queries,
                    all_best_queries_already_inferred=all(q['already_inferred']for q in queries)))
    write(args.output/'QUERY_ENTRY_SUPPORT.json',query_rows)
    report = dict(requested=len(jobs),certified=len(chosen),measured=len(measured),
        missing_certificate_original_indices=sorted(j['original_index']for i,j in jobs.items()if i not in chosen),
        missing_label_original_indices=sorted(j['original_index']for i,j in jobs.items()
            if i not in chosen or chosen[i][1].get('labels')!='MEASURED'),scopes=scopes,
        chosen_references=[dict(index=r['index'],original_index=r['original_index'],run=str(run),
            reference_sha256=r['reference_sha256'])for _,(run,r)in sorted(chosen.items())],attempts=attempts,
        query_diagnostic=dict(strict_query_contexts=len(query_rows),
            all_best_queries_already_inferred_contexts=sum(r['all_best_queries_already_inferred']for r in query_rows),
            original_indices_with_already_inferred_best_queries=sorted({r['original_index']for r in query_rows
                if r['all_best_queries_already_inferred']}),
            on_reference_strict_query_contexts=sum(r['reference_mass']>0 for r in query_rows),
            on_reference_all_best_queries_already_inferred_contexts=sum(r['reference_mass']>0 and
                r['all_best_queries_already_inferred']for r in query_rows)),
        model_D='NOT_MEASURED',training='NOT_RUN',production='UNCHANGED_V8',
        limitation='World support and possibly selected profile change. Reference-path reach is not model self-play reach. Positive query gain is not proof of private-answer information value.')
    write(args.output/'OVERVIEW.json',report)
    write(args.output/'COMPLETE.json',dict(overview_sha256=sha(args.output/'OVERVIEW.json'),
        query_support_sha256=sha(args.output/'QUERY_ENTRY_SUPPORT.json'),
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps({k:v for k,v in report.items()if k not in ('attempts','chosen_references')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
