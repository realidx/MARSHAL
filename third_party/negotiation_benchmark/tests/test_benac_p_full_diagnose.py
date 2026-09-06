"""Full-suite contracts: interventions, leakage, four-cell scoring and resume."""
from dataclasses import replace
import json
import numpy as np
import pytest
from benac_p.diagnose_suite import (
    Suite, generated_pack, action_branches, action_info, request_payload,
    score, summarize, validate_answer, run_tasks, cluster_summary, digest,
)


@pytest.fixture(scope='module')
def suite():
    return Suite(n_games=2,seed=12300).build()


def oracle_records(suite):
    records={}
    for task in suite.tasks:
        label=suite.labels[task['id']]
        if task['kind']=='belief':answer={'probabilities':label['posterior']}
        elif task['kind']=='planning':answer={'action_index':int(np.argmax(label['q']))}
        else:answer={'utilities':label['utilities']}
        records[task['id']]={'status':'ok','answer':answer}
    return records


def test_unfiltered_generator_reproducibility_and_disjoint_splits(suite):
    assert generated_pack(98,'confirmation').spec.to_dict(include_private=True)==generated_pack(98,'confirmation').spec.to_dict(include_private=True)
    assert suite.pack_map['g12300'].split=='discovery'
    assert suite.pack_map['d12301'].split=='confirmation'
    assert suite.pack_map['anchor'].split=='calibration'
    assert len({t['id'] for t in suite.tasks})==len(suite.tasks)


def test_belief_and_planning_are_separate_and_labels_never_sent(suite):
    tasks={t['id']:t for t in suite.tasks}
    cid='anchor/high/CHOOSE_1'
    belief=tasks[cid+'/belief']; oracle=tasks[cid+'/plan_oracle']; model=tasks[cid+'/plan_model']
    assert 'legal_actions' not in belief['input']
    assert 'current_probabilities' not in belief['input']
    assert oracle['input']['observation']['transcript']==[]
    assert 'initial_probabilities' not in oracle['input']
    records=oracle_records(suite)
    a=request_payload(oracle,records); b=request_payload(model,records)
    assert a==b  # Identical prompt when the injected values are equal.
    for task in suite.tasks:
        assert not any(k in task['input'] for k in ('q','optimum','posterior','private_preferences'))
    records[cid+'/belief']={'status':'invalid'}
    with pytest.raises(ValueError):request_payload(model,records)


def test_forced_menu_enumeration_and_negative_controls(suite):
    for cert in suite.certificates:
        pack=suite.pack_map[cert['game']]
        for arm in cert['arms'].values():
            assert sum(b['probability'] for b in arm['branches'])==pytest.approx(1)
        if pack.id in ('no_information','known_type'):
            assert abs(cert['matched_information_gap'])<1e-10
            assert all(abs(a['information_gain'])<1e-10 for a in cert['arms'].values())
    long=suite.contexts['horizon_long/root']['oracle']
    short=suite.contexts['horizon_short/root']['oracle']
    assert long.value>0 and short.value==0


def test_all_oracle_factorial_and_dynamic_chooser_control(suite):
    records=oracle_records(suite)
    fixed_count=len(suite.tasks)
    suite.add_model_branches(records)
    assert len(suite.tasks)>fixed_count
    records=oracle_records(suite)
    scored=score(suite,records)
    assert all(r.get('regret',0)<1e-8 and r.get('excess_brier',0)<1e-8 for r in scored['results'])
    assert all(abs(r['interaction'])<1e-8 for r in scored['factorial'])
    for r in scored['active']:
        assert abs(r['chooser_repair_effect'])<1e-8
        assert abs(r['updater_repair_effect'])<1e-8
        assert abs(r['chooser_updater_interaction'])<1e-8
    summary=summarize(suite,scored)
    assert summary['confirmation']['independent_planning']['mean']==0
    assert summary['confirmation']['belief']['n_games']==1


def test_incomplete_games_not_renormalized_and_cluster_not_turn(suite):
    rows=[{'game':'a','weight':.9,'x':1},{'game':'a','weight':.1}, {'game':'b','weight':1,'x':2}]
    s=cluster_summary(rows,'x')
    assert s['n_games']==1 and s['mean']==2 and s['excluded_incomplete_games']==1
    s=cluster_summary([{'game':'a','x':1}]*100+[{'game':'b','x':3}],'x')
    assert s['mean']==2 and s['n_games']==2


