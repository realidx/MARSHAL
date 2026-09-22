"""Native-transition reference replays; no LLM or agent-accessible solver."""
from collections import Counter,defaultdict
from examples.final_evaluation.shapefactory import Factory,IDS,CYCLES,instances

def action(kind,**payload):return dict(type=kind,payload=payload)
def replay(case,cooperative):
    env=Factory(case);queues=defaultdict(list);production=Counter()
    if cooperative:
        for buyer in IDS:
            for shape in case['orders'][buyer]:
                sellers=[a for a in IDS if case['specialties'][a]==shape and production[a]<3]
                seller=min(sellers,key=lambda a:(production[a],a));production[seller]+=1
                queues[seller].append((buyer,shape))
    for cycle in range(CYCLES):
        env.tick(cycle);observations={a:env.observation(a) for a in IDS};actions={}
        for a in IDS:
            me=observations[a]['task']['participants'][a]
            if cooperative and cycle==0 and production[a]:actions[a]=action('produce_shape',shape=case['specialties'][a],quantity=production[a])
            elif not cooperative and cycle<2:actions[a]=action('produce_shape',shape=case['orders'][a][cycle],quantity=1)
            else:
                incoming=[o for o in observations[a]['task']['pending_offers'] if o['to']==a]
                if incoming:actions[a]=action('trade_response',transaction_id=incoming[0]['id'],response_type='accept')
                elif cooperative and cycle>=3 and queues[a]:
                    buyer,shape=queues[a].pop(0);actions[a]=action('propose_trade_offer',offer_type='sell',target_id=buyer,shape=shape,quantity=1,price_per_unit=15)
                elif me['tasks'] and not (Counter(me['tasks'])-Counter(me['inventory'])):actions[a]=action('fulfill_order',order_indices=list(range(len(me['tasks']))))
                else:actions[a]=action('do_nothing')
        for a in IDS[cycle%4:]+IDS[:cycle%4]:env.submit(a,actions[a])
    env.tick(CYCLES)
    result=env.metrics();expected=290 if cooperative else 240
    assert result['all_orders_completed'] and result['mean_final_balance']==expected,(case['id'],cooperative,result)
    assert result['semantic_rejections']==0,result
    return dict(case_id=case['id'],policy='specialist' if cooperative else 'self_supply',metrics=result,events=env.events)

def audit():return [replay(c,coop) for c in instances() for coop in (False,True)]
if __name__=='__main__':
    import json
    from pathlib import Path
    p=Path('examples/final_evaluation/shapefactory_v1');p.mkdir(exist_ok=True)
    data=audit();(p/'references.json').write_text(json.dumps(data,indent=2)+'\n')
    (p/'cases.json').write_text(json.dumps(instances(),indent=2)+'\n')
    print('Verified 24 native replays: self_supply=240, specialist team mean=290; all orders complete.')
