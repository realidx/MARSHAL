"""Evaluation-only HTTP client: held-out B/P and fixed-base-opponent games."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.request import Request, urlopen

from training.social_mixed.core import Episode, load_data, seed_for


def complete(url, model, request):
    body=dict(model=model,messages=request['messages'],tools=request['tools'],tool_choice='auto',
              parallel_tool_calls=False,max_tokens=1024,temperature=1.0,top_p=1.0,top_k=-1,
              repetition_penalty=1.0,seed=request['seed'])
    req=Request(url.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer EMPTY'})
    with urlopen(req,timeout=180) as response:raw=json.load(response)
    choice=raw['choices'][0]
    return dict(completion=dict(raw_message=choice['message'],finish_reason=choice['finish_reason']),
                usage=raw.get('usage',{}),request=request,source='evaluation_only_http')


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--learner-url',required=True)
    cli.add_argument('--opponent-url',required=True)
    cli.add_argument('--learner-model',default='social-learner')
    cli.add_argument('--opponent-model',default='social-base')
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--replicas',type=int,default=4)
    cli.add_argument('--concurrency',type=int,default=16)
    args=cli.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    data=load_data()
    from training.b_sft.social_named_probe import request
    from training.b_sft.social_bp_training import reward,summarize
    def bp(job):
        task,replica=job
        req=request(task,'action_tools',task.get('name_variant',0))
        req['seed']=seed_for(42,'eval',task['id'],replica)
        reply=complete(args.learner_url,args.learner_model,req)
        return dict(task=task,replica=replica,response=reply,score=reward(task,reply['completion']))
    def game(job):
        reset,seat,replica=job
        episode=Episode(reset,f'eval:{reset["id"]}',replica,42)
        while episode.status=='running':
            learner=episode.rules.actor(episode.node)==seat
            reply=complete(args.learner_url if learner else args.opponent_url,
                           args.learner_model if learner else args.opponent_model,episode.request())
            episode.accept(reply)
        return dict(episode.summary(),learner_seat=seat,calls=episode.calls)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        bp_records=[]
        with (args.output/'bp.jsonl').open('w') as f:
            for row in pool.map(bp,[(t,i) for t in data['bp_validation'] for i in range(args.replicas)]):
                f.write(json.dumps(row)+'\n');f.flush();bp_records.append(row)
        games=[]
        jobs=[(r,p,i) for r in data['selfplay_validation'] for p in range(r['raw']['game']['n_players']) for i in range(args.replicas)]
        with (args.output/'games.jsonl').open('w') as f:
            for row in pool.map(game,jobs):
                f.write(json.dumps(row)+'\n');f.flush();games.append(row)
    terminal=[g for g in games if g['status']=='terminal']
    outcome=dict(games=len(games),terminal=len(terminal),completion_rate=len(terminal)/len(games),
                 learner_utility_conditional_on_completion=(sum(g['terminal_utility'][g['learner_seat']] for g in terminal)/len(terminal) if terminal else None),
                 others_total_utility_conditional_on_completion=(sum(sum(v for p,v in enumerate(g['terminal_utility']) if p!=g['learner_seat']) for g in terminal)/len(terminal) if terminal else None),
                 learner_protocol_mean=sum(g['protocol'][g['learner_seat']] for g in games)/len(games))
    (args.output/'summary.json').write_text(json.dumps(dict(bp=summarize(bp_records),selfplay=outcome,
        opponent=args.opponent_model,replicas=args.replicas,test_used=False,
        note='Incomplete terminal utility stays missing; conditional utility must be read with completion rate.'),indent=2)+'\n')


if __name__=='__main__':main()
