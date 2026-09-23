"""Two-player cooperation-incentive Shape Factory diagnostic, v2."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from examples.final_evaluation.calbench_local import load_routes
from examples.final_evaluation import shapefactory as sf
from examples.final_evaluation import shapefactory_local as runner

IDS = ['A', 'B']
SHAPES = ['circle', 'square']
CYCLES = 12
CASES = [
    dict(id='lite-circle-square', specialties={'A':'circle','B':'square'},
         orders={'A':['square'],'B':['circle']}),
    dict(id='lite-square-circle', specialties={'A':'square','B':'circle'},
         orders={'A':['circle'],'B':['square']}),
]


class LiteFactory(sf.Factory):
    def __init__(self, case, dashboard=False):
        self.native=sf.native();self.case=deepcopy(case);self.dashboard=dashboard
        self.cycle=0;self.events=[];self.pending=[]
        self.state=SimpleNamespace(task_state=self.native.shapefactory_init_state(dict(
            agents=[dict(id=a) for a in IDS],protocol=dict(produce_shape_delay_sec=30),
            task=dict(shape_options=SHAPES,specialties=case['specialties'],shapes_order=1,
                      starting_money=200,regular_cost=40,specialty_cost=15,
                      min_trade_price=15,max_trade_price=100,incentive_money=60,
                      max_production_num=3,target_steps=100000))))
        for actor in IDS:
            self.state.task_state['participants'][actor]['tasks']=list(case['orders'][actor])

    def metrics(self):
        metrics=super().metrics()
        participants=self.state.task_state['participants']
        completed=sum(p['order_progress'] for p in participants.values())
        metrics.update(mean_final_balance=sum(p['money'] for p in participants.values())/2,
                       completed_fraction=completed/2,all_orders_completed=completed==2,
                       completed_items=completed)
        return metrics


RULES='''You are Shape Factory player {actor}; the other player is {partner}. Maximize your own final money while completing your one private order item. Your order is for a shape other than your specialty. You can obtain that shape by producing it yourself or by communicating and buying it from the other player. Your specialty is cheaper to produce and may be valuable to the other player. You may initiate a direct message to negotiate, make a buy or sell offer, respond to an offer, or produce a shape; do not wait for the other player to act first if you have a useful move. Cooperation can improve earnings, but self-production is allowed; choose based on your situation. Do not assume the other player's private order.

You may produce circle or square: your specialty costs 15 per item, the other shape costs 40. Start with 200 and no inventory. Maximum total production is 3 items per player. Production takes 3 cycles; cost and inventory changes apply at completion, subject to funds and capacity then. A fulfilled order item consumes its shape and earns 60. fulfill_order uses shapes already in your inventory and CURRENT order indices. Trading transfers inventory and money only when the recipient accepts and both parties can execute. Prices must be 15 through 100. Offers do not reserve inventory or money. A sell offer requires current inventory; a buy offer requires sufficient money. Private messages do not execute trades. You have one action per cycle for 12 cycles (10 logical seconds each). Observations precede current-cycle actions; new messages/offers are visible next cycle. Production due at the 120-second endpoint settles, with no additional action.

Check your current orders, inventory, production usage, pending production and offers before acting. Do not keep producing the same shape merely because it is your specialty. If the production cap is reached, use another valid action; if an action is rejected, read the reason and adjust rather than repeating it. For trade_response and cancel_trade_offer, use a real transaction_id from current pending offers, never an example ID. You may fulfill only when inventory contains the shape required by the selected current order. Choose exactly one action. Return only JSON {"action":{"type":"...","payload":{...}},"rationale":"optional short reason"}. No markdown or prose.

Enabled action payload examples: message {"channel":"direct","recipients":["{partner}"],"content":"I need your specialty shape; would you trade?","content_type":"text"}; produce_shape {"shape":"{order_shape}","quantity":1}; propose_trade_offer {"offer_type":"buy","shape":"{order_shape}","price_per_unit":25,"target_id":"{partner}","quantity":1}; trade_response {"transaction_id":"<real pending offer id>","response_type":"accept"}; cancel_trade_offer {"transaction_id":"<real pending offer id>"}; fulfill_order {"order_indices":[0]}; do_nothing {"reason":"No valid high-value move this cycle"}. Never address a message or offer to yourself.'''


def lite_prompt(observation):
    actor=observation['you']
    partner=next(a for a in IDS if a!=actor)
    own=observation['task']['participants'][actor]
    order_shape=own['tasks'][0] if own['tasks'] else own['specialty']
    messages=sf.prompt(observation)
    messages[0]['content']=(RULES.replace('{actor}',actor).replace('{partner}',partner)
                            .replace('{order_shape}',order_shape))
    return messages


def configure():
    sf.IDS=IDS;sf.SHAPES=SHAPES;sf.CYCLES=CYCLES
    runner.IDS=IDS;runner.CYCLES=CYCLES;runner.Factory=LiteFactory
    runner.prompt=lite_prompt
    runner.VERSION='shape-factory-lite-cooperation-incentive-v2'


def witness(case):
    """One symmetric legal trace proves the case admits bilateral trade and fulfillment."""
    configure()
    env=LiteFactory(case)
    for cycle in range(CYCLES):
        env.tick(cycle)
        for actor in IDS:
            partner=IDS[1-IDS.index(actor)]
            if cycle==0:
                action=dict(type='produce_shape',payload=dict(shape=case['specialties'][actor],quantity=1))
            elif cycle==3:
                action=dict(type='propose_trade_offer',payload=dict(offer_type='sell',
                    shape=case['specialties'][actor],quantity=1,price_per_unit=25,target_id=partner))
            elif cycle==4:
                offer=next(x for x in env.state.task_state['pending_offers'] if x['to']==actor)
                action=dict(type='trade_response',payload=dict(transaction_id=offer['id'],response_type='accept'))
            elif cycle==5:
                action=dict(type='fulfill_order',payload=dict(order_indices=[0]))
            else:
                action=dict(type='do_nothing',payload={})
            if not env.submit(actor,action):
                raise AssertionError(f'Witness rejected: {case["id"]} cycle={cycle} actor={actor} action={action}')
    env.tick(CYCLES)
    metrics=env.metrics()
    if metrics['completed_items']!=2 or metrics['trades']!=2 or metrics['semantic_rejections']:
        raise AssertionError(f'Witness incomplete: {case["id"]}: {metrics}')
    return metrics


def run_job(job):
    configure()
    return runner.run_one(job)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routes',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parallel-games',type=int,default=2)
    args=parser.parse_args()
    routes=load_routes(args.routes)
    if routes.get('temperature',0)!=0:raise ValueError('Temperature must be zero')
    if args.parallel_games<1:parser.error('parallel-games must be positive')
    witnesses={case['id']:witness(case) for case in CASES}
    args.output.mkdir(parents=True,exist_ok=False)
    replicas=routes.get('equivalent_replicas') or [routes['endpoints']['focal']]
    jobs=[(case,condition,routes,str(args.output/f'{case["id"]}-{condition}'),
           replicas[i%len(replicas)])
          for i,case in enumerate(CASES) for condition in ('private','dashboard')]
    runner.dump(args.output/'protocol.json',dict(version='shape-factory-lite-cooperation-incentive-v2',
        not_paper_or_frozen_benchmark=True,cases=CASES,cycles=CYCLES,conditions=['private','dashboard'],
        rules='Native economics/actions; two agents, one cross-specialty order each; cooperation incentivized but not required',
        references=witnesses,routes=routes))
    with ProcessPoolExecutor(max_workers=args.parallel_games) as pool:
        results=list(pool.map(run_job,jobs))
    runner.dump(args.output/'results.json',results)
    runner.dump(args.output/'summary.json',dict(
        cases=len(CASES),games=len(results),completed_items=sum(r['metrics']['completed_items'] for r in results),
        possible_items=2*len(results),fully_completed_games=sum(r['metrics']['all_orders_completed'] for r in results),
        accepted_trades=sum(r['metrics']['trades'] for r in results),
        calls=sum(r['calls'] for r in results),
        parse_failures=sum(r['post_normalization_parse_failures'] for r in results),
        execution_rejections=sum(r['execution_rejections'] for r in results)))
    (args.output/'COMPLETE').write_text('ok\n')


if __name__=='__main__':main()
