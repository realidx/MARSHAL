"""Fixed-opportunity Shape Factory adapter over pinned native economic transitions."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import sys
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
VERSION='shape-factory-fixed-opportunity-v1'
IDS=list('ABCD'); SHAPES=['circle','square','triangle']; CYCLES=18
ACTIONS={'message','produce_shape','propose_trade_offer','trade_response','cancel_trade_offer','fulfill_order','do_nothing'}

def native():
    source=HERE/'collabsim_native'; manifest=json.loads((source/'source.json').read_text())
    for name,digest in manifest['files'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise ValueError('Native source changed: '+name)
    sys.path.insert(0,str(source)) if str(source) not in sys.path else None
    module=importlib.import_module('src.tasks.shapefactory')
    if Path(module.__file__).resolve()!=source/'src/tasks/shapefactory.py':raise RuntimeError('CollabSim module namespace collision')
    return module

def instances():
    specialty=['circle','circle','square','triangle']
    choices=[list(itertools.combinations_with_replacement([s for s in SHAPES if s!=sp],2)) for sp in specialty]
    pool=[]
    for orders in itertools.product(*choices):
        demand=Counter(s for order in orders for s in order)
        if not all(0<demand[s]<=3*specialty.count(s) for s in SHAPES):continue
        if not any(len(set(orders[i]))==2 for i in (0,1)):continue
        pool.append(orders)
    assert len(pool)==16,len(pool)
    # Fixed lexical pool; choose 12 without model results. Rotate role-to-ID mapping.
    cases=[]
    for k,orders in enumerate(pool[:12]):
        mapping={i:IDS[(i+k)%4] for i in range(4)}
        shapes={s:SHAPES[(j+k//4)%3] for j,s in enumerate(SHAPES)}
        cases.append(dict(id=f'sf-{k+1:02}',pool_index=k,
                          specialties={mapping[i]:shapes[specialty[i]] for i in range(4)},
                          orders={mapping[i]:[shapes[s] for s in orders[i]] for i in range(4)}))
    return cases

class Factory:
    def __init__(self,case,dashboard=False):
        self.native=native();self.case=deepcopy(case);self.dashboard=dashboard;self.cycle=0;self.events=[];self.pending=[]
        self.state=SimpleNamespace(task_state=self.native.shapefactory_init_state(dict(
            agents=[dict(id=a) for a in IDS],protocol=dict(produce_shape_delay_sec=30),
            task=dict(shape_options=SHAPES,specialties=case['specialties'],shapes_order=2,
                      starting_money=200,regular_cost=40,specialty_cost=15,min_trade_price=15,max_trade_price=100,
                      incentive_money=60,max_production_num=3,target_steps=100000))))
        for a in IDS:self.state.task_state['participants'][a]['tasks']=list(case['orders'][a])
    def emit(self,**event):
        event=dict(event,cycle=self.cycle,logical_seconds=self.cycle*10,index=len(self.events));self.events.append(event);return event
    def tick(self,cycle):
        self.cycle=cycle
        due=[x for x in self.pending if x[0]<=cycle];self.pending=[x for x in self.pending if x[0]>cycle]
        for _,actor,action in due:self.execute(actor,action)
    def observation(self,actor):
        task=deepcopy(self.state.task_state)
        for a,row in list(task['participants'].items()):
            if a==actor:continue
            if self.dashboard:
                row.pop('tasks',None);row.pop('in_production',None)
            else:task['participants'][a]={'specialty':row['specialty']}
        visible=[deepcopy(e) for e in self.events if e.get('visibility')=='public' or e.get('actor_id')==actor or actor in e.get('recipients',[])]
        return dict(you=actor,cycle=self.cycle,cycles_remaining=CYCLES-self.cycle,task=task,events=visible,
                    your_pending_production=[dict(due_cycle=t,action=a) for t,p,a in self.pending if p==actor])
    def execute(self,actor,action):
        start=len(self.events)
        handled=self.native.shapefactory_apply_action(self.state,actor,action,self.emit)
        if not handled:self.emit(event_type='action_rejected',actor_id=actor,visibility='private',payload=dict(action=action,error_message='Native action rejected: check current funds, inventory, order indices and offer status.'))
        self.state.task_state['steps_taken']+=1
        return handled and not any(e['event_type']=='action_rejected' for e in self.events[start:])
    def submit(self,actor,action):
        error=validate(action)
        if error:
            self.emit(event_type='action_rejected',actor_id=actor,visibility='private',payload=dict(action=action,error_message=error));return False
        kind=action['type'];p=action['payload']
        if kind=='message':
            if actor in p['recipients']:return self.reject(actor,action,'Cannot message yourself')
            self.emit(event_type='message',actor_id=actor,visibility='private',recipients=p['recipients'],payload=p);return True
        if kind=='propose_trade_offer' and p['target_id']==actor:return self.reject(actor,action,'Cannot trade with yourself')
        if kind=='do_nothing':return True
        if kind=='produce_shape':
            # Native time-mode applies cost, inventory and cap checks at completion, not admission.
            self.pending.append((self.cycle+3,actor,deepcopy(action)))
            self.emit(event_type='production_scheduled',actor_id=actor,visibility='private',payload=dict(action=action,due_cycle=self.cycle+3));return True
        return self.execute(actor,action)
    def reject(self,actor,action,error):
        self.emit(event_type='action_rejected',actor_id=actor,visibility='private',payload=dict(action=action,error_message=error));return False
    def metrics(self):
        ps=self.state.task_state['participants'];progress=sum(p['order_progress'] for p in ps.values())
        return dict(mean_final_balance=sum(p['money'] for p in ps.values())/4,completed_fraction=progress/8,
                    all_orders_completed=progress==8,individual_balances={a:p['money'] for a,p in ps.items()},
                    completed_items=progress,trades=sum(t['status']=='accepted' for t in self.state.task_state['completed_trades']),
                    inventory={a:p['inventory'] for a,p in ps.items()},
                    production={a:p['production_number'] for a,p in ps.items()},
                    production_by_shape=dict(Counter({s:sum(e['payload']['quantity'] for e in self.events if e['event_type']=='shape_produced' and e['payload']['shape']==s) for s in SHAPES})),
                    messages=sum(e['event_type']=='message' for e in self.events),
                    semantic_rejections=sum(e['event_type']=='action_rejected' for e in self.events))

def validate(action):
    if not isinstance(action,dict) or set(action)!={'type','payload'} or action['type'] not in ACTIONS or not isinstance(action['payload'],dict):return 'Expected one enabled action with type and payload'
    k=action['type'];p=action['payload']
    if k in ('produce_shape','propose_trade_offer'):
        if p.get('shape') not in SHAPES or type(p.get('quantity',1)) is not int or not 1<=p.get('quantity',1)<=3:return 'Invalid shape or quantity'
    if k=='propose_trade_offer':
        if p.get('offer_type') not in ('buy','sell') or p.get('target_id') not in IDS or type(p.get('price_per_unit')) not in (int,float) or not 15<=p['price_per_unit']<=100:return 'Invalid offer fields or price'
    if k=='message':
        rs=p.get('recipients')
        if p.get('channel')!='direct' or not isinstance(rs,list) or not rs or any(a not in IDS for a in rs) or len(set(rs))!=len(rs) or not isinstance(p.get('content'),str) or not p['content']:return 'Invalid direct message'
    if k=='fulfill_order':
        ix=p.get('order_indices')
        if not isinstance(ix,list) or not ix or any(type(i) is not int or i<0 for i in ix) or len(set(ix))!=len(ix):return 'Invalid or duplicate order indices'
    if k in ('trade_response','cancel_trade_offer') and not isinstance(p.get('transaction_id'),str):return 'Missing transaction ID'
    if k=='trade_response' and p.get('response_type') not in ('accept','decline'):return 'Invalid response'
    return None

RULES='''You are one of four independent Shape Factory players. Maximize your own final money while completing your two private order items. All players have the same rules. You may produce any of circle, square, triangle: your specialty costs 15 per item, others 40. Start with 200 and no inventory. Maximum total production is 3 items per player. Production takes 3 cycles; cost and inventory changes apply at completion, subject to funds and capacity then. Producing can continue asynchronously. A fulfilled order item consumes its shape and earns 60. Order indices refer to the CURRENT remaining task list and change after fulfillment. Trading transfers actual inventory and money only when the recipient accepts and both parties can execute. Prices must be 15 through 100. Offers do not reserve inventory or money. A sell offer requires current inventory; a buy offer requires sufficient current money. Private messages do not execute trades. You have one action per cycle for 18 cycles (10 logical seconds each). All observations are taken before any agent acts this cycle; actions execute in a rotating order, so conflicts are possible. New messages/offers are visible at the next decision. Production due at the 180-second endpoint settles, with no extra action opportunity. Do not assume partners' private orders. No need to trade if self-production is preferable. Return only JSON {"action":{"type":"...","payload":{...}},"rationale":"optional short reason"}. No extra action, markdown or prose.
Payload examples (IDs must be real): message {"channel":"direct","recipients":["B"],"content":"...","content_type":"text"}; produce_shape {"shape":"circle","quantity":1}; propose_trade_offer {"offer_type":"sell","shape":"circle","price_per_unit":25,"target_id":"B","quantity":1}; trade_response {"transaction_id":"offer_0_1","response_type":"accept"}; cancel_trade_offer {"transaction_id":"offer_0_1"}; fulfill_order {"order_indices":[0]}; do_nothing {"reason":"..."}.'''

def prompt(observation):return [dict(role='system',content=RULES),dict(role='user',content=json.dumps(observation,sort_keys=True))]
