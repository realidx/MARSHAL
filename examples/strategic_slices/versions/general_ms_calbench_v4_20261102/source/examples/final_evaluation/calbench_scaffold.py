"""Opt-in CalBench adapter for the generic MS scaffold; no upstream edits."""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from examples.final_evaluation.interaction_scaffold import VERSION, action_request

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / 'examples/strategic_slices/versions/general_ms_calbench_v4_20261102/SNAPSHOT.json'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def protocol(config):
    total = config.get('max_tokens')
    if 'ms_max_tokens' in config:
        raise ValueError('ms_max_tokens belongs to the historical two-stage design; remove it for ms-guided')
    if type(total) is not int or total <= 0:
        raise ValueError('Require a positive integer max_tokens action budget')
    return dict(version=VERSION, mode='ms-guided', calls_per_native_request=1,
        total_output_cap_per_native_call=total,
        budget_scope='one native generation cap; no stage split or subtraction',
        request_layout='native system and history unchanged; append concise MS-to-plan-to-action guidance to current final user',
        persistence='original native client stores original user and final assistant reply, including native thinking; no extra stage messages',
        response_format='unchanged native thinking/actions JSON; no MS/plan fields or separate prose response',
        action_failure='original native parsing, truncation accounting and retry; no MS-stage failures',
        usage_contract='original provider usage; missing usage remains null, no token estimation or MS accounting gate',
        seed_policy='unchanged native seed sequence; no MS seed or extra call',
        privacy='only native visible messages; no extra environment facts or teacher judgments',
        environment_reflection=False, training=False)


def verify_registration():
    registered = json.loads(REGISTRATION.read_text())
    for name, expected in registered['source_sha256'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f'Scaffold source differs from registered {VERSION}: {name}; register a new version')
    return registered


class MSGuidedTransport:
    """One native provider call; return its result unchanged to the native client."""
    def __init__(self, route, config, output, seed, agent_id, transport_class=None):
        if transport_class is None:
            from examples.final_evaluation.calbench_local import Transport
            transport_class = Transport
        self.contract = protocol(config)
        self.action = transport_class(route, deepcopy(config), output, seed, agent_id)

    def streaming_with_retry(self, messages, **kwargs):
        return self.action.streaming_with_retry(action_request(messages), **kwargs)


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
