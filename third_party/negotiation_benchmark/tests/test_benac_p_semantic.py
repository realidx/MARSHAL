"""Semantic oracle certificates, causal interfaces, rollout scoring and resume."""
from copy import deepcopy
from dataclasses import replace
import json
import numpy as np
import pytest
from benac_p.semantic_game import SemanticGame, PREFERENCES
from benac_p.semantic_suite import Suite, score, summarize, main
from benac_p.diagnose_protocol import submission_tool
from methods.vllm_client import VLLMChatCompletion, VLLMToolCall


def oracle_records(suite):
    records={}
    for t in suite.tasks:
        records[t['id']]=dict(status='ok',answer=suite.oracle_answer(t,records))
    return records


@pytest.fixture(scope='module')
def suite():return Suite(2,20000).build()


def test_deterministic_terminal_rationality_and_matched_controls():
    for seed in range(101,106):
        for condition in ('unknown_relevant','known','unknown_irrelevant'):
            g=SemanticGame(seed,condition);cert=g.certify()
            assert cert['rational_response_decisions']>30
            assert not cert['partner_behavior_randomness']
            q=cert['root_q']
            if condition=='unknown_relevant':assert q['assess_menu']>q['prepare']
            else:assert q['prepare']>q['assess_menu']
            assert len({tuple(goal.required_actions) for goal in g.spec.goals})==len(g.spec.goals)
            for pref in PREFERENCES:
                for move in g.moves(g.initial()):
                    a=g.execute(g.initial(),move,pref);b=g.execute(g.initial(),move,pref)
                    assert a[0]==b[0] and a[1].snapshot_commitments()==b[1].snapshot_commitments()


def test_response_has_no_access_to_other_private_preferences():
    g=SemanticGame(20000);state=g.initial()
    move=next(m for m in g.moves(state) if m.key=='assess_menu')
    own=g.rows['want'][1]
    response=g.response(state,move,own)
    matrix=np.full_like(g.spec.private_preferences,-1)
    state.spec=replace(g.spec,private_preferences=matrix)
    assert g.response(state,move,own)==response=='CHOOSE_1'
    assert g.response(state,move,g.rows['neutral'][1])=='REJECT'
    assert g.response(state,move,g.rows['avoid'][1])=='CHOOSE_2'


def test_logical_support_and_enumeration_not_random_responses():
    g=SemanticGame(20100);root=g.initial();moves={m.key:m for m in g.moves(root)}
    menu=g.branches(root,PREFERENCES,moves['assess_menu'])
    assert {b['response']:b['support'] for b in menu}=={'CHOOSE_1':('want',),'REJECT':('neutral',),'CHOOSE_2':('avoid',)}
    assert sum(b['weight'] for b in menu)==pytest.approx(1)
    prep=g.branches(root,PREFERENCES,moves['prepare'])
    assert len(prep)==1 and prep[0]['support']==PREFERENCES
    single=g.branches(root,PREFERENCES,moves['assess_a'])
    assert next(b['support'] for b in single if b['response']=='REJECT')==('neutral','avoid')


def test_informative_menu_can_irreversibly_destroy_the_route():
    g=SemanticGame(20300);root=g.initial();moves={m.key:m for m in g.moves(root)}
    q={m.key:v for m,v in g.q_values(root,g.support)}
    assert q['committing_menu']<q['assess_menu']
    free=g.branches(root,g.support,moves['assess_menu'])
    locked=g.branches(root,g.support,moves['committing_menu'])
    assert [(b['response'],b['support']) for b in free]==[(b['response'],b['support']) for b in locked]
    for b in locked:
        if b['response']!='REJECT':
            assert len(g.moves(b['state']))==1
            assert sum(b['state'].commitments[0,1:4])==1
            assert b['state'].commitments[0,0]==1


def test_semantic_inputs_and_clean_judgment_intervention(suite):
    records=oracle_records(suite);tasks={t['id']:t for t in suite.tasks}
    for cid,ctx in suite.cases.items():
        b=tasks[cid+'/belief'];p=tasks[cid+'/plan_oracle'];m=tasks[cid+'/plan_model']
        assert b['kind']=='semantic_belief' and 'legal_actions' not in b['input']
        assert 'history' not in p['input'] and 'initially_possible_preferences' not in p['input']
        assert suite.payload(p,records)==suite.payload(m,records)
        public=json.dumps(p['input'])
        assert not any(x in public for x in ('log_probabilities','root_q','private_preferences','temperature','softmax'))
        assert 'probabilities' not in submission_tool(b)['function']['parameters']['properties']
    # Same sufficient planning state across informative responses; only judgment differs.
    gid='b20000/unknown_relevant'
    payloads=[deepcopy(tasks[b['case']+'/plan_oracle']['input']) for b in suite.arms[gid]['oracle']['branches']]
    for p in payloads:p.pop('partner_judgment')
    assert payloads[0]==payloads[1]==payloads[2]


def test_all_oracle_tables_and_engine_rollouts(suite):
    records=oracle_records(suite);suite.add_model_arms(records);records=oracle_records(suite)
    scores=score(suite,records);summary=summarize(suite,scores)
    for split in summary.values():
        for name,s in split.items():
            if name=='matched_control':continue
            assert s['belief_exact']['mean']==1
            assert s['OL']['mean']==s['belief_repair']['mean']==s['end_to_end_regret']['mean']==0
    for a in scores['active']:
        assert a['chooser_repair']==a['updater_repair_model_action']==a['updater_repair_oracle_action']==0
        rr=[r for r in scores['rollouts'] if r['game']==a['game']]
        assert sum(r['weight']*r['terminal_utilities'][0] for r in rr)==pytest.approx(a['end_to_end_utility'])
        assert all(len(r['history'])==3 for r in rr)


