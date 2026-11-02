"""Opt-in CalBench adapter for the generic MS scaffold; no upstream edits."""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

from examples.final_evaluation.interaction_scaffold import VERSION, ms_request, action_request

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / 'examples/strategic_slices/versions/general_ms_calbench_v1_20261102/SNAPSHOT.json'


class ScaffoldFailure(BaseException):
    """A failed analysis must not be swallowed by the native empty-action fallback."""


def sha(value):
    return hashlib.sha256(value).hexdigest()


def protocol(config):
    total = config.get('max_tokens')
    ms = config.get('ms_max_tokens', 512)
    if type(total) is not int or type(ms) is not int or not 0 < ms < total:
        raise ValueError('Require integer budgets: 0 < ms_max_tokens < max_tokens')
    return dict(version=VERSION, mode='base-ms', ms_max_tokens=ms,
        action_max_tokens=total-ms, total_output_cap_per_native_call=total,
        calls_per_native_request=2, budget_scope='output-token cap, not matched FLOPs or input tokens',
        ms_memory='no independent MS history; native final assistant responses remain in native history',
        analysis_failure='abort game/run on empty, truncated, unfinished or non-stop MS; no fallback',
        action_failure='retain native parsing/retry policy; do not erase failed attempts',
        seed_policy='action uses original native seed sequence; MS uses SHA256(native seed:ms)',
        privacy='only native visible messages; MS is private and never executed',
        environment_reflection=False, training=False)


def verify_registration():
    registered = json.loads(REGISTRATION.read_text())
    for name, expected in registered['source_sha256'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f'Scaffold source differs from registered v1: {name}; register a new version')
    return registered


class MSTransport:
    """Wrap the native transport twice. Only the final action returns to LLMClient."""
    def __init__(self, route, config, output, seed, agent_id, transport_class=None):
        if transport_class is None:
            from examples.final_evaluation.calbench_local import Transport
            transport_class = Transport
        self.contract = protocol(config)
        self.output, self.agent_id, self.index = Path(output), agent_id, 0
        ms_folder = self.output / 'ms'
        ms_folder.mkdir(exist_ok=True)
        ms_config, act_config = deepcopy(config), deepcopy(config)
        ms_config['max_tokens'] = self.contract['ms_max_tokens']
        act_config['max_tokens'] = self.contract['action_max_tokens']
        ms_seed = int(sha(f'{seed}:ms'.encode())[:8], 16)
        self.ms = transport_class(route, ms_config, ms_folder, ms_seed, agent_id)
        self.action = transport_class(route, act_config, self.output, seed, agent_id)

    def streaming_with_retry(self, messages, **kwargs):
        if kwargs:
            raise ValueError('MS v1 does not accept per-call overrides; configure the registered stage budgets')
        index = self.index
        self.index += 1
        receipt = dict(agent_id=self.agent_id, native_call_index=index, version=VERSION,
                       status='started', native_messages_sha256=sha(json.dumps(messages, sort_keys=True).encode()))
        started = time.monotonic()
        try:
            analysis = self.ms.streaming_with_retry(ms_request(messages))
            text = analysis.get('text')
            if (analysis.get('finish_reason') != 'stop' or not isinstance(text, str) or not text.strip()):
                receipt['status'] = 'analysis_failure'
                raise ScaffoldFailure(f'Agent {self.agent_id}: MS {index} was empty or did not finish normally')
            receipt['ms_text_sha256'] = sha(text.encode())
            result = self.action.streaming_with_retry(action_request(messages, text))
            # Native trace accounting must include both requests, with missing usage left unknown.
            result = dict(result)
            receipt['stage_usage'] = {}
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                values = [analysis.get(key), result.get(key)]
                receipt['stage_usage'][key] = dict(ms=values[0], action=values[1])
                result[key] = sum(values) if all(isinstance(v, int) for v in values) else None
            result['duration_s'] = time.monotonic() - started
            receipt['status'] = 'ok'
            return result
        except BaseException:
            if receipt['status'] == 'started':
                receipt['status'] = 'request_failure'
            raise
        finally:
            receipt['elapsed_seconds'] = time.monotonic() - started
            with (self.output / f'scaffold-agent-{self.agent_id}.jsonl').open('a') as f:
                f.write(json.dumps(receipt, ensure_ascii=False) + '\n')


def write_snapshot(output, config, *, cli=None, game_config=None, job=None):
    """Record actual identity; an API alias does not establish checkpoint identity."""
    registered = verify_registration()
    files = ['examples/final_evaluation/calbench_stream_v1/manifest.json',
             'examples/final_evaluation/calbench_stream_v1/MANIFEST.sha256',
             'examples/final_evaluation/calbench_source.json']
    dependencies = {}
    for package in ('pydantic', 'json-repair', 'ortools', 'opentelemetry-api', 'opentelemetry-sdk',
                    'opentelemetry-semantic-conventions', 'pytest', 'vllm', 'torch', 'transformers'):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = '未记录（当前进程环境未安装）'
    output = Path(output)
    launcher_root = next((p for p in (output.parent, output.parent.parent)
                          if (p/'execution_identity.json').is_file()), output.parent)
    launcher = launcher_root / 'execution_identity.json'
    runtime = launcher_root / 'runtime_environment.json'
    servers = launcher_root / 'servers.json'
    snapshot = dict(schema=1, version=VERSION, scope='CalBench opt-in evaluation; production active unchanged',
        cli=cli if cli is not None else '未记录（per-game snapshot; see run root）',
        resolved_routes=deepcopy(config), game_config=game_config, job=job,
        contract=protocol(config), source_sha256=registered['source_sha256'],
        resolved_transport=dict(temperature=config.get('temperature', 0.0),
            timeout_seconds=config.get('timeout_seconds',120),
            chat_template_kwargs=config.get('chat_template_kwargs','native model template; no override'),
            context_policy='no adapter truncation; server rejects oversized requests',
            context_capacity='see server_commands; external API capacity otherwise 未记录'),
        input_sha256={name:sha((ROOT/name).read_bytes()) for name in files},
        registered_snapshot_sha256=sha(REGISTRATION.read_bytes()),
        model_identity=json.loads(launcher.read_text()) if launcher.is_file() else '未记录（API model alias is not a weight hash）',
        runtime=dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                     dependencies=dependencies, sys_path=sys.path,
                     launcher_environment=json.loads(runtime.read_text()) if runtime.is_file() else '未记录',
                     server_commands=json.loads(servers.read_text()) if servers.is_file() else '未记录'),
        evaluation='original native rules, all four seats, original final-state scoring; hindsight reference only',
        reward_advantage_training='not applicable; no parameter updates',
        resume='existing outputs cannot be overwritten; reruns use new output directories')
    (output / 'pipeline_snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+'\n')
    return snapshot
