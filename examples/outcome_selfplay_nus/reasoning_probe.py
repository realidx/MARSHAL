"""Paired fixed-state explanation probe; no environment steps or reward changes."""
import argparse,hashlib,json,os,time
from collections import defaultdict
from pathlib import Path
from urllib.request import Request,urlopen


def summarize(rows):
    stats=defaultdict(lambda:dict(requests=0,http_completed=0,explanation=0,tool_submission=0,explanation_and_tool=0,truncated=0))
    for r in rows:
        s=stats[r['arm']];s['requests']+=1
        if 'body' not in r:continue
        s['http_completed']+=1
        choice=r['body']['choices'][0];m=choice['message'];text=m.get('content')
        explained=isinstance(text,str) and bool(text.strip())
        calls=m.get('tool_calls') or []
        names={t['function']['name'] for t in r['request']['tools']}
        submitted=len(calls)==1 and calls[0].get('function',{}).get('name') in names and choice.get('finish_reason')!='length'
        s['explanation']+=explained;s['tool_submission']+=submitted
        s['explanation_and_tool']+=explained and submitted
        s['truncated']+=choice.get('finish_reason')=='length'
    return dict(stats)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--requests',type=Path,default=Path(__file__).with_name('reasoning_probe_requests.jsonl'))
    cli.add_argument('--base-url');cli.add_argument('--model',default='outcome-base')
    cli.add_argument('--output-dir',type=Path);cli.add_argument('--check-only',action='store_true')
    args=cli.parse_args();data=args.requests.read_bytes();cases=[json.loads(x) for x in data.splitlines()]
    assert len({c['id'] for c in cases})==len(cases)
    if args.check_only:
        for c in cases:assert c['request']['messages'] and c['request']['tools']
        print(f'Validated {len(cases)} requests; no HTTP calls.');return
    if not args.base_url or args.output_dir is None:cli.error('--base-url and --output-dir required')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'manifest.json').write_text(json.dumps(dict(requests_sha256=hashlib.sha256(data).hexdigest(),model=args.model,base_url=args.base_url,training_started=False,environment_steps=0,retries=0),indent=2)+'\n')
    rows=[]
    with (args.output_dir/'samples.jsonl').open('x') as output:
        for case in cases:
            body=dict(case['request'],model=args.model);row=dict(case,request=body);start=time.monotonic()
            try:
                request=Request(args.base_url.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ.get('VLLM_API_KEY','EMPTY')})
                with urlopen(request,timeout=180) as response:row['body']=json.load(response)
            except Exception as exc:row['error']=f'{type(exc).__name__}: {exc}'
            row['seconds']=time.monotonic()-start;rows.append(row)
            output.write(json.dumps(row,ensure_ascii=False)+'\n');output.flush()
            print(case['id'],row.get('error','saved'),flush=True)
    summary=summarize(rows)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
