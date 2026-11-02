"""Export real native request-builder outputs with explicitly synthetic responses.

No HTTP requests or model sampling. The native client and production MS wrapper
run unchanged; only the HTTP provider is replaced with a deterministic fixture.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

from examples.final_evaluation.calbench_local import verify_source
from examples.final_evaluation.calbench_scaffold import BeliefTransport, InlineTransport, write_snapshot
from examples.final_evaluation.interaction_scaffold import VERSION, MS_INSTRUCTION
from examples.final_evaluation.calbench_stage_context import stage_context


def export(output, mode='belief-ms'):
    verify_source()
    from calendar_game.agents import GameConfig
    from calendar_game.calendar import Calendar
    from calendar_game.clients.llm import LLMClient
    from examples.final_evaluation.calbench_stream import load_frozen
    manifest, cases = load_frozen()
    case = next(c for c in cases if c['id'] == 'loose_uniform_s1')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = dict(scaffold=mode, max_tokens=4096, temperature=0.,
                  local_only=True, endpoints={a:dict(base_url='http://127.0.0.1:1/v1', model='OFFLINE_FIXTURE_NOT_A_MODEL')
                                              for a in ('focal', 'q0')})
    route = config['endpoints']['q0']
    payloads, native_contexts = [], []
    state = {}

    class Capture(BeliefTransport if mode=='belief-ms' else InlineTransport):
        def streaming_with_retry(self, messages, **kwargs):
            native_contexts.append(deepcopy(messages))
            return super().streaming_with_retry(messages, **kwargs)

    class Response:
        def __init__(self, value): self.value = value
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(self.value).encode()

    def provider(request, **kwargs):
        body = json.loads(request.data)
        payloads.append(body)
        is_ms = body['messages'][-1]['content'].endswith(MS_INSTRUCTION)
        content = state['ms'] if is_ms else json.dumps(state['action'])
        return Response(dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                             usage=dict(prompt_tokens=0, completion_tokens=3, total_tokens=3)))

    client = LLMClient(Capture(route, config, output, case['scenario_seed'], 0))
    client.register(0, GameConfig(num_agents=4, num_slots=8, agent_id=0,
                                 all_agent_ids=[0,1,2,3], decision_retries=1, communication_protocol='dm'))
    calendar = Calendar(8)
    calendar.slots = deepcopy(case['scenario']['calendars'][0])
    client.start_round(case['scenario']['meetings'][0], calendar.render(), 0)
    examples = []

    def invoke(label, analysis, action, callback, note):
        state.update(ms=analysis, action=deepcopy(action))
        if mode=='inline-ms':
            state['action']['thinking'] = analysis+' '+action['thinking']
            action = state['action']
        start = len(payloads)
        with patch('examples.final_evaluation.calbench_local.urlopen', side_effect=provider):
            result = callback()
        examples.append(dict(label=label, provenance=note, native_messages=native_contexts[-1],
                             context_projection=stage_context(native_contexts[-1]).__dict__ if mode=='belief-ms' else None,
                             actual_ms_request=payloads[start] if mode=='belief-ms' else None,
                             actual_action_request=payloads[start+1] if mode=='belief-ms' else payloads[start],
                             synthetic_ms=analysis, synthetic_action=action,
                             native_history_after=deepcopy(client._history),
                             native_parsed_actions=result.tool_calls,
                             tools_registration='No HTTP tools field; native named schemas in original system' if mode=='inline-ms' else 'No HTTP tools field; native named action schemas restored only in final ACTION user'))

    invoke('cheap_talk_initial',
        'My own calendar has free slots 1, 2, 5, and 7. I have not received any statements about the other participants\' availability. Their acceptable slots are uncertain.',
        dict(thinking='Ask about a slot free for me.', actions=[dict(type='dm', to=1, content='Slot 1 works for me. Does it work for you?')]),
        lambda:client.turn([], 0, 4), 'Real frozen initial state; hand-authored response fixture, not model output')
    invoke('cheap_talk_update',
        'Agents 1 and 2 have each said slot 1 works. This supports a shared choice, though I cannot inspect their calendars. My own slot 1 is free.',
        dict(thinking='The messages support slot 1.', actions=[]),
        lambda:client.turn([dict(**{'from':1}, meeting_id=1, content='Slot 1 works for me.'),
                            dict(**{'from':2}, meeting_id=1, content='Slot 1 works for me.')], 1, 4),
        'Synthetic received messages over the real frozen state; no claim that a model produced them')
    invoke('decision', 'The received statements support slot 1 and it is free on my calendar. Other agents still submit independently.',
        dict(thinking='Use the discussed slot.', actions=[dict(type='schedule', meeting_id=1, slot=1)]),
        lambda:client.decide(case['scenario']['meetings'][0], calendar.render()),
        'Native decision builder with synthetic prior dialogue; no environment execution')
    invoke('retry', 'The validation feedback requires reconsidering my submitted action. The available evidence still supports slot 1.',
        dict(thinking='Submit the specified meeting and slot.', actions=[dict(type='schedule', meeting_id=1, slot=1)]),
        lambda:client.retry_decide(1,1,'Synthetic format-error feedback for request-export coverage.'),
        'Synthetic retry branch only; the preceding fixture did not actually fail')
    # Continue the same native history, now with an authored accepted commitment.
    # Only the current meeting and received request are supplied, never future ones.
    calendar.slots[1] = dict(meeting_id=1, cost=1)
    calendar.meeting_participants[1] = [0,1,2]
    client.start_round(case['scenario']['meetings'][1], calendar.render(), 1)
    invoke('nonparticipant_communication', 'Agent 1 requests a change to our existing shared commitment. I need to consider my own constraints; their request does not reveal everyone else\'s agreement.',
        dict(thinking='Acknowledge the request without assuming others agreed.', actions=[]),
        lambda:client.turn([dict(**{'from':1}, meeting_id=2, content='Can we move meeting 1 from slot 1 to slot 2?')], 0, 4),
        'Authored continuation after meeting 1 at slot 1; received request is synthetic')
    invoke('voluntary', 'I received a request to move meeting 1. My slot 2 is free, but the messages do not establish that every participant agreed to the move.',
        dict(thinking='There is no confirmed shared replacement yet.', actions=[]),
        lambda:client.voluntary_decide(case['scenario']['meetings'][1], calendar.render()),
        'Native voluntary builder on authored continuation; no model or game outcome claim')

    # Independent first-turn branch: incoming messages already exist before this
    # player's first turn. Both that request and its later history must keep them.
    client = LLMClient(Capture(route, config, output, case['scenario_seed'], 0))
    client.register(0, GameConfig(num_agents=4, num_slots=8, agent_id=0,
                                 all_agent_ids=[0,1,2,3], decision_retries=1, communication_protocol='dm'))
    calendar.slots = deepcopy(case['scenario']['calendars'][0])
    client.start_round(case['scenario']['meetings'][0], calendar.render(), 0)
    invoke('first_turn_with_inbox',
        'Agent 1 says slot 5 works for them and asks whether it works for me. My slot 5 is free. I do not yet know whether the other participant agrees.',
        dict(thinking='Ask the remaining participant about the proposed slot.', actions=[dict(type='dm', to=2, content='Agent 1 proposed slot 5. Does it work for you?')]),
        lambda:client.turn([dict(**{'from':1}, meeting_id=1, content='Slot 5 works for me. Does it work for you?')], 0, 4),
        'Independent branch: real frozen initial calendar, synthetic incoming DM before the first turn; not a model result')
    invoke('history_after_first_inbox',
        'Agent 1 previously said slot 5 works. I have asked Agent 2 about it, but no reply has arrived, so their availability remains uncertain.',
        dict(thinking='There is no new information.', actions=[]),
        lambda:client.turn([], 1, 4),
        'Continuation of first_turn_with_inbox: the earlier received DM remains visible in the projected history')

    artifact = dict(status='OFFLINE_REQUEST_EXPORT_WITH_SYNTHETIC_RESPONSES', case_id=case['id'],
                    native_suite='calbench_stream_v1', case_sha256=manifest['files'][f"cases/{case['id']}.json"],
                    mode=mode, agent_id=0, actual_initial_calendar=calendar.slots, examples=examples)
    # Preserve the actual initial calendar rather than the authored continuation.
    artifact['actual_initial_calendar'] = case['scenario']['calendars'][0]
    (output/'requests.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    blocks = [f'# 完整请求预览：{VERSION} 独立belief/MS → action', '',
              '本文件由实际原生客户端和生产两阶段请求函数生成；仅HTTP响应替换成人工fixture，没有调用模型。', '',
              'MS的system及各user是原生可见上下文的观察/规则视图：行动输出要求和示例已移到最后ACTION user。',
              '历史assistant保留真实原生提交；当前MS是实际第一响应（此处为人工fixture），不会执行或作为pass。',
              'Action完整续接同一MS前缀，再追加assistant MS和user ACTION；最后user恢复原生工具/格式/当前阶段行动要求。',
              '跨行动保存仍是原生user与最终assistant action，临时MS不写进原生历史。', '',
              '完整wire requests、原生输入、投影视图/移位内容及历史：[requests.json](requests.json)。', '',
              '接受的MS+action共享4096。fixture MS用量3，所以action cap4093；重试是额外成本，全部保留。',
              '这份CPU导出只验证请求构造，不证明真实模型一定遵守阶段要求或协调成绩提升。', '']
    if mode=='inline-ms':
        blocks = [f'# 完整请求预览：{VERSION} inline-ms', '',
            '原生system、历史与当前user不改写；仅在最后user追加通用MS要求。一次生成，在原生thinking中分析、actions中提交动作。',
            '所有回复均为人工fixture；没有独立MS调用，未运行模型。完整wire请求与原生输入见[requests.json](requests.json)。', '']
    for example in examples:
        blocks.extend([f"## {example['label']}", '', example['provenance'], ''])
        for key, title in [('actual_ms_request','MS request'),('actual_action_request','Action request')]:
            request=example[key]
            if request is None: continue
            blocks.extend([f'### {title}', '', 'Request fields other than messages:', '', '```json',
                           json.dumps({k:v for k,v in request.items() if k!='messages'},ensure_ascii=False,indent=2), '```', ''])
            for i,message in enumerate(request['messages']):
                blocks.extend([f"#### message {i}: {message['role']}", '', '```text', message['content'], '```', ''])
        blocks.extend(['### Native history after final action (no stage-local messages)', '', '```json',
                       json.dumps(example['native_history_after'],ensure_ascii=False,indent=2), '```', ''])
    (output/'PROMPT_PREVIEW.md').write_text('\n'.join(blocks))
    snapshot = write_snapshot(output, config, cli=dict(argv=sys.argv, mode='offline HTTP fixture; no network/model'),
                              game_config=manifest['config'])
    snapshot.update(execution_kind='offline_request_export', model_sampling=False,
                    synthetic_responses=True, dependency_scope='CPU request construction, not model evaluation')
    (output/'pipeline_snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    return artifact


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode',choices=['belief-ms','inline-ms'],default='belief-ms')
    args=parser.parse_args()
    export(args.output,args.mode)
