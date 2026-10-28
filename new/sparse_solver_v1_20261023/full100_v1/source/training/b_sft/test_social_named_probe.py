from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from training.b_sft import social_named_probe as named
from training.b_sft.prepare_named_bridge_probe import (
    qualitative_tasks, complete, direct_fact_tasks, acquisition_tasks, acquisition_information_audit)
from training.b_sft.remote_bp_probe import run


class NamedProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = [json.loads(x) for x in Path('new/local_data/social_runs/bp_no_catalogue_probe_v4/tasks.jsonl').read_text().splitlines()]
        cls.by_source = {t['source']: t for t in cls.tasks}

    def test_all_existing_questions_have_named_lossless_gold_in_every_output_arm(self):
        for task in self.tasks:
            for variant in (0,1):
                for arm in named.ARMS:
                    request = named.request(task,arm,variant)
                    visible = json.dumps(request)
                    for forbidden in ('action_id','proposer_action','partner_action','commitments_after',
                                      'type_catalogues','policy_sha256','action_values'):
                        self.assertNotIn(forbidden,visible)
                    answer = named.gold_answer(task,variant)
                    self.assertEqual(named.score(task,complete(task,answer,arm),arm,variant)['reward'],1)

    def test_named_additions_preserve_existing_bindings_and_refuse_withdrawal(self):
        task = self.by_source['complete_own_gain']
        names = named.Names(task['input'])
        action = dict(action='OFFER',partner_id=1,proposer_action=[1,1],partner_action=[1])
        self.assertEqual(names.action(action,0,[[1,0],[1]]),dict(action='OFFER',partner='Blair',
            self_commitments=['Maple'],partner_commitments=[]))
        action['proposer_action']=[0,1]
        with self.assertRaises(ValueError):names.action(action,0,[[1,0],[1]])

    def test_history_keeps_voluntary_response_and_setup_offer_separate(self):
        view=named.present(self.by_source['one_response_reject'])
        self.assertEqual(view['history'][-2],dict(actor='Alex',source='imposed setup',action='OFFER',
            partner='Blair',self_commitments=['Cedar'],partner_commitments=['Cedar']))
        self.assertEqual(view['history'][-1],dict(actor='Blair',source='voluntary',response='REJECT'))
        self.assertEqual(view['binding_commitments'],{'Alex':[],'Blair':[]})
        other=named.present(self.by_source['three_player_4_maintain'])
        self.assertEqual(other['your_private_investigation_answers'],{})

    def test_full_set_is_penalized_only_when_wrong_and_words_never_repair_answer(self):
        for source,reward in [('one_response_reject',0),('irrelevant_goal_response_maintains_three',1)]:
            task=self.by_source[source]
            answer=dict(judgments=[dict(player='Blair',goal='Orchard',possible_preferences=['want','neutral','avoid'],favored='undetermined')])
            for arm in named.ARMS:
                self.assertEqual(named.score(task,complete(task,answer,arm,'Only avoid remains.'),arm)['reward'],reward)
        for task in direct_fact_tasks():
            gold=named.gold_answer(task)
            self.assertEqual(len(gold['judgments'][0]['possible_preferences']),1)
            wrong=deepcopy(gold);wrong['judgments'][0]['possible_preferences']=['want','neutral','avoid']
            self.assertEqual(named.score(task,complete(task,wrong,'text'),'text')['reward'],0)

    def test_qualitative_same_state_changes_choice_without_hidden_point_weights(self):
        ts={t['source']:t for t in qualitative_tasks()}
        likely=ts['qualitative_avoid_likely_0'];unlikely=ts['qualitative_avoid_unlikely_0']
        self.assertEqual(likely['input']['current_state'],unlikely['input']['current_state'])
        self.assertEqual(likely['teacher']['worlds'],unlikely['teacher']['worlds'])
        self.assertEqual(len(unlikely['teacher']['worlds']),3)
        self.assertNotEqual(likely['teacher']['acceptable_actions'],unlikely['teacher']['acceptable_actions'])
        for t in ts.values():
            prompt=str(named.request(t))
            for secret in ('audit_envelopes','per_world_payoffs','0.45','0.99','type_catalogues'):
                self.assertNotIn(secret,prompt)
            cert=t['teacher']['qualitative_certificate']
            if t['teacher']['claims'][0]['level']=='certain':
                self.assertEqual(named.present(t)['your_current_belief']['unresolved_preferences'],[])
                self.assertEqual(named.present(t)['your_current_belief']['known_preferences']['Blair']['Orchard'],'avoid')
            if t['teacher']['claims'][0]['level']=='almost_certain':
                self.assertEqual(len(named.present(t)['your_current_belief']['unresolved_preferences']),1)
            if cert['status']=='ambiguous_information':
                action=named.present(t)['legal_actions'][0]
                self.assertIsNone(named.score(t,complete(t,action,'text'),'text')['reward'])
            else:
                self.assertEqual(named.score(t,complete(t,named.gold_answer(t),'text'),'text')['reward'],1)

    def test_sampler_preflights_every_arm_and_handles_text_without_tools(self):
        tasks=[self.by_source['one_response_reject'],self.by_source['complete_own_gain']]
        requests=[]
        for t in tasks:
            for arm in named.ARMS:
                requests.append(dict(task_id=t['id']+arm,task=t['task'],output_arm=arm,request=named.request(t,arm)))
        class Response:
            def __init__(self,payload):self.payload=payload
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):
                if self.payload.get('tools'):
                    msg=dict(tool_calls=[dict(function=dict(name=self.payload['tools'][0]['function']['name'],arguments='{}'))])
                    finish='tool_calls'
                else:
                    msg=dict(content='{"reasoning":"A brief explanation.","answer":{}}');finish='stop'
                return json.dumps(dict(choices=[dict(message=msg,finish_reason=finish)])).encode()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'requests.jsonl';path.write_text(''.join(json.dumps(x)+'\n' for x in requests))
            with patch('training.b_sft.remote_bp_probe.urlopen',side_effect=lambda req,timeout:Response(json.loads(req.data))):
                result=run(path,Path(d)/'results',['http://local/v1'],'test',preflight=True)
            self.assertEqual(result['requests_sent'],6)
            self.assertEqual(result['native_submissions'],4)
            self.assertEqual(result['text_submissions'],2)

    def test_active_investigate_chain_and_same_history_information_value(self):
        tasks=list(acquisition_tasks())
        root=next(t for t in tasks if t['source']=='investigate_acquisition_root')
        self.assertEqual(root['teacher']['acceptable_actions'],[dict(action='INVESTIGATE',player=1,goal=0)])
        end=next(t for t in tasks if t['source']=='acquisition_same_game_last_turn')
        self.assertFalse(any(a.get('action')=='INVESTIGATE' for a in end['teacher']['acceptable_actions']))
        plans=[t for t in tasks if t['skill']=='investigate_then_use_answer']
        self.assertEqual(len(plans),3)
        self.assertNotEqual(plans[0]['teacher']['acceptable_actions'],plans[-1]['teacher']['acceptable_actions'])
        self.assertTrue(all(t['input']['voluntary_history']==plans[0]['input']['voluntary_history'] for t in plans))
        for t in tasks:
            self.assertEqual(named.score(t,complete(t,named.gold_answer(t),'text'),'text')['reward'],1)
        audit=acquisition_information_audit()
        self.assertTrue(audit['native']['all_values_match'])
        self.assertAlmostEqual(audit['with_private_answer'][0],audit['best_without_answer'][0])
        self.assertGreater(audit['with_private_answer'][1]-audit['best_without_answer'][1],.3)

    def test_preflight_records_model_protocol_failures_without_blocking(self):
        # All three observed remote failure shapes plus a token-budget failure.
        cases=[
            ('B','joint_tool',dict(content='<tool_call>{"name":"SUBMIT_BELIEFS"}</tool_call>',tool_calls=[]),'stop'),
            ('B','text',dict(content='{"reasoning":"Evidence","answer":[]}'),'stop'),
            ('P','text',dict(content='{"reasoning":"Plan","answer":"OFFER","partner":"Blair"}'),'stop'),
            ('P','separate_tool',dict(content='An unfinished plan'),'length'),
        ]
        class Response:
            def __init__(self,message,finish):self.body=dict(choices=[dict(message=message,finish_reason=finish)])
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(self.body).encode()
        requests=[]
        for i,(task,arm,_,_) in enumerate(cases):
            native=self.by_source['one_response_reject' if task=='B' else 'complete_own_gain']
            requests.append(dict(task_id=str(i),task=task,output_arm=arm,request=named.request(native,arm)))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'requests.jsonl';path.write_text(''.join(json.dumps(x)+'\n' for x in requests))
            with patch('training.b_sft.remote_bp_probe.urlopen',side_effect=[Response(msg,finish) for _,_,msg,finish in cases]):
                result=run(path,Path(d)/'results',['http://local/v1'],'test',preflight=True)
            self.assertEqual(result['completed'],4)
            self.assertEqual(result['completed_without_protocol_submission'],4)
            self.assertEqual(result['infrastructure_failures'],0)
            self.assertEqual(result['truncated_submissions'],1)
            rows=[json.loads(x) for x in (Path(d)/'results/samples.jsonl').read_text().splitlines()]
            self.assertEqual([r['raw_message'] for r in rows],[c[2] for c in cases])

    def test_preflight_still_blocks_transport_and_response_envelope_failures(self):
        task=self.by_source['one_response_reject']
        class MalformedResponse:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"choices":[{"message":null,"finish_reason":"stop"}]}'
        for response in [HTTPError('http://local/v1',503,'Unavailable',{},None),MalformedResponse()]:
            with self.subTest(response=type(response).__name__),tempfile.TemporaryDirectory() as d:
                path=Path(d)/'requests.jsonl'
                path.write_text(json.dumps(dict(task_id=task['id'],task='B',request=named.request(task)))+'\n')
                with patch('training.b_sft.remote_bp_probe.urlopen',side_effect=[response]):
                    with self.assertRaisesRegex(RuntimeError,'transport or response-envelope'):
                        run(path,Path(d)/'results',['http://local/v1'],'test',preflight=True)
                summary=json.loads((Path(d)/'results/summary.json').read_text())
                self.assertEqual(summary['infrastructure_failures'],1)
                self.assertEqual(summary['completed'],0)

    def test_registered_action_tools_preserve_every_legal_choice_and_score(self):
        tasks=self.tasks + list(acquisition_tasks())
        for task in tasks:
            for variant in (0,1):
                req=named.request(task,'action_tools',variant)
                if task['task']=='B':
                    self.assertEqual([x['function']['name'] for x in req['tools']],['SUBMIT_BELIEFS'])
                    self.assertEqual(named.score(task,complete(task,named.gold_answer(task,variant),'action_tools'),
                                                 'action_tools',variant)['reward'],1)
                    continue
                visible=named.present(task,variant)
                declared={x['function']['name'] for x in req['tools']}
                self.assertNotIn('SUBMIT_ACTION',declared)
                for action in visible['legal_actions']:
                    name,args=named.action_call(action)
                    self.assertIn(name,declared)
                    result=named.score(task,complete(task,action,'action_tools'),'action_tools',variant)
                    old=named.score(task,complete(task,action,'separate_tool'),'separate_tool',variant)
                    self.assertEqual(result,old)

    def test_action_tools_reject_wrong_targets_wrappers_and_multiple_calls(self):
        task=next(t for t in acquisition_tasks() if t['source']=='investigate_acquisition_root')
        good=complete(task,named.gold_answer(task),'action_tools')
        self.assertEqual(good['raw_message']['tool_calls'][0]['function']['name'],'INVESTIGATE')
        for args in [dict(player='Alex',goal='Orchard'),dict(player='Blair',goal='Missing'),
                     dict(action='INVESTIGATE',player='Blair',goal='Orchard')]:
            bad=deepcopy(good)
            bad['raw_message']['tool_calls'][0]['function']['arguments']=json.dumps(args)
            self.assertEqual(named.score(task,bad,'action_tools')['status'],'format_failure')
        duplicate=deepcopy(good);duplicate['raw_message']['tool_calls']*=2
        self.assertEqual(named.score(task,duplicate,'action_tools')['status'],'format_failure')
        self.assertEqual(named.score(task,good,'separate_tool')['status'],'format_failure')
        wrapper=complete(task,named.gold_answer(task),'separate_tool')
        self.assertEqual(named.score(task,wrapper,'action_tools')['status'],'format_failure')
        # Known/irrelevant goals remain legal choices, but incorrect for this task.
        wrong=complete(task,dict(action='INVESTIGATE',player='Blair',goal='Harbor'),'action_tools')
        self.assertEqual(named.score(task,wrong,'action_tools')['reward'],0)

    def test_preflight_accepts_a_registered_tool_other_than_the_first(self):
        task=next(t for t in acquisition_tasks() if t['source']=='investigate_acquisition_root')
        payload=named.request(task,'action_tools')
        self.assertNotEqual(payload['tools'][0]['function']['name'],'INVESTIGATE')
        message=complete(task,named.gold_answer(task),'action_tools')['raw_message']
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(dict(choices=[dict(message=message,finish_reason='tool_calls')])).encode()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'requests.jsonl'
            path.write_text(json.dumps(dict(task_id=task['id'],task='P',output_arm='action_tools',request=payload))+'\n')
            with patch('training.b_sft.remote_bp_probe.urlopen',return_value=Response()):
                result=run(path,Path(d)/'results',['http://local/v1'],'test',preflight=True)
            self.assertEqual(result['native_submissions'],1)


if __name__=='__main__':unittest.main()
