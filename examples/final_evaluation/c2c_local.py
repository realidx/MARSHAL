"""Development-only C2C runner with explicit local/API routing; no rule changes."""
import argparse
import copy
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from examples.strategic_transfer.c2c_paired import C2C_COMMIT, COMMANDERS, _latest_state
ROOT=Path(__file__).resolve().parents[2]


def load_routes(path):
    config=json.loads(Path(path).read_text())
    if config.get('schema_version')!=1:raise ValueError('Unsupported routing config')
    routes=[config['endpoints'][name] for name in ('focal','q0','summary')]
    routes+=config.get('equivalent_replicas',[])
    for route in routes:
        url=urlparse(route['base_url'])
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
            raise ValueError('Use an HTTP(S) base URL without embedded credentials')
        if config.get('local_only',True) and url.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Nonlocal endpoint requires local_only=false')
        if not route['model']:raise ValueError('Missing served model name')
    if config['max_tokens']<1:raise ValueError('Invalid output budget')
    return config


def development_plan(seed_base=2026091700, boards=1):
    if boards<1:raise ValueError('Positive board count required')
    games=[]
    for board in range(boards):
        board_seed=seed_base+board;shuffle_seed=seed_base+50000+board
        slots=list(range(4));random.Random(shuffle_seed).shuffle(slots)
        for seat in range(4):
            models=['q0']*4;models[slots[seat]]='focal'
            games.append(dict(game_id=f'game_{board:03d}_seat_{seat}',board_seed=board_seed,
                              shuffle_seed=shuffle_seed,focal_seat=seat,model_assignment=models))
    return dict(schema_version=1,stage='development',formal_test=False,c2c_commit=C2C_COMMIT,games=games)