def test_dependency_runner_and_resume_without_http(suite,tmp_path):
    chosen=[t for t in suite.tasks if t['id'] in ('anchor/root/belief','anchor/root/plan_model')]
    class Client:
        calls=0
        def complete(self,messages,**kwargs):
            self.calls+=1
            payload=json.loads(messages[1]['content'])
            if 'probabilities' in payload['output_schema']:return '{"probabilities":[0.5,0.5]}'
            assert payload['problem']['current_probabilities']==[.5,.5]
            return '{"action_index":0}'
    client=Client();records={}
    run_tasks(suite,chosen,records,client,tmp_path,workers=2)
    assert client.calls==2 and all(r['status']=='ok' for r in records.values())
    run_tasks(suite,chosen,records,client,tmp_path,workers=2)
    assert client.calls==2
    loaded=json.loads((tmp_path/'answers.json').read_text())
    assert loaded==records


def test_screening_is_certified_before_model_calls(suite):
    p=suite.pack_map['d12301']; ctx=suite.contexts['d12301/root']
    assert p.screening['root_action_regret']>.005
    assert p.screening['same_action_update_gain']>.02
    assert ctx['oracle'].value==pytest.approx(p.screening['adaptive_value'])
    from benac_p.menu_diagnose import root_comparison
    certified=root_comparison(p.spec,p.prior,p.policies)
    assert certified['root_action_regret']==pytest.approx(p.screening['root_action_regret'])
    assert certified['same_menu_update_gain']==pytest.approx(p.screening['same_action_update_gain'])


def test_belief_causal_effect_can_be_additive(suite):
    from benac_p.bayes_planner import BayesPlanner
    from benac_p.diagnose_suite import with_probabilities
    from benac_p.observations import build_player_observation
    records=oracle_records(suite)
    # Deliberately wrong updater, but perfect planner conditional on its input.
    for cid,ctx in suite.contexts.items():
        if '/optimal/' not in cid or len(ctx['belief'].hypotheses)!=2:continue
        p=[1.,0.] if ctx['belief'].probabilities[0]<.5 else [0.,1.]
        planner=BayesPlanner(partner_policies=ctx['pack'].policies)
        action=planner.act(build_player_observation(ctx['state'],0),with_probabilities(ctx['belief'],p))
        if ctx['oracle'].regret(action)>.01:
            records[cid+'/belief']['answer']={'probabilities':p}
            records[cid+'/plan_model']['answer']={'action_index':ctx['actions'].index(action)}
            break
    else:raise AssertionError('No task-relevant belief intervention found.')
    result=next(r for r in score(suite,records)['factorial'] if r['case']==cid)
    assert result['belief_repair_effect']>.01
    assert abs(result['planner_repair_effect'])<1e-8
    assert abs(result['interaction'])<1e-8


def test_complete_cli_and_resume_with_mock_service(tmp_path,monkeypatch):
    from benac_p.diagnose_suite import main
    import methods.vllm_client
    class Client:
        calls=0
        def __init__(self,*args,**kwargs):pass
        def complete(self,messages,**kwargs):
            Client.calls+=1
            request=json.loads(messages[1]['content']);p=request['problem'];schema=request['output_schema']
            if 'probabilities' in schema:
                n=len(p.get('initial_probabilities',[1.]))
                return json.dumps({'probabilities':[1/n]*n})
            if 'utilities' in schema:return json.dumps({'utilities':[0]*len(p['options'])})
            return '{"action_index":0}'
    monkeypatch.setattr(methods.vllm_client,'OpenAICompatibleNegotiationClient',Client)
    args=['--output-dir',str(tmp_path),'--n-games','0','--model','mock-only','--base-url','http://unused.invalid','--workers','2']
    main(args)
    count=Client.calls
    assert count>200
    assert (tmp_path/'report.md').exists()
    scores=json.loads((tmp_path/'scores.json').read_text())
    assert all(r['status']=='ok' for r in scores['results'])
    assert len(json.loads((tmp_path/'dynamic_tasks.json').read_text()))>0
    main(args+['--resume'])
    assert Client.calls==count
