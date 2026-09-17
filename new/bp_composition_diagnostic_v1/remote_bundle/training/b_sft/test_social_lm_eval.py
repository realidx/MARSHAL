from copy import deepcopy
import json
import unittest

from training.b_sft.online_social import OnlineSocial
from methods.vllm_client import VLLMChatCompletion,VLLMToolCall
from training.b_sft.social_cases_expand import information_fixture
from training.b_sft.social_lm_eval import (call_model,inspect_decision,DryClient,continue_episode,
    aggregate,b_metrics,temporal_pair,model_payload)


class FakeClient:
    def __init__(self, b, index=0, missing=False, truncated=False, text='my text', action=None):
        self.b=b;self.index=index;self.missing=missing;self.truncated=truncated;self.text=text;self.seen=[];self.action=action
    def complete_with_tools(self,messages,*,tools,**kwargs):
        self.seen.append((deepcopy(messages),deepcopy(tools),kwargs))
        name=tools[0]['function']['name']
        args=(dict(judgments=self.b) if name=='SUBMIT_BELIEFS' else
              deepcopy(self.action if self.action is not None else json.loads(messages[-1]['content'])['legal_actions'][self.index]))
        calls=() if self.missing else (VLLMToolCall(name,args,raw_arguments=json.dumps(args)),)
        return VLLMChatCompletion(self.text,calls,dict(content=self.text),dict(completion_tokens=5),
            'length' if self.truncated else 'tool_calls')


class AttemptClient(FakeClient):
    """Script failures independently for B and P; not an actual model."""
    def __init__(self,b,**failures):
        super().__init__(b)
        self.failures={s:list(xs) for s,xs in failures.items()}

    def complete_with_tools(self,messages,*,tools,**kwargs):
        c=super().complete_with_tools(messages,tools=tools,**kwargs)
        stage='B' if tools[0]['function']['name']=='SUBMIT_BELIEFS' else 'P'
        queue=self.failures.get(stage,[]);failure=queue.pop(0) if queue else None
        if failure=='request_error':raise ValueError('service failure')
        if failure=='truncated':
            return VLLMChatCompletion('Unfinished analysis',(),{'content':'Unfinished analysis'},
                                     {'completion_tokens':kwargs['max_tokens']},'length')
        if failure=='format':return VLLMChatCompletion(c.content,(),c.raw_message,c.usage,'stop')
        if failure=='invalid_targets':
            return VLLMChatCompletion(c.content,(VLLMToolCall('SUBMIT_BELIEFS',{'judgments':[]}),),
                                     c.raw_message,c.usage,'tool_calls')
        return c


