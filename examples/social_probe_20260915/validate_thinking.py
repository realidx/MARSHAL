"""Check installed reasoning/tool parsers on synthetic strings, without loading weights."""
import inspect
import json
from pathlib import Path
import sys


def check_parsers(reasoning, tools, request):
    final_call = '<tool_call>\n{"name":"PASS","arguments":{}}\n</tool_call>'
    cases = [
        ('complete', '<think>Consider '+final_call+' but first compare utility.</think>Final decision. '+final_call, True),
        ('truncated_thinking', '<think>Consider '+final_call+' and continue reasoning', False),
        ('no_action', '<think>Compare utility.</think>No final action.', False),
    ]
    results = []
    for name, text, expected_call in cases:
        thinking, content = reasoning.extract_reasoning_content(text, request=request)
        parsed = tools.extract_tool_calls(content or '', request=request)
        assert thinking and parsed.tools_called == expected_call, name
        if expected_call:
            assert len(parsed.tool_calls) == 1
            call = parsed.tool_calls[0].function
            assert call.name == 'PASS' and json.loads(call.arguments) == {}
            assert 'Consider' not in (parsed.content or '')
        else:
            assert not parsed.tool_calls
        results.append(dict(case=name, reasoning_saved=True, final_tool_calls=len(parsed.tool_calls)))
    return results


def main():
    from transformers import AutoTokenizer
    from vllm.reasoning import ReasoningParserManager
    from vllm.entrypoints.openai.tool_parsers import ToolParserManager
    from vllm.entrypoints.openai.protocol import ChatCompletionRequest
    from vllm.entrypoints.openai.serving_chat import OpenAIServingChat
    tokenizer = AutoTokenizer.from_pretrained(sys.argv[1], local_files_only=True)
    request = ChatCompletionRequest(model='social-base', messages=[dict(role='user', content='Parser fixture')],
        tools=[dict(type='function', function=dict(name='PASS', parameters=dict(type='object', properties={})))],
        tool_choice='auto', max_tokens=1024, stream=False)
    reasoning = ReasoningParserManager.get_reasoning_parser('deepseek_r1')(tokenizer)
    tools = ToolParserManager.get_tool_parser('hermes')(tokenizer)
    # Our requests are nonstreaming. Confirm installed serving code composes both parsers.
    source = inspect.getsource(OpenAIServingChat.chat_completion_full_generator)
    assert 0 <= source.find('extract_reasoning_content(') < source.find('extract_tool_calls('), 'Installed server does not parse reasoning before tools'
    assert 'content if content is not None else ""' in source, 'Inspect installed tool-parser input before proceeding'
    result = dict(weights_loaded=False, network_calls=0, parser='deepseek_r1', tool_parser='hermes',
                  cases=check_parsers(reasoning, tools, request))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2)+'\n')
    print('Thinking/tool parser checks passed; no model calls.', flush=True)


if __name__ == '__main__':
    main()
