"""Offline launcher guards; no GPU, network or model calls."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import shutil
import signal
import tempfile
import threading
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from training.b_sft import remote_bp_probe as sampler

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('probe_remote', HERE/'run_remote.py')
remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
spec_cpu = importlib.util.spec_from_file_location('probe_cpu', HERE/'diagnose_cpu.py')
cpu = importlib.util.module_from_spec(spec_cpu); spec_cpu.loader.exec_module(cpu)


class RemoteTests(unittest.TestCase):
    def test_thinking_probe_preserves_all_paired_inputs(self):
        bundle = HERE/'remote_bundle_qwen17_thinking'
        manifest, requests, resets = remote.verify(bundle)
        old = HERE/'remote_bundle_qwen17'
        self.assertEqual(len(requests), 52)
        self.assertEqual(len(resets), 12)
        for name in ('bp_requests.jsonl','bridges_requests.jsonl','l0_requests.jsonl',
                     'selfplay_resets.environment.jsonl','runtime_v4.tar.gz','probe_generation_config.json'):
            self.assertEqual((bundle/name).read_bytes(), (old/name).read_bytes())
        profile = manifest['model_profile']
        self.assertTrue(profile['enable_thinking'])
        original = (old/'qwen17_nonthinking.jinja').read_text().removeprefix('{%- set enable_thinking = false -%}')
        self.assertEqual((bundle/profile['template_filename']).read_text(), '{%- set enable_thinking = true -%}'+original)
        launch = (bundle/'launch_qwen17_thinking.sh').read_text()
        self.assertIn('--local-only', launch)
        self.assertIn('--sampling-seed 20260916', launch)

    def test_thinking_server_composes_reasoning_and_tools(self):
        bundle = HERE/'remote_bundle_qwen17_thinking'
        manifest, _, _ = remote.verify(bundle)
        original = (bundle/'qwen17_thinking.jinja').read_text().removeprefix('{%- set enable_thinking = true -%}')
        tokenizer = SimpleNamespace(chat_template=original)
        fixture = dict(manifest, model_profile=dict(manifest['model_profile'], model_files_sha256={}))
        with tempfile.TemporaryDirectory() as temp:
            options, _ = remote.configure_model(tokenizer, Path(temp), fixture, bundle, Path(temp))
            self.assertEqual(options[-3:], ['--enable-reasoning','--reasoning-parser','deepseek_r1'])
            self.assertEqual(Path(options[1]).read_text(), tokenizer.chat_template)
            self.assertNotIn('set enable_thinking = false', tokenizer.chat_template)

    def test_qwen17_reuses_exact_inputs_including_latest_l0(self):
        bundle = HERE/'remote_bundle_qwen17'
        manifest, requests, resets = remote.verify(bundle)
        self.assertEqual(len(requests), 52)
        self.assertEqual(len(resets), 12)
        for name in ('bp_requests.jsonl', 'bridges_requests.jsonl', 'selfplay_resets.environment.jsonl'):
            self.assertEqual((bundle/name).read_bytes(), (HERE/'selection_v1'/name).read_bytes())
        self.assertEqual((bundle/'l0_requests.jsonl').read_bytes(),
                         (HERE.parent/'social_bp/b_l0_isolated_v1/requests.jsonl').read_bytes())
        self.assertFalse(manifest['model_profile']['enable_thinking'])

    def test_qwen17_model_guard_and_shared_template(self):
        bundle = HERE/'remote_bundle_qwen17'
        manifest, _, _ = remote.verify(bundle)
        template = (bundle/'qwen17_nonthinking.jinja').read_text()
        original = template.removeprefix('{%- set enable_thinking = false -%}')
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), manifest['bp_template_sha256'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root/'model'; model.mkdir()
            (model/'config.json').write_text('wrong model')
            tokenizer = SimpleNamespace(chat_template=original)
            with self.assertRaisesRegex(ValueError, 'metadata/tokenizer differs'):
                remote.configure_model(tokenizer, model, manifest, bundle, root)
            fixture = dict(manifest, model_profile=dict(manifest['model_profile'],
                model_files_sha256={'config.json':hashlib.sha256(b'wrong model').hexdigest()}))
            options, _ = remote.configure_model(tokenizer, model, fixture, bundle, root)
            self.assertEqual(tokenizer.chat_template, template)
            self.assertEqual(Path(options[1]).read_text(), tokenizer.chat_template)
            config = json.loads((Path(options[3])/'generation_config.json').read_text())
            self.assertEqual((config['top_p'], config['top_k']), (.8, 20))

    def test_qwen17_all_stages_report_separate_groups(self):
        bundle = HERE/'remote_bundle_qwen17'
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            args = SimpleNamespace(output=Path(temp), stages=['bp','bridges','l0','selfplay'],
                                   workers_per_gpu=16, sampling_seed=20260916, capture_performance=False)
            client = Mock()
            client.run.side_effect = [dict(requests_sent=n, infrastructure_failures=0) for n in (224,144,48)]
            with patch.object(remote, 'run_selfplay', return_value=dict(games=48, statuses={'terminal':48})):
                self.assertEqual(remote.run_selected_stages(args, client, None, None,
                    remote.rows(bundle/'selfplay_resets.environment.jsonl'), ['a','b'], bundle), 0)
            result = json.loads((Path(temp)/'COMPLETE.json').read_text())
            self.assertEqual(result['bp_formal_responses'], 416)
            self.assertEqual(result['selfplay_attempts'], 48)
            self.assertEqual(result['formal_responses_by_stage'], dict(bp=224, bridges=144, l0=48))

    def test_l0_bundle_contains_only_six_formal_questions_and_rejects_other_stages(self):
        bundle = HERE/'remote_bundle_l0'
        manifest, requests, resets = remote.verify(bundle)
        self.assertEqual(manifest['conditions'], dict(bp=28, bridges=6, selfplay=12))
        formal = remote.rows(bundle/'bridges_requests.jsonl')
        self.assertEqual(len(formal), 6)
        self.assertEqual(sum(r['split'] == 'validation' for r in formal), 3)
        self.assertTrue(all('Correct PREVIOUS belief' in r['request']['messages'][1]['content'] for r in formal))
        args = SimpleNamespace(check=False, performance_only=False, stages=['selfplay'])
        with patch.object(remote, 'ENTRY', bundle), self.assertRaises(ValueError):
            remote.run(args)

    def test_l0_completion_reports_48_answers_without_selfplay(self):
        bundle = HERE/'remote_bundle_l0'
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            args = SimpleNamespace(output=Path(temp), stages=['bridges'], workers_per_gpu=16,
                                   sampling_seed=20260916, capture_performance=False)
            client = Mock()
            client.run.return_value = dict(requests_sent=48, infrastructure_failures=0)
            with patch.object(remote, 'run_selfplay') as games:
                self.assertEqual(remote.run_selected_stages(args, client, None, None, [], ['a','b'], bundle), 0)
                games.assert_not_called()
            result = json.loads((Path(temp)/'COMPLETE.json').read_text())
            self.assertEqual(result['formal_responses_by_stage'], {'bridges':48})
            self.assertEqual(result['selfplay_attempts'], 0)
            self.assertEqual(len(client.run.call_args.args[2]), 32)
            self.assertEqual(client.run.call_args.kwargs['group_size'], 8)

    def test_selected_inputs_and_hidden_reset_boundary(self):
        _, requests, resets = remote.verify(HERE/'remote_bundle')
        self.assertEqual(len(requests), 46)
        self.assertEqual(len(resets), 12)
        self.assertTrue(all('realized_world' not in r and 'teacher' not in r for r in requests))
        self.assertTrue(all('realized_world' in r for r in resets))

    def test_changed_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp)/'bundle'; shutil.copytree(HERE/'remote_bundle', copy)
            path = copy/'bp_requests.jsonl'
            path.write_text(path.read_text().replace('"split": "train"', '"split": "test"', 1))
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                remote.verify(copy)

    def test_exactly_two_explicit_gpus_required(self):
        with patch.object(remote, 'ENTRY', HERE/'remote_bundle'):
            for value in ('', '0', '0,0', '0, 0', '0,1,2'):
                with patch.dict(remote.os.environ, {'CUDA_VISIBLE_DEVICES': value}):
                    with self.assertRaisesRegex(ValueError, 'exactly the two GPUs'):
                        remote.run(SimpleNamespace(check=False))

    def test_cleanup_targets_only_owned_process_group_even_if_frontend_exited(self):
        server = Mock(pid=12345)
        server.poll.return_value = 1
        with patch.object(remote.os, 'killpg') as kill:
            remote.stop_server(server)
        kill.assert_called_once_with(12345, signal.SIGTERM)
        server.wait.assert_called_once_with(timeout=20)

    def test_token_count_counts_ids_not_encoding_fields(self):
        tokenizer = Mock()
        tokenizer.apply_chat_template.return_value = {'input_ids':[1,2,3,4], 'attention_mask':[1,1,1,1]}
        self.assertEqual(remote.token_count(tokenizer, [], []), 4)
        self.assertFalse(tokenizer.apply_chat_template.call_args.kwargs['truncation'])
        tokenizer.apply_chat_template.return_value = {'input_ids':[[1,2,3,4]]}
        with self.assertRaises(ValueError):
            remote.token_count(tokenizer, [], [])

    def test_performance_inputs_preserve_native_protocol_and_originals(self):
        _, requests, _ = remote.verify(HERE/'remote_bundle')
        original = json.dumps(requests, sort_keys=True)
        selected = remote.performance_requests(requests)
        self.assertEqual(len(selected), 16)
        self.assertEqual(sum(r['task']=='P' for r in selected), 4)
        self.assertEqual(selected, remote.performance_requests(requests))
        for r in selected:
            self.assertEqual(r['request']['max_tokens'], 1024)
            self.assertEqual(r['request']['tool_choice'], 'auto')
        self.assertEqual(json.dumps(requests, sort_keys=True), original)

    def test_performance_deadline_preserves_partial_results(self):
        _, requests, _ = remote.verify(HERE/'remote_bundle')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            def interrupted(command, timeout):
                self.assertEqual(timeout, 360)
                p = out/'performance_samples'; p.mkdir()
                (p/'samples.jsonl').write_text(json.dumps(dict(status='completed', seconds=1,
                    usage={'completion_tokens':20}, finish_reason='length'))+'\n{"partial":')
                raise remote.subprocess.TimeoutExpired(command, timeout)
            args = SimpleNamespace(output=out, workers_per_gpu=4, execution='graphs')
            with patch.object(remote.subprocess, 'run', side_effect=interrupted):
                self.assertEqual(remote.run_performance(args, out, requests, ['a','b']), 2)
            result = json.loads((out/'PERFORMANCE.json').read_text())
            self.assertTrue(result['timed_out'])
            self.assertFalse(result['complete'])
            self.assertEqual(result['saved'], 1)
            self.assertFalse((out/'COMPLETE.json').exists())

    def test_cpu_interval_excludes_reused_pids_and_counts_multiple_cores(self):
        before = dict(at=10, processes={'1':dict(start=1,ticks=100,name='worker',ppid=0,uid=1),
                                       '2':dict(start=2,ticks=100,name='old',ppid=0,uid=1)})
        after = dict(at=20, processes={'1':dict(start=1,ticks=2100,name='worker',ppid=0,uid=1),
                                      '2':dict(start=3,ticks=3000,name='new',ppid=0,uid=1)})
        result = cpu.compare(before, after, 100)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['cpu_percent'], 200)

    def test_proc_stat_name_with_spaces_and_parentheses(self):
        fields = ['S']+['0']*19
        fields[1], fields[11], fields[12], fields[19] = '9', '30', '4', '900'
        parsed = cpu.parse_stat('123 (ray worker (x)) '+' '.join(fields))
        self.assertEqual(parsed, dict(name='ray worker (x)', ppid=9, ticks=34, start=900))

    def test_formal_independent_seeds_and_32_calls_in_flight_with_only_18_tasks(self):
        barrier = threading.Barrier(32, timeout=5)
        lock = threading.Lock()
        payloads = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps(dict(choices=[dict(message=dict(content='unfinished'), finish_reason='length')],
                                       usage={'completion_tokens':1024})).encode()
        def response(request, timeout):
            payload = json.loads(request.data)
            with lock:
                payloads.append(payload)
                count = len(payloads)
            if count <= 32:
                barrier.wait()
            self.assertEqual(payload['max_tokens'], 1024)
            self.assertEqual(payload['tool_choice'], 'auto')
            return Response()
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            out = Path(temp)
            with patch.object(sampler, 'urlopen', side_effect=response):
                summary = sampler.run(HERE/'remote_bundle/bridges_requests.jsonl', out/'parallel',
                    ['http://localhost:18091/v1','http://localhost:18092/v1']*16,
                    'social-base', group_size=8, sample_seed_base=20260915)
            self.assertEqual(summary['completed'], 144)
            self.assertEqual(summary['infrastructure_failures'], 0)
            first = remote.rows(out/'parallel/samples.jsonl')
            self.assertEqual(len({r['seed'] for r in first}), 144)
            self.assertEqual(len({r['worker_id'] for r in first}), 32)
            for task_id in {r['task_id'] for r in first}:
                self.assertEqual(sorted(r['sample_index'] for r in first if r['task_id']==task_id), list(range(8)))
            with patch.object(sampler, 'urlopen', return_value=Response()):
                sampler.run(HERE/'remote_bundle/bridges_requests.jsonl', out/'serial',
                    ['http://localhost:18091/v1'], 'social-base', group_size=8, sample_seed_base=20260915)
            second = remote.rows(out/'serial/samples.jsonl')
            key = lambda rs: {(r['task_id'],r['sample_index']):r['seed'] for r in rs}
            self.assertEqual(key(first), key(second))

    def test_bridges_selfplay_stages_skip_old_bp_and_report_actual_counts(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            args = SimpleNamespace(output=Path(temp), stages=['bridges','selfplay'], workers_per_gpu=16,
                                   sampling_seed=20260915, capture_performance=False)
            client = Mock()
            client.run.return_value = dict(requests_sent=144, infrastructure_failures=0)
            resets = remote.rows(HERE/'remote_bundle/selfplay_resets.environment.jsonl')
            with patch.object(remote, 'run_selfplay', return_value=dict(games=48,statuses={'terminal':48})):
                self.assertEqual(remote.run_selected_stages(args, client, None, None, resets,
                    ['a','b'], HERE/'remote_bundle'), 0)
            client.run.assert_called_once()
            self.assertEqual(client.run.call_args.args[0].name, 'bridges_requests.jsonl')
            self.assertEqual(len(client.run.call_args.args[2]), 32)
            self.assertEqual(client.run.call_args.kwargs['sample_seed_base'], 20260915)
            done = json.loads((args.output/'COMPLETE.json').read_text())
            self.assertEqual(done['formal_responses_by_stage'], {'bridges':144})
            self.assertEqual(done['selfplay_attempts'], 48)

    def test_formal_transport_failure_does_not_mark_complete_or_start_next_stage(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            args = SimpleNamespace(output=Path(temp), stages=['bridges','selfplay'], workers_per_gpu=16,
                                   sampling_seed=20260915, capture_performance=False)
            client = Mock()
            client.run.return_value = dict(requests_sent=144, infrastructure_failures=1)
            with patch.object(remote, 'run_selfplay') as selfplay:
                self.assertEqual(remote.run_selected_stages(args, client, None, None, [],
                    ['a','b'], HERE/'remote_bundle'), 2)
                selfplay.assert_not_called()
            self.assertFalse((args.output/'COMPLETE.json').exists())
            self.assertTrue((args.output/'INCOMPLETE.json').exists())


if __name__ == '__main__':
    unittest.main()