def test_belief_repair_has_positive_cost_for_wrong_judgment():
    s=Suite(2,20200).build();records=oracle_records(s)
    for t in s.tasks:
        if t['kind']=='semantic_belief' and '/after_assess_menu/' in t['id'] and '/unknown_relevant/' in t['id']:
            true=s.labels[t['id']]['possible_preferences'][0]
            records[t['id']]['answer']={'possible_preferences':[next(p for p in PREFERENCES if p!=true)]}
    for t in s.tasks:
        if t['parent']:records[t['id']]['answer']=s.oracle_answer(t,records)
    rows=score(s,records)['factorial']
    selected=[r for r in rows if '/after_assess_menu/' in r['case'] and '/unknown_relevant/' in r['case']]
    assert selected and all(r['belief_repair']>0 and r['OL']==0 for r in selected)


def test_missing_branch_excludes_game_without_renormalizing():
    s=Suite(2,20400).build();records=oracle_records(s);s.add_model_arms(records);records=oracle_records(s)
    gid='b20401/unknown_relevant';cid=s.arms[gid]['oracle']['branches'][0]['case']
    records[cid+'/plan_model']={'status':'invalid'}
    scored=score(s,records);summary=summarize(s,scored)['confirmation']['unknown_relevant']
    assert summary['R']['OO']['n_games']==0
    assert summary['belief_repair']['n_games']==0
    assert summary['end_to_end_regret']['n_games']==0
    assert summary['belief_exact']['n_games']==1


def test_model_chooser_with_no_evidence_is_distinguished_from_bad_updater():
    s=Suite(2,20600).build();records=oracle_records(s)
    for gid in s.games:
        ctx=s.cases[gid+'/root'];i=next(i for i,m in enumerate(ctx['moves']) if m.key=='prepare')
        records[gid+'/root/plan_oracle']['answer']={'action_index':i}
    s.add_model_arms(records)
    for t in s.tasks:
        if t['id'] not in records:records[t['id']]=dict(status='ok',answer=s.oracle_answer(t,records))
    a=next(a for a in score(s,records)['active'] if a['condition']=='unknown_relevant')
    assert a['arms']['model']['information_gain']==0
    assert a['arms']['model']['belief_exact']==1
    assert a['channel_information_repair']>0 and a['chooser_repair']>0
    assert a['updater_repair_model_action']==0


def test_mock_native_end_to_end_dynamic_calls_and_resume(tmp_path,monkeypatch):
    import methods.vllm_client
    class Client:
        calls=0
        def __init__(self,*a,**kw):assert kw['max_tokens']==1024
        def complete_with_tools(self,messages,**kwargs):
            Client.calls+=1;p=json.loads(messages[1]['content'])
            assert 'Briefly reason about' in messages[0]['content']
            assert '100 words' not in messages[0]['content']
            tool=kwargs['tools'][0]['function']['name']
            if tool=='SUBMIT_JUDGMENT':answer={'possible_preferences':p['initially_possible_preferences']}
            else:
                # Deliberately choose a non-reference root interaction to exercise dynamic arms.
                i=next((a['action_index'] for a in p['legal_actions'] if 'first assessment alone' in a['proposal']),0)
                answer={'action_index':i}
            return VLLMChatCompletion('Brief reasoning.',(VLLMToolCall(tool,answer),),{}, {'completion_tokens':100},'tool_calls')
    monkeypatch.setattr(methods.vllm_client,'OpenAICompatibleNegotiationClient',Client)
    args=['--n-games','2','--seed','20800','--output-dir',str(tmp_path),'--model','mock']
    main(args);count=Client.calls
    assert count>48
    assert json.loads((tmp_path/'dynamic_tasks.json').read_text())
    assert json.loads((tmp_path/'rollouts.json').read_text())
    assert json.loads((tmp_path/'protocol_summary.json').read_text())['mean_completion_tokens']==100
    main(args+['--resume']);assert Client.calls==count
    main(args+['--score-only']);assert Client.calls==count
    with pytest.raises(SystemExit):main(args+['--resume','--max-tokens','2048'])
    records=json.loads((tmp_path/'answers.json').read_text())
    first=next(k for k,v in records.items() if 'payload_hash' in v)
    records[first]['payload_hash']='tampered';(tmp_path/'answers.json').write_text(json.dumps(records))
    with pytest.raises(ValueError):main(args+['--resume'])


def test_belief_preflight_checks_all_four_and_preserves_wrong_answers(suite,tmp_path,monkeypatch):
    from copy import deepcopy
    from benac_p.semantic_suite import belief_preflight, BELIEF_QUESTION
    original=deepcopy(suite.tasks)
    calls=[]
    def fake_generate(client,task,payload,*args):
        calls.append(deepcopy(payload))
        assert payload['history']==[] and payload['question']==BELIEF_QUESTION
        answer=payload['initially_possible_preferences']
        if answer==['avoid']:answer=['want','neutral','avoid']
        return dict(status='ok',answer={'possible_preferences':answer})
    monkeypatch.setattr('benac_p.semantic_suite.generate',fake_generate)
    assert not belief_preflight(suite,object(),tmp_path,'reasoning_tools','balanced',128)
    assert len(calls)==4
    assert [p['initially_possible_preferences'] for p in calls]==[['want'],['neutral'],['avoid'],['want','neutral','avoid']]
    assert not belief_preflight(suite,object(),tmp_path,'reasoning_tools','balanced',128)
    assert len(calls)==4 and suite.tasks==original
    assert belief_preflight(suite,None,tmp_path/'synthetic','reasoning_tools','balanced',128,True)
