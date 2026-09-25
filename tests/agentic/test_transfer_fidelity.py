import json
import subprocess
import sys

import pytest

from examples.final_evaluation.shapefactory_lite_3p import config, UPSTREAM, verify_source
from examples.final_evaluation.shapefactory_native_summary import summarize, event_metrics


def test_three_player_configs_preserve_native_rules_and_explicit_budget():
    verify_source()
    for visibility in ('private', 'dashboard'):
        for reverse in (False, True):
            base, cfg = config(visibility, reverse, 'test', 'http://localhost:8000/v1')
            for key in ('prompts', 'protocol', 'probe', 'controls', 'action_space'):
                assert cfg[key] == base[key]
            for key, value in base['task'].items():
                if key not in ('shapes_order','shapes_types','shape_options','specialties'):
                    assert cfg['task'][key] == value
            assert len(cfg['agents']) == 3
            assert all(a['model']['max_tokens'] == 4096 for a in cfg['agents'])
            assert cfg['experiment']['duration_sec'] == 900
            assert cfg['task']['shapes_order'] == 1


def test_native_three_player_self_supply_and_trade_ring():
    script = '''
import json,sys
from types import SimpleNamespace
from src.tasks.shapefactory import shapefactory_init_state,shapefactory_apply_action
cfg=json.loads(sys.argv[1])
for trading in (False, True):
 state=SimpleNamespace(task_state=shapefactory_init_state(cfg));events=[]
 def emit(**event):events.append(event)
 def act(actor,kind,**payload):
  assert shapefactory_apply_action(state,actor,dict(type=kind,payload=payload),emit), (actor,kind,payload)
 people=state.task_state['participants']
 for actor,p in people.items():
  assert len(p['tasks'])==1 and p['tasks'][0]!=p['specialty']
  act(actor,'produce_shape',shape=p['specialty'] if trading else p['tasks'][0],quantity=1)
 if trading:
  for buyer,p in people.items():
   seller=next(a for a,s in people.items() if s['specialty']==p['tasks'][0])
   act(seller,'propose_trade_offer',offer_type='sell',shape=p['tasks'][0],price_per_unit=20,target_id=buyer,quantity=1)
   offer=state.task_state['pending_offers'][-1]
   act(buyer,'trade_response',transaction_id=offer['id'],response_type='accept')
 for actor,p in people.items():
  act(actor,'fulfill_order',order_indices=[0])
  assert p['order_progress']==1
 assert sum(p['money'] for p in people.values()) == (735 if trading else 660)
'''
    for reverse in (False, True):
        _, cfg = config('private', reverse, 'test', 'http://localhost/v1')
        subprocess.run([sys.executable, '-c', script, json.dumps(cfg)], cwd=UPSTREAM, check=True)


def test_summary_matches_native_metrics_and_distinguishes_partial_orders(tmp_path):
    import yaml
    cfg={'agents':[{'id':'A'},{'id':'B'}], 'task':{'type':'shapefactory','shapes_order':2}}
    summary={'per_agent':{'A':{'final_balance':220,'order_progress':1},'B':{'final_balance':260,'order_progress':2}},'task_summary':{'completed_trades':3}}
    events=[{'event_type':'trade_offer_created'} for _ in range(3)] + [
        {'event_type':'trade_offer_responded','actor_id':'B','payload':{'response_type':'accept','initiator_id':'A'}},
        {'event_type':'trade_offer_responded','payload':{'response_type':'decline'}},
        {'event_type':'trade_offer_cancelled'},
    ] + [{'event_type':'message_delivered','actor_id':'A','payload':{'content':'hello'}} for _ in range(4)]
    (tmp_path/'manifest.json').write_text(json.dumps({'jobs':[{'id':'g'}]}))
    (tmp_path/'g.yml').write_text(yaml.safe_dump(cfg));(tmp_path/'g.exit_code').write_text('0')
    (tmp_path/'g').mkdir();(tmp_path/'g/run_summary.json').write_text(json.dumps(summary))
    path=tmp_path/'g/events.jsonl';path.write_text(json.dumps(events))
    row=summarize(tmp_path)['games'][0]
    assert row['order_fulfillment_rate']==.5 and row['fulfilled_order_items']==3
    assert row['successful_trades']==1 and row['resolved_offers_native']==3
    assert row['messages_per_successful_trade']==4
    script='''
import json,sys
from pathlib import Path
from analysis.trace_parser import Trace
from analysis.task_metrics import _shapefactory_metrics
cfg,summary,events=json.loads(sys.argv[1]);t=Trace(Path('.'),events=events,manifest={'config':cfg},summary=summary)
m,_=_shapefactory_metrics(t)
print(json.dumps(m))
'''
    native=json.loads(subprocess.check_output([sys.executable,'-c',script,json.dumps([cfg,summary,events])],cwd=UPSTREAM))
    assert row['mean_final_balance']==native['session_avg_wealth']
    assert row['trade_accept_rate']==native['trade_accept_rate']
    assert row['agents_fully_fulfilled']==native['agents_fully_fulfilled_own_order_count']
    assert row['messages_per_successful_trade']==native['messages_per_successful_trade']
    path.write_text('\n'.join(json.dumps(e) for e in events))
    assert event_metrics(path)['successful_trades']==1
    path.write_text('[]')
    assert event_metrics(path)['messages_per_successful_trade'] is None
    (tmp_path/'g.exit_code').write_text('1')
    assert 'aggregate' not in summarize(tmp_path)
