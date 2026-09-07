import json
from unittest.mock import patch

import pytest

from benac_p.diagnose_protocol import generate, protocol_summary, finalize, system_prompt
from benac_p.diagnose_suite import digest
from benac_p.finalization_calibration import main
from benac_p.semantic_suite import SYSTEM
from methods.vllm_client import VLLMChatCompletion, VLLMToolCall, OpenAICompatibleNegotiationClient


TASK = {'id': 'test', 'kind': 'planning', 'input': {'legal_actions': [{}, {}]}}


def response(finish='tool_calls', tokens=20):
    return VLLMChatCompletion('I choose action 1.', (VLLMToolCall('SUBMIT_ACTION', {'action_index': 1}),),
                             {}, {'completion_tokens': tokens, 'prompt_tokens': 100, 'total_tokens': 100+tokens}, finish)


class Client:
    def __init__(self, final='tool_calls'):
        self.calls = []
        self.final = final

    def complete_with_tools(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if len(self.calls) == 1:
            return response('length', 1024)
        assert kwargs['max_tokens'] == 128
        assert kwargs['tool_choice'] == {'type': 'function', 'function': {'name': 'SUBMIT_ACTION'}}
        assert messages[-2] == {'role': 'assistant', 'content': 'I choose action 1.'}
        assert not any('tool_calls' in m for m in messages)
        if self.final == 'error':
            raise RuntimeError('remote service failed')
        return response(self.final)


@pytest.mark.parametrize('finish,status', [('tool_calls', 'ok'), ('length', 'truncated'), ('error', 'finalization_error')])
def test_one_attempt_keeps_first_pass_and_total_cost(finish, status):
    client = Client(finish)
    r = generate(client, TASK, {'question': 'choose'}, SYSTEM, reasoning_profile='balanced', finalization_tokens=128)
    assert len(client.calls) == 2 and r['status'] == status
    assert r['attempts'][0]['status'] == 'truncated'
    assert r['first_finish_reason'] == 'length'
    assert r['usage']['completion_tokens'] == (1024 if finish == 'error' else 1044)
    if finish != 'tool_calls':
        assert 'answer' not in r
    summary = protocol_summary({'t': r, 'blocked': {'status': 'blocked_parent'}})
    assert summary['total_request_attempts'] == 2
    assert summary['first_pass_truncated_tasks'] == 1
    assert summary['finalization_attempted_tasks'] == 1
    assert summary['finalization_protocol_successes'] == int(finish == 'tool_calls')
    assert summary['reasoning_requests'] == 1
    assert summary['truncated_requests'] == (2 if finish == 'length' else 1)
    with pytest.raises(ValueError):
        finalize(client, TASK, {}, SYSTEM, r)


def test_valid_answer_never_retried():
    class Valid:
        def complete_with_tools(self, *args, **kwargs):
            assert kwargs['tool_choice'] == 'auto'
            return response()
    assert 'attempts' not in generate(Valid(), TASK, {}, SYSTEM, finalization_tokens=128)


def test_per_request_budget_does_not_mutate_client():
    class HTTPResponse:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def read(self):return json.dumps({'choices': [{'message': {'content': '', 'tool_calls': []}, 'finish_reason': 'stop'}]}).encode()
    budgets = []
    def urlopen(request, **kwargs):
        budgets.append(json.loads(request.data)['max_tokens'])
        return HTTPResponse()
    client = OpenAICompatibleNegotiationClient('http://unused.invalid', 'mock', max_tokens=1024)
    with patch('urllib.request.urlopen', urlopen):
        client.complete_with_tools([], tools=[{}], max_tokens=128)
        client.complete_with_tools([], tools=[{}])
    assert budgets == [128, 1024] and client.max_tokens == 1024


def test_replay_only_truncations_and_resume_without_new_calls(tmp_path):
    source = tmp_path/'source'; source.mkdir(); out = tmp_path/'out'
    client = Client()
    first = generate(client, TASK, {}, SYSTEM, reasoning_profile='balanced')
    valid = dict(first, status='ok', finish_reason='tool_calls', answer={'action_index': 1})
    rows = [{'id': key, 'task': TASK, 'payload': {'question': key}} for key in ('valid', 'truncated')]
    data = {'manifest.json': {'model': 'mock', 'max_tokens': 1024, 'source_manifest': {'temperature': 0},
                             'system_hashes': {'balanced': digest(system_prompt(SYSTEM, 'reasoning_tools', 'balanced'))}},
            'tasks.json': rows, 'answers.json': {'balanced/valid': valid, 'balanced/truncated': first},
            'oracle_labels.json': {key: {'q': [0, 1]} for key in ('valid', 'truncated')}}
    for name, value in data.items():(source/name).write_text(json.dumps(value))
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    argv = ['--source-run', str(source), '--output-dir', str(out), '--model', 'mock']
    main(argv+['--export-only'])
    assert len(json.loads((out/'pending_tasks.json').read_text())) == 1
    # Replay client begins directly with finalization; previous call was archived.
    with patch('methods.vllm_client.OpenAICompatibleNegotiationClient', return_value=client):
        main(argv+['--resume'])
        main(argv+['--resume'])
    assert len(client.calls) == 2
    result = json.loads((out/'answers.json').read_text())
    assert result['valid'] == valid and result['truncated']['status'] == 'ok'
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(SystemExit):main(argv+['--resume', '--finalization-tokens', '256'])