class Transport:
    def __init__(self,config,log_path,seed,summary_model):
        self.config=config;self.log_path=Path(log_path);self.seed=seed
        self.summary_model=summary_model;self.counters={}

    def __call__(self,model,messages,temperature=.7,max_tokens=None,response_format=None,log_dir=None):
        alias='summary' if model==self.summary_model else model
        if alias not in self.config['endpoints']:raise ValueError('Unconfigured model alias: '+model)
        route=self.config['endpoints'][alias];index=self.counters.get(alias,0);self.counters[alias]=index+1
        seed=int(hashlib.sha256(f'{self.seed}:{alias}:{index}'.encode()).hexdigest()[:8],16)
        body=dict(model=route['model'],messages=messages,temperature=temperature,
                  max_tokens=max_tokens if max_tokens is not None else self.config['max_tokens'],seed=seed)
        if response_format is not None:body['response_format']=response_format
        key=os.environ.get(route.get('api_key_env',''),'EMPTY')
        started=time.monotonic()
        record=dict(alias=alias,call_index=index,base_url=route['base_url'],request=body)
        try:
            req=Request(route['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urlopen(req,timeout=self.config['timeout_seconds']) as response:raw=json.load(response)
            record['response']=raw;choice=raw['choices'][0]
            if choice.get('finish_reason')=='length':
                record['status']='truncated';raise RuntimeError('C2C response truncated')
            text=choice['message']['content']
            if not isinstance(text,str):
                record['status']='protocol_failure';raise ValueError('Missing textual response')
            if response_format and response_format.get('type')=='json_object':
                try:
                    parsed=json.loads(text)
                    if not isinstance(parsed,dict) and not (isinstance(parsed,list) and len(parsed)==1 and isinstance(parsed[0],dict)):
                        raise ValueError('Expected JSON object')
                except (ValueError,TypeError):
                    record['status']='protocol_failure';raise
            record['status']='ok';return text
        except Exception as exc:
            record.setdefault('status','infrastructure_failure')
            # Do not serialize credentials or request headers into run artifacts.
            record['error_type']=type(exc).__name__
            from c2c.models.exceptions import LLMException
            raise LLMException(f"{record['status']} in {alias} call {index}: {type(exc).__name__}") from exc
        finally:
            record['elapsed_seconds']=time.monotonic()-started
            self.log_path.parent.mkdir(parents=True,exist_ok=True)
            with self.log_path.open('a') as stream:stream.write(json.dumps(record,ensure_ascii=False)+'\n')


def game_routes(routes, game):
    config=copy.deepcopy(routes)
    replicas=config.get('equivalent_replicas')
    if replicas:
        # Only explicitly declared identical checkpoint replicas may share roles.
        route=replicas[(game['board_seed']+game['focal_seat'])%len(replicas)]
        config['endpoints']={alias:dict(route) for alias in ('focal','q0','summary')}
    return config


def run_game(upstream, routes, output, game, max_turns):
    # Separate processes isolate native RNG state and the transport module hook.
    sys.path.insert(0,str(upstream))
    import c2c.llm as llm
    from c2c.prompts import _DEAL_SUMMARY_MODEL
    from c2c.experiments.run_batch import _run_game_worker
    routes=game_routes(routes,game)
    output=Path(output)
    folder=output/game['game_id'];log=folder/'transport.jsonl'
    llm.call_llm=Transport(routes,log,f"{game['board_seed']}:{game['shuffle_seed']}:{game['focal_seat']}",_DEAL_SUMMARY_MODEL)
    cfg=dict(game,game_dir=str(folder),max_turns=max_turns,comparison_target_index=game['focal_seat'],
             llm_max_retries=0,llm_backoff_base_s=2.,llm_backoff_max_s=90.,llm_jitter_s=0.,resume=False,start_step=0)
    _run_game_worker(cfg)
    calls=[json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    state=_latest_state(folder)
    result=dict(game_id=game['game_id'],focal_seat=game['focal_seat'],calls=len(calls),
                call_statuses={status:sum(c['status']==status for c in calls) for status in ('ok','truncated','protocol_failure','infrastructure_failure')},
                worker_error=(folder/'error.json').exists(),game_over=bool(state and state.get('game_over')),
                winner=state.get('winner') if state else None,
                focal_win=bool(state and state.get('winner')==COMMANDERS[game['focal_seat']]))
    result['status']='worker_error' if result['worker_error'] else 'natural_terminal' if result['game_over'] else 'horizon_reached_without_winner'
    return result


def run(args):
    routes=load_routes(args.routes);plan=json.loads(Path(args.plan).read_text())
    if plan.get('stage')!='development' or plan.get('formal_test') is not False:
        raise ValueError('This runner only accepts development plans')
    upstream=Path(args.c2c_dir).resolve()
    if not (upstream/'.git').exists():
        raise ValueError('C2C folder lacks Git metadata; run examples.final_evaluation.setup_c2c')
    top=subprocess.check_output(['git','-C',str(upstream),'rev-parse','--show-toplevel'],text=True).strip()
    if Path(top).resolve()!=upstream:raise ValueError('Git resolved to an unrelated parent repository')
    commit=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    if commit!=C2C_COMMIT or plan['c2c_commit']!=commit:raise ValueError('C2C source version mismatch')
    if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain','--untracked-files=no'],text=True).strip():
        raise ValueError('C2C tracked source modified')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    (output/'run_manifest.json').write_text(json.dumps(dict(plan=plan,routes=routes,max_turns=args.max_turns,parallel_games=args.parallel_games,
        summary_policy='frozen Q0 extraction; no new judge',models_compared=False),indent=2)+'\n')
    results=[]
    with ProcessPoolExecutor(max_workers=args.parallel_games,mp_context=mp.get_context('spawn')) as pool:
        pending={pool.submit(run_game,upstream,routes,output,game,args.max_turns):game for game in plan['games']}
        print(f"Running {len(pending)} games; parallel_games={args.parallel_games}",flush=True)
        for future in as_completed(pending):
            result=future.result()
            results.append(result)
            results.sort(key=lambda item:item['game_id'])
            (output/'development_results.json').write_text(json.dumps(dict(formal_test=False,games=results),indent=2)+'\n')
            print(f"Finished {result['game_id']}: {result['status']} ({len(results)}/{len(pending)})",flush=True)
    (output/'RUN_FINISHED.json').write_text(json.dumps(dict(games=len(results),meaning='Runner finished; inspect game and call failures, not a success claim'))+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare-dev');prep.add_argument('--output',type=Path,required=True);prep.add_argument('--boards',type=int,default=1);prep.add_argument('--seed-base',type=int,default=2026091700)
    execute=sub.add_parser('run-dev');execute.add_argument('--routes',default=str(Path(__file__).with_name('c2c_local.json')))
    execute.add_argument('--plan',required=True);execute.add_argument('--output',required=True);execute.add_argument('--c2c-dir',default=str(ROOT/'third_party/cooperate-to-compete'));execute.add_argument('--max-turns',type=int,default=50)
    execute.add_argument('--parallel-games',type=int,default=4)
    args=parser.parse_args()
    if args.command=='prepare-dev':
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x') as f:f.write(json.dumps(development_plan(args.seed_base,args.boards),indent=2)+'\n')
    else:
        if args.max_turns<1 or args.parallel_games<1:parser.error('--max-turns and --parallel-games must be positive')
        run(args)

if __name__=='__main__':main()