class SocialLMEvalTests(unittest.TestCase):
    def env(self):
        raw,prefix=information_fixture();return OnlineSocial(raw,prefix)

    def test_one_retry_recovers_each_stage_without_advancing_state(self):
        env=self.env();before=deepcopy(env.context())
        correct=[dict(player=x['player'],goal=x['goal'],**x['answer']) for x in env.belief_table()]
        client=AttemptClient(correct,B=['truncated'],P=['format']);calls=[]
        r=inspect_decision(env,client,on_call=calls.append)
        self.assertEqual(env.context(),before)
        self.assertEqual(len(calls),4)
        self.assertTrue(r['B']['recovered_on_retry']);self.assertTrue(r['P']['recovered_on_retry'])
        self.assertEqual(r['actual_model_B'],correct)
        self.assertIsNone(r['B']['attempts'][0]['format_score'])
        self.assertEqual(r['P']['attempts'][0]['format_score'],-1)
        self.assertIsNone(r['supervision']['B'][0]['task_score'])
        self.assertFalse(r['supervision']['B'][0]['format_mask'])
        self.assertEqual(r['supervision']['P'][0]['format_score'],-1)
        self.assertFalse(r['supervision']['P'][0]['task_mask'])
        self.assertTrue(r['supervision']['P'][1]['task_mask'])
        self.assertEqual(r['supervision']['B'][0]['truncation_score'],-1)
        self.assertEqual(r['supervision']['B'][0]['reward'],-1)
        self.assertEqual(r['supervision']['B'][1]['reward'],0)
        self.assertEqual(r['supervision']['P'][0]['truncation_score'],0)
        self.assertEqual(r['supervision']['P'][0]['reward'],-1)
        self.assertEqual(r['supervision']['P'][1]['reward'],r['supervision']['P'][1]['task_score'])
        self.assertEqual(r['B_metrics']['score']['score'],0)
        for stage in ('B','P'):
            a,b=r[stage]['attempts']
            self.assertEqual([a['attempt_index'],b['attempt_index']],[0,1])
            self.assertEqual([a['request']['max_tokens'],b['request']['max_tokens']],[1024,1024])
            ctx=deepcopy(b['input']);self.assertIn('retry_feedback',ctx);ctx.pop('retry_feedback')
            self.assertEqual(a['input'],ctx)
        metrics=aggregate([r])['attempts']
        self.assertEqual(metrics['B']['truncations'],1)
        self.assertEqual(metrics['B']['format_failures'],0)
        self.assertEqual(metrics['P']['format_failures'],1)
        episode=continue_episode(env,env.worlds[0],client,r,lambda _:None)
        self.assertTrue(episode['terminal'])
        self.assertEqual(episode['utilities'],env.outcome(env.worlds[0]))

    def test_invalid_b_targets_retry_but_wrong_beliefs_do_not(self):
        env=self.env()
        wrong=[dict(**q,possible_preferences=['avoid'],favored='avoid') for q in env.context()['queries']]
        c=AttemptClient(wrong,B=['invalid_targets'])
        r=inspect_decision(env,c)
        self.assertEqual(r['B']['attempt_count'],2)
        self.assertEqual(r['B']['attempts'][0]['failure_category'],'format')
        self.assertTrue(r['B']['recovered_on_retry'])
        self.assertLess(r['B_metrics']['score']['score'],0)
        self.assertEqual(r['actual_model_B'],wrong)
        self.assertEqual(r['P']['attempt_count'],1)
        clean=inspect_decision(env,AttemptClient(wrong))
        self.assertEqual(clean['B']['attempt_count'],1)

    def test_two_failures_exhaust_retry_without_fabricating_an_action(self):
        env=self.env();before=deepcopy(env.context())
        c=AttemptClient([],B=['truncated','truncated'],P=['format','truncated'])
        r=inspect_decision(env,c)
        self.assertEqual(len(c.seen),4)
        self.assertEqual(r['B_handoff_status'],'unavailable')
        self.assertTrue(all(not r[s]['attempts'][-1]['retry_scheduled'] for s in ('B','P')))
        self.assertEqual([x['reward'] for x in r['supervision']['B']],[-1,-1])
        self.assertEqual([x['reward'] for x in r['supervision']['P']],[-1,-1])
        self.assertIsNone(r['P_metrics']['reference_regret'])
        e=continue_episode(env,env.worlds[0],c,r,lambda _:None)
        self.assertEqual(e['status'],'model_action_failure')
        self.assertIsNone(e['ego_utility']);self.assertEqual(env.context(),before)
        self.assertEqual(len(c.seen),4)  # Continuation cannot reset the retry allowance.

    def test_service_failure_is_not_a_model_format_penalty(self):
        env=self.env()
        correct=[dict(player=x['player'],goal=x['goal'],**x['answer']) for x in env.belief_table()]
        r=inspect_decision(env,AttemptClient(correct,B=['request_error']))
        first=r['B']['attempts'][0]
        self.assertEqual(first['failure_category'],'infrastructure')
        self.assertIsNone(first['format_score'])
        self.assertFalse(r['supervision']['B'][0]['task_mask'])
        self.assertFalse(r['supervision']['B'][0]['format_mask'])
        self.assertIsNone(r['supervision']['B'][0]['truncation_score'])
        self.assertFalse(r['supervision']['B'][0]['truncation_mask'])
        self.assertIsNone(r['supervision']['B'][0]['reward'])
        self.assertFalse(r['supervision']['B'][0]['reward_mask'])
        self.assertTrue(r['B']['recovered_on_retry'])

    def test_wrong_b_passes_unchanged_and_teacher_not_sent(self):
        env=self.env();wrong=[dict(**q,possible_preferences=['avoid'],favored='avoid') for q in env.context()['queries']]
        c=FakeClient(wrong);r=inspect_decision(env,c)
        p_context=json.loads(c.seen[1][0][-1]['content'])
        self.assertEqual(p_context['model_beliefs'],wrong)
        self.assertLess(r['B_metrics']['score']['score'],0)
        self.assertTrue(r['B_passthrough_exact'])
        for messages,tools,kw in c.seen:
            payload=json.loads(messages[-1]['content'])
            for forbidden in ('teacher_B','B_by_target','teacher_counts','environment_world','P_reference'):
                self.assertNotIn(forbidden,payload)
            self.assertEqual(kw['tool_choice'],'auto')
        self.assertIn('my text',r['B']['raw_text'])
        self.assertEqual(json.loads(c.seen[0][0][-1]['content'])['queries'],env.context()['queries'])
        self.assertIn('others_value',r['P_metrics']['reference']['values'][0])

    def test_missing_tool_never_becomes_pass_or_terminal_reward(self):
        env=self.env();c=FakeClient([],missing=True);r=inspect_decision(env,c)
        before=deepcopy(env.history)
        e=continue_episode(env,env.worlds[0],c,r,lambda _:None)
        self.assertEqual(e['status'],'model_action_failure');self.assertFalse(e['terminal'])
        self.assertIsNone(e['utilities']);self.assertEqual(env.history,before)
        self.assertEqual(json.loads(c.seen[-1][0][-1]['content'])['model_beliefs']['submission_status'],'expected_one_tool_call')
        self.assertEqual(len(c.seen),4)  # Exactly one retry per failed stage.
        self.assertEqual(aggregate([r])['P_optimal_rate_discriminating'],0)

    def test_failed_b_tool_text_never_enters_p_task(self):
        client=FakeClient([],missing=True,text='SUBMIT_BELIEFS([invented query])')
        record=inspect_decision(self.env(),client)
        payload=json.loads(client.seen[-1][0][-1]['content'])
        self.assertNotIn('SUBMIT_BELIEFS',json.dumps(payload))
        self.assertNotIn('favored_rule',payload)
        self.assertFalse(payload['model_beliefs']['judgments_available'])
        self.assertIn('invented query',record['B']['raw_text'])

    def test_bare_list_remains_a_protocol_failure_with_raw_answer_preserved(self):
        raw='[{"player":1,"goal":0,"possible_preferences":["avoid"],"favored":"avoid"}]'
        class BareListClient:
            def complete_with_tools(self,*args,**kwargs):
                return VLLMChatCompletion('My explanation.',
                    (VLLMToolCall('SUBMIT_BELIEFS',None,raw_arguments=raw),),{}, {}, 'tool_calls')
        result=call_model(BareListClient(),'B',self.env().context(),1200)
        self.assertEqual(result['status'],'malformed_arguments')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['tool_calls'][0]['raw_arguments'],raw)

    def test_invalid_targets_are_flagged_for_p_without_erasing_b_audit(self):
        env=self.env()
        invalid=[dict(player=0,goal=0,possible_preferences=['want'],favored='want')]
        client=FakeClient(invalid);record=inspect_decision(env,client)
        payload=json.loads(client.seen[-1][0][-1]['content'])
        self.assertEqual(payload['model_beliefs']['submission_status'],'invalid_judgments')
        self.assertEqual(record['B']['answer'],invalid)
        self.assertIn('unexpected_target',record['B_metrics']['score']['protocol_errors'])

    def test_public_rendering_preserves_catalogue_correlations_and_event_actors(self):
        from benac_p.endgame_diagnose import decode_action
        env=self.env();ctx=env.context();payload=model_payload('B',ctx)
        labels={1:'want',0:'neutral',-1:'avoid'}
        for p,rows in ctx['public_type_catalogues'].items():
            reconstructed=[[next(v for v,label in labels.items() if label==r[f'goal_{g}'])
                            for g in range(len(rows[0]))] for r in payload['public_type_catalogues'][p]]
            self.assertEqual(reconstructed,rows)
        node=env.game.rules.initial()
        for event,action in zip(payload['history'],ctx['history']):
            self.assertEqual(event['actor'],env.game.rules.actor(node))
            self.assertEqual(event['kind'],'setup')
            node=env.game.rules._apply(node,decode_action(action))
        for p,ids in payload['public_state']['committed_action_ids'].items():
            self.assertEqual(ids,[f'action_{a}' for a,b in enumerate(ctx['public_state']['commitments'][int(p)]) if b])
        self.assertEqual(ctx,env.context())

    def test_responder_is_distinct_from_pending_proposer(self):
        from training.b_sft.social_dataset_v4 import menu_fixture
        raw,prefix=menu_fixture();env=OnlineSocial(raw,prefix)
        payload=model_payload('P',env.context())
        self.assertEqual(payload['decision']['acting_player'],0)
        self.assertEqual(payload['decision']['responder'],0)
        self.assertEqual(payload['pending_offer']['proposer_id'],1)
        self.assertEqual(payload['decision']['proposers_after_current'],[])
        self.assertEqual(payload['decision']['pending_offer_type'],'MENU')
        self.assertEqual(payload['decision']['pending_offer_status'],'awaiting_response_not_binding')
        # Compare the displayed final-turn claim with every native transition.
        self.assertTrue(payload['decision']['current_proposer_turn_is_last'])
        for action in env.game.rules.actions(env.node):
            self.assertTrue(env.game.rules._apply(env.node,action).state.is_terminal)
        self.assertNotIn('proposer_id',env.context()['pending_offer'])

    def test_readable_views_roundtrip_all_development_histories(self):
        from pathlib import Path
        from training.b_sft.social_lm_eval import load_pack,system_for
        data=Path(__file__).resolve().parents[2]/'new/local_data/social_generalization_v4'
        if not data.exists():self.skipTest('Local development pack unavailable')
        _,points=load_pack(data,'both')
        labels={1:'want',0:'neutral',-1:'avoid'}
        def check_action(shown,native):
            if 'offers' in native:
                self.assertEqual(shown['partner_id'],native['partner_id'])
                self.assertEqual(len(shown['offers']),len(native['offers']))
                for a,b in zip(shown['offers'],native['offers']):check_action(a,b)
            elif 'proposer_action' in native:
                self.assertEqual(shown['partner_id'],native['partner_id'])
                for key,view in [('proposer_action','proposer_committed_action_ids'),
                                 ('partner_action','responder_committed_action_ids')]:
                    ids={int(x.removeprefix('action_')) for x in shown[view]}
                    self.assertEqual([int(i in ids) for i in range(len(native[key]))],native[key])
            else:self.assertEqual(shown,native)
        for point in points:
            ctx=point['row']['input'];original=deepcopy(ctx)
            for stage in ('B','P'):
                v=model_payload(stage,ctx)
                self.assertEqual(len(v['legal_actions']),len(ctx['legal_actions']))
                self.assertEqual(len({json.dumps(a,sort_keys=True) for a in v['legal_actions']}),len(v['legal_actions']))
                for shown,native in zip(v['legal_actions'],ctx['legal_actions']):
                    check_action(shown,native)
                    if stage=='P':
                        parsed=call_model(FakeClient([],action=shown),'P',ctx,1024)
                        self.assertEqual(parsed['status'],'ok')
                        self.assertEqual(parsed['answer'],native)
                        self.assertEqual(parsed['submitted_action'],shown)
                self.assertEqual(len(v['history']),len(ctx['history']))
                for event,raw in zip(v['history'],ctx['history']):check_action(event['action'],raw)
                if ctx['pending_offer']:check_action(v['pending_offer'],ctx['pending_offer'])
                for p,row in enumerate(ctx['public_state']['commitments']):
                    ids={int(x.removeprefix('action_')) for x in v['public_state']['committed_action_ids'][str(p)]}
                    self.assertEqual([int(i in ids) for i in range(len(row))],row)
                for goal in v['game']['goals']:
                    self.assertNotIn('your_preference',goal)
                    self.assertEqual(v['own_preferences']['player'],ctx['player'])
                    self.assertEqual(v['own_preferences']['preferences_by_goal'][f"goal_{goal['goal_id']}"],labels[ctx['own_preferences'][goal['goal_id']]])
                for field in ('runtime_protocol','B_task_version','partner_model','own_goal_preferences'):
                    self.assertNotIn(field,v)
                self.assertEqual(list(v)[:3],['player','task','decision'])
            self.assertEqual(ctx,original)
        self.assertNotIn('maximize',system_for('B'))
        self.assertIn('maximize',system_for('P'))

    def test_truncated_and_legacy_index_rejected(self):
        env=self.env();ctx=env.context()
        self.assertEqual(call_model(FakeClient([],truncated=True),'P',ctx,50)['status'],'truncated')
        self.assertEqual(call_model(FakeClient([],action={'action_index':0}),'P',ctx,50)['status'],'illegal_action')

    def test_native_offer_is_executed_and_malformed_commitments_are_rejected(self):
        from training.b_sft.social_cases_expand import probe_action
        env=self.env();action=probe_action()
        from training.b_sft.social_presentation import readable_action
        shown=readable_action(action,env.context()['public_state']['current_proposer'])
        result=call_model(FakeClient([],action=shown),'P',env.context(),100)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['answer'],action)
        for bad in [action,dict(shown,partner_id=True),dict(shown,proposer_committed_action_ids=[1]),
                    dict(shown,proposer_committed_action_ids=['action_99']),
                    dict(shown,unexpected=1),{'action':shown},dict(shown,partner_id=99)]:
            self.assertEqual(call_model(FakeClient([],action=bad),'P',env.context(),100)['status'],'illegal_action')
        env.step(result['answer'],kind='learner')
        self.assertIsNotNone(env.node.pending)

    def test_reviewed_instructions_reach_model_without_chinese_or_old_constraints(self):
        client=FakeClient([]);inspect_decision(self.env(),client)
        for messages,tools,_ in client.seen:
            text=json.dumps([messages,tools],ensure_ascii=False)
            self.assertNotRegex(text,'[\u4e00-\u9fff]')
            for removed in ('ALL_OF','zero-based','action_index','Do not output counts or probabilities',
                            'No fixed reasoning template','A tool call alone is incomplete',
                            'not extra observations','do not copy tool JSON'):
                self.assertNotIn(removed,text)

    def test_no_selected_target_is_not_success(self):
        env=self.env();r=inspect_decision(env,FakeClient([]))
        result=aggregate([r]);self.assertEqual(result['B_empty_selection'],1)
        self.assertEqual(result['B_target_coverage'],0);self.assertIsNone(result['B_selected_exact_rate'])
        pair=temporal_pair(r,r)
        self.assertTrue(all(not x['both_exact'] and not x['both_selected'] for x in pair['targets']))

    def test_duplicate_correct_targets_cannot_inflate_exact(self):
        env=self.env();b=env.belief_table()[0];answer=dict(player=b['player'],goal=b['goal'],**b['answer'])
        metrics=b_metrics(env,[answer,answer]);self.assertFalse(metrics['score']['format_valid'])
        self.assertTrue(all(not d['exact'] for d in metrics['target_details']))

    def test_extra_public_target_does_not_erase_correct_hidden_judgments(self):
        env=self.env()
        answer=[dict(player=b['player'],goal=b['goal'],**b['answer']) for b in env.belief_table()]
        answer.append(dict(player=0,goal=0,possible_preferences=['want'],favored='want'))
        metrics=b_metrics(env,answer)
        self.assertFalse(metrics['score']['format_valid'])
        self.assertEqual(metrics['score']['protocol_score'],-1)
        self.assertTrue(all(d['exact'] for d in metrics['target_details']))
        self.assertEqual(metrics['score']['score'],0)

    def test_masked_teacher_does_not_count_as_wrong_complete_b(self):
        env=self.env()
        answer=[dict(player=b['player'],goal=b['goal'],**b['answer']) for b in env.belief_table()]
        correct=inspect_decision(env,FakeClient(answer))
        env.fragile=True
        masked=inspect_decision(env,FakeClient(answer))
        self.assertEqual(aggregate([correct,masked])['B_complete_exact_rate'],1)

    def test_partial_tool_markup_is_not_counted_as_reasoning(self):
        class PartialClient:
            def complete_with_tools(self,*args,**kwargs):
                return VLLMChatCompletion('<tool_call>{',(),dict(content='<tool_call>{'),{},'length')
        r=call_model(PartialClient(),'B',self.env().context(),10)
        self.assertEqual(r['status'],'truncated')
        self.assertEqual(r['reasoning_chars'],0)
        self.assertEqual(r['raw_text'],'<tool_call>{')

    def test_missing_explanation_is_reported_without_replacing_model_answer(self):
        env=self.env();before=deepcopy(env.context())
        answer=[dict(player=b['player'],goal=b['goal'],**b['answer']) for b in env.belief_table()]
        client=FakeClient(answer,text='  \n ')
        record=inspect_decision(env,client)
        result=aggregate([record])
        self.assertEqual(result['B_reasoning_present_rate'],0)
        self.assertEqual(result['P_explanation_statuses'],{'missing':1})
        self.assertEqual(result['B_complete_exact_rate'],1)
        self.assertTrue(record['P_metrics']['legal'])
        self.assertTrue(record['B_passthrough_exact'])
        self.assertEqual(len(client.seen),2)  # No retry or second generation phase.
        self.assertEqual(env.context(),before)  # Frozen dataset facts remain unchanged.

    def test_explanation_before_truncated_markup_is_retained_separately(self):
        text='Rejecting leaves the commitments unchanged.\n<tool_call>{'
        result=call_model(FakeClient([],text=text,truncated=True),'P',self.env().context(),30)
        self.assertEqual(result['reasoning_text'],'Rejecting leaves the commitments unchanged.')
        self.assertEqual(result['explanation_status'],'present')
        self.assertEqual(result['status'],'truncated')
        self.assertEqual(result['raw_text'],text)

    def test_request_failure_has_unavailable_explanation_and_can_be_summarized(self):
        class BrokenClient:
            def complete_with_tools(self,*args,**kwargs):raise RuntimeError('server unavailable')
        result=aggregate([inspect_decision(self.env(),BrokenClient())])
        self.assertEqual(result['B_explanation_statuses'],{'unavailable':1})
        self.assertEqual(result['P_explanation_statuses'],{'unavailable':1})

    def test_queries_persist_after_partner_reveals_singleton(self):
        from training.b_sft.social_cases_expand import probe_action
        env=self.env();queries=env.context()['queries']
        env.step(probe_action(),kind='learner')
        world=env.game.worlds[-1]
        env.step(env.reference_action(world[env.actor]),kind='partner')
        self.assertTrue(all(len(b['answer']['possible_preferences'])==1 for b in env.belief_table()))
        # context requires ego turn; fixed_context itself has no posterior access.
        from training.b_sft.social_task import fixed_context
        ctx=dict(player=env.raw['ego'],public_type_catalogues=env.raw['type_catalogues'])
        self.assertEqual(fixed_context(ctx)['queries'],queries)

    def test_teacher_budget_missing_and_action_legal_are_separate(self):
        env=self.env();r=inspect_decision(env,DryClient(),p_rollouts=1)
        self.assertTrue(r['P_metrics']['legal']);self.assertFalse(r['P_metrics']['reference']['mask'])
        self.assertIsNone(r['P_metrics']['reference_regret'])
        self.assertIsNone(r['supervision']['P'][0]['task_score'])
        self.assertFalse(r['supervision']['P'][0]['task_mask'])
        self.assertIsNone(r['supervision']['P'][0]['reward'])
        self.assertFalse(r['supervision']['P'][0]['reward_mask'])
        result=aggregate([r]);self.assertEqual(result['P_reference_available'],0)
        self.assertIsNone(result['P_optimal_rate_all_reference_available'])

    def test_scripted_continuation_records_actual_native_events_and_pairs(self):
        env=self.env();c=DryClient();r=inspect_decision(env,c);events=[];calls=[]
        e=continue_episode(env,env.worlds[0],c,r,lambda _:None,on_event=events.append,on_call=calls.append)
        self.assertTrue(e['terminal']);self.assertEqual(e['utilities'],env.outcome(env.worlds[0]))
        self.assertEqual(len(events),len(env.history)-len(env.prefix))
        self.assertTrue(all(x['event']['worlds_before']==x['event']['worlds_after'] for x in events if x['event']['kind']=='learner'))


if __name__=='__main__':unittest.main()
