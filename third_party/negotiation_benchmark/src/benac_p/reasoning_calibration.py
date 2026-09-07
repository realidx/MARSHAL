"""Matched discovery-only reasoning-budget comparison on frozen saved inputs.

Reuses the archived open-profile baseline. Replays compact and balanced on
identical inputs, including frozen model judgments. No new judgments are fed
into planning inputs during this comparison. Confirmation tasks are excluded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import numpy as np
from benac_p.semantic_suite import Suite, SYSTEM
from benac_p.diagnose_suite import dump, digest, cluster_summary
from benac_p.diagnose_protocol import generate, system_prompt, protocol_summary, REASONING_PROFILE_VERSION


def prepare(source,per_stratum=4,seed=0):
    manifest=json.loads((source/'manifest.json').read_text())
    answers=json.loads((source/'answers.json').read_text())
    archive=json.loads((source/'tasks.json').read_text())
    if manifest.get('oracle_check') or manifest['response_protocol']!='reasoning_tools':
        raise ValueError('Calibration requires a real-model native-tool baseline.')
    if archive['system']!=system_prompt(SYSTEM,'reasoning_tools','open'):
        raise ValueError('Source is not the unchanged open-profile baseline; do not mix prompt changes.')
    suite=Suite(manifest['bundles'],manifest['seed']).build()
    if digest(suite.tasks)!=manifest['task_hash']:raise ValueError('Source tasks differ from current game; cannot do a matched comparison.')
    suite.add_model_arms(answers)
    strata={}
    for task in suite.tasks:
        label=suite.labels[task['id']];record=answers.get(task['id'],{})
        if label['split']!='discovery' or 'finish_reason' not in record:continue
        try:payload=suite.payload(task,answers)
        except ValueError:continue
        if record.get('payload_hash')!=digest(payload):raise ValueError('Archived input fingerprint differs.')
        stage='root' if label['case'].endswith('/root') else 'downstream'
        role=task['id'].rsplit('/',1)[1]
        stratum='/'.join((label['condition'],stage,role))
        ctx=suite.cases[label['case']]
        expected=dict(possible_preferences=label['possible_preferences'])
        if task['kind']=='planning':
            game=suite.games[label['game']]['game']
            # Score planning under the ACTUAL frozen supplied judgment, not a
            # hidden repaired judgment the replayed model never received.
            supplied=payload['partner_judgment']['possible_preferences']
            q={m.key:v for m,v in game.q_values(ctx['state'],supplied)}
            expected={'q':[q[m.key] for m in ctx['moves']]}
        strata.setdefault(stratum,[]).append(dict(id=task['id'],bundle=label['bundle'],stratum=stratum,
            task=task,payload=payload,expected=expected,baseline=record))
    rng=np.random.default_rng(seed);selected=[]
    for key,rows in sorted(strata.items()):
        order=rng.permutation(len(rows))[:per_stratum]
        selected.extend(rows[i] for i in order)
    if not selected:raise ValueError('No eligible discovery tasks.')
    return suite,manifest,selected


def evaluate(row,record):
    ok=record.get('status')=='ok';success=False;regret=None
    try:
        if ok and row['task']['kind']=='semantic_belief':
            answer=record['answer']['possible_preferences']
            if not isinstance(answer,list) or not answer or any(x not in ('want','neutral','avoid') for x in answer) or len(set(answer))!=len(answer):raise ValueError('Invalid preference set')
            success=set(answer)==set(row['expected']['possible_preferences'])
        elif ok:
            idx=record['answer']['action_index'];q=row['expected']['q']
            if isinstance(idx,bool) or not isinstance(idx,int) or not 0<=idx<len(q):raise ValueError('Invalid action')
            regret=max(q)-q[idx];success=regret<1e-8
    except (ValueError,KeyError,TypeError):ok=False
    return dict(valid=int(ok),success=int(ok and success),regret=regret if ok else None,
                tokens=record.get('usage',{}).get('completion_tokens'),
                truncated=int(record.get('status')=='truncated'))


def summarize(selected,records):
    report={};scored={}
    for profile in ('open','compact','balanced'):
        rr=[]
        for row in selected:
            if profile+'/'+row['id'] not in records:continue
            r=evaluate(row,records[profile+'/'+row['id']])
            rr.append(dict(r,id=row['id'],game=row['bundle'],kind=row['task']['kind']))
        scored[profile]={r['id']:r for r in rr}
        if len(rr)!=len(selected):report[profile]={'complete':False,'requests':len(rr)};continue
        b=[r for r in rr if r['kind']=='semantic_belief'];p=[r for r in rr if r['kind']=='planning']
        report[profile]=dict(complete=True,requests=len(rr),valid_rate=float(np.mean([r['valid'] for r in rr])),
            truncation_rate=float(np.mean([r['truncated'] for r in rr])),
            belief_valid_and_exact_rate=float(np.mean([r['success'] for r in b])) if b else None,
            planning_valid_and_optimal_rate=float(np.mean([r['success'] for r in p])) if p else None,
            planning_regret_on_valid=float(np.mean([r['regret'] for r in p if r['valid']])) if any(r['valid'] for r in p) else None,
            protocol=protocol_summary({row['id']:records[profile+'/'+row['id']] for row in selected}))
        if profile!='open':
            pairs=[dict(game=r['game'],success_delta=r['success']-scored['open'][r['id']]['success'],
                        token_delta=r['tokens']-scored['open'][r['id']]['tokens']) for r in rr
                   if r['tokens'] is not None and scored['open'][r['id']]['tokens'] is not None]
            report[profile]['paired_vs_open']={k:cluster_summary(pairs,k) for k in ('success_delta','token_delta')}
    complete=[name for name,x in report.items() if x['complete']]
    recommendation=None
    if len(complete)==3:
        best_b=max(report[x]['belief_valid_and_exact_rate'] for x in complete)
        best_p=max(report[x]['planning_valid_and_optimal_rate'] for x in complete)
        eligible=[x for x in complete if report[x]['valid_rate']>=.98 and
                  report[x]['protocol']['mean_completion_tokens'] is not None and
                  report[x]['belief_valid_and_exact_rate']>=best_b-.05 and
                  report[x]['planning_valid_and_optimal_rate']>=best_p-.05]
        if eligible:recommendation=min(eligible,key=lambda x:report[x]['protocol']['mean_completion_tokens'])
    return dict(profiles=report,recommended_profile=recommendation,
        selection_rule='Development heuristic: >=98% valid and within 5 percentage points of best observed B and P valid-and-correct rates; among eligible profiles choose lowest mean completion tokens. Not a noninferiority proof.',
        interpretation='Invalid/truncated answers count as uncompleted successes, never as fabricated strategic actions. Regret on valid answers has different coverage across profiles. Planning is scored under its frozen supplied judgment. Only discovery inputs are used.')


def write_report(result,path):
    def token_text(value):return 'NA' if value is None else f'{value:.1f}'
    lines=['# Reasoning budget calibration','',
        'Matched discovery inputs. Open is the archived baseline; compact/balanced are new calls at the SAME hard token cap.',
        'B/P success rates below require both a valid completion and a correct answer; no silent exclusion of truncations.',
        'P targets use the supplied judgment, including frozen model judgments.','',
        '| Profile | Valid | Truncated | B valid + exact | P valid + optimal | Mean tokens | P95 tokens |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for profile,x in result['profiles'].items():
        if not x['complete']:lines.append(f'| {profile} | incomplete | | | | | |');continue
        lines.append(f"| {profile} | {x['valid_rate']:.1%} | {x['truncation_rate']:.1%} | {x['belief_valid_and_exact_rate']:.1%} | {x['planning_valid_and_optimal_rate']:.1%} | {token_text(x['protocol']['mean_completion_tokens'])} | {token_text(x['protocol']['p95_completion_tokens'])} |")
    lines += ['',f"Provisional recommended profile: {result['recommended_profile'] or 'none yet; coverage or quality criteria not met'}.",result['selection_rule'],'',result['interpretation'],
              'Freeze the selected setting before a fresh confirmation run. Historical-baseline comparisons assume the same model weights and serving configuration. Paired bundle-bootstrap intervals are in comparison.json.']
    path.write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--per-stratum',type=int,default=4);parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--base-url',default='http://localhost:8000/v1');parser.add_argument('--model',default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--export-only',action='store_true');parser.add_argument('--resume',action='store_true')
    args=parser.parse_args(argv)
    if args.per_stratum<1 or args.workers<1:parser.error('Counts must be positive.')
    suite,source_manifest,selected=prepare(args.source_run,args.per_stratum,args.seed)
    if args.model!=source_manifest['model']:parser.error('Use the same served model as the baseline.')
    if args.output_dir.resolve()==args.source_run.resolve() or args.source_run.resolve() in args.output_dir.resolve().parents:parser.error('Keep the calibration outside the immutable source run.')
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    manifest=dict(version=REASONING_PROFILE_VERSION,selection_hash=digest(selected),source_manifest=source_manifest,
        max_tokens=source_manifest['max_tokens'],profiles=['open','compact','balanced'],model=args.model,base_url=args.base_url,
        system_hashes={p:digest(system_prompt(SYSTEM,'reasoning_tools',p)) for p in ('open','compact','balanced')})
    if (out/'manifest.json').exists():
        if json.loads((out/'manifest.json').read_text())!=manifest:parser.error('Calibration manifest changed; use a new output directory.')
        if (out/'answers.json').exists() and not args.resume:parser.error('Use --resume for an existing calibration.')
    elif args.resume:parser.error('No calibration manifest to resume.')
    dump(out/'manifest.json',manifest)
    dump(out/'tasks.json',[{k:v for k,v in row.items() if k not in ('baseline','expected')} for row in selected])
    dump(out/'oracle_labels.json',{r['id']:r['expected'] for r in selected})
    records=json.loads((out/'answers.json').read_text()) if (out/'answers.json').exists() else {}
    for row in selected:records['open/'+row['id']]=row['baseline']
    dump(out/'answers.json',records)
    if args.export_only:
        dump(out/'comparison.json',summarize(selected,records))
        print(f'{len(selected)} fixed discovery tasks; {2*len(selected)} new requests for two profiles. No model calls made.')
        return
    from methods.vllm_client import OpenAICompatibleNegotiationClient
    client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=source_manifest['max_tokens'],temperature=source_manifest['temperature'])
    jobs=[(profile,row) for profile in ('compact','balanced') for row in selected if profile+'/'+row['id'] not in records or records[profile+'/'+row['id']].get('status')=='transport_error']
    rng=np.random.default_rng(args.seed);rng.shuffle(jobs)
    def request(profile,row):
        try:
            record=generate(client,row['task'],row['payload'],SYSTEM,'reasoning_tools',profile)
            if record['status']=='ok':
                try:record['answer']=suite.validate(row['task'],record['answer'])
                except (ValueError,TypeError,KeyError) as exc:record.update(status='invalid',error=str(exc))
            return record
        except Exception as exc:return dict(status='transport_error',error=type(exc).__name__)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0,len(jobs),args.workers):
            futures={pool.submit(request,p,r):p+'/'+r['id'] for p,r in jobs[start:start+args.workers]}
            failed=False
            for future in as_completed(futures):
                key=futures[future];records[key]=future.result();failed |= records[key]['status']=='transport_error'
                dump(out/'answers.json',records)
            if failed:raise RuntimeError('Transport failure saved; resume after resolving the service issue.')
            print(f'{len(records)-len(selected)}/{2*len(selected)} new responses',flush=True)
    result=summarize(selected,records);dump(out/'comparison.json',result);write_report(result,out/'report.md')
    print(f'Calibration complete: {out / "report.md"}')


if __name__=='__main__':main()
