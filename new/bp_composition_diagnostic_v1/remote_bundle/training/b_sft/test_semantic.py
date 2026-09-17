import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from training.b_sft.generation import evaluation_interval, prepare_prompts, rank_indices, select_train_probe
from training.b_sft.semantic import Selection, gold_answer, parse_response, read_pairs, score_records, write_report
from training.b_sft.semantic_callback import make_semantic_callback
from training.b_sft.train import parse_args


def example(identifier, source='s', values=('want', 'neutral'), history=()):
    return dict(id=identifier, source_id=source, tools=[{'type': 'function'}], messages=[
        dict(role='system', content='rules'),
        dict(role='user', content=json.dumps(dict(query={'player_id': 3, 'goal_id': 11}, history=list(history)))),
        dict(role='assistant', content='', tool_calls=[dict(function=dict(name='SUBMIT_JUDGMENT',
             arguments=json.dumps(dict(possible_preferences=list(values)))) )])])


def prediction(row, values=None, status='ok'):
    return dict(id=row['id'], status=status,
                answer=gold_answer(row) if values is None else dict(possible_preferences=values))


def response(values=('want', 'neutral')):
    return '<tool_call>' + json.dumps(dict(name='SUBMIT_JUDGMENT', arguments=dict(possible_preferences=list(values)))) + '</tool_call><|im_end|>'


def test_first_answer_parser_and_preface():
    assert parse_response(response())['status'] == 'ok'
    assert parse_response('Evidence is inconclusive.\n' + response())['preface'] == 'Evidence is inconclusive.'
    for text in [response([]), response(['want', 'want']), response(['likely_want']), response() + response(),
                 '{"possible_preferences":["want"]}', response() + 'trailing text',
                 '<tool_call>[]</tool_call>', response().replace('SUBMIT_JUDGMENT', 'OTHER')]:
        assert parse_response(text)['status'] == 'protocol_failure'
    assert parse_response(response(), truncated=True)['status'] == 'truncated'


def test_pair_failures_and_source_macro_are_not_hidden():
    event = {'player_id': 3, 'action': {'response': 'CHOOSE_2'}}
    rows = [example('before'), example('after', history=[event]), example('third', source='t', values=['want'])]
    pairs = [dict(before='before', after='after', source_id='s'), dict(before='absent', after='after', source_id='s')]
    preds = [prediction(rows[0]), prediction(rows[1], status='protocol_failure')]
    metrics, questions, pair_rows = score_records(rows, preds, pairs)
    assert metrics['overall']['exact_rate_all'] == pytest.approx(1/3)
    assert metrics['source_macro_exact'] == .25
    assert metrics['pairs']['maintain']['both_exact_rate_all'] == 0
    assert metrics['pairs']['maintain']['both_exact_rate_valid'] is None
    assert metrics['unavailable_pairs'] == 1
    assert questions[1]['false_exclusions'] is None
    assert questions[2]['status'] == 'missing'
    assert pair_rows[0]['new_event'] == event


def test_update_pair_and_wrong_to_right_report(tmp_path):
    event = {'player_id': 3, 'action': {'response': 'REJECT'}}
    rows = [example('b'), example('a', values=['want'], history=[event])]
    pairs = [dict(before='b', after='a', source_id='s')]
    preds = [prediction(r) for r in rows]
    baseline = [prediction(rows[0], ['want']), prediction(rows[1], ['want', 'neutral'])]
    metrics = write_report(tmp_path, rows, preds, pairs, baseline)
    assert metrics['pairs']['update']['both_exact_rate_all'] == 1
    questions = [json.loads(x) for x in (tmp_path/'questions.jsonl').read_text().splitlines()]
    assert all(q['comparison'] == 'wrong->correct' for q in questions)
    assert 'REJECT' in (tmp_path/'pairs.csv').read_text()
    with pytest.raises(ValueError, match='exactly one'):
        score_records([rows[0], example('a')], preds, pairs)
    with pytest.raises(ValueError, match='Duplicate'):
        score_records(rows, preds + preds)


def test_selection_ties_baseline_and_resume():
    selection = Selection()
    assert selection.observe(0, .5, 3) == (True, False)
    assert selection.observe(10, .5, 3) == (False, False)
    assert selection.best_step == 0
    assert selection.observe(20, .6, 3) == (True, False)
    selection = Selection(**selection.to_dict())
    assert selection.observe(30, .59, 3) == (False, False)
    assert selection.observe(40, .6, 3) == (False, False)
    assert selection.observe(50, .58, 3) == (False, True)
    assert selection.best_step == 20
    with pytest.raises(ValueError):
        selection.observe(60, float('nan'), 3)


def test_generation_schedule_and_prompt_has_no_gold():
    class Tokenizer:
        def apply_chat_template(self, messages, tools, **kwargs):
            assert [m['role'] for m in messages] == ['system', 'user']
            assert kwargs == dict(tokenize=False, add_generation_prompt=True)
            return 'prompt only'
        def __call__(self, text, **kwargs):
            return {'input_ids': [1, 2, 3]}
    prompts = prepare_prompts([example('a')], Tokenizer(), 131, 128)
    assert 'answer' not in prompts[0]
    with pytest.raises(ValueError, match='refusing truncation'):
        prepare_prompts([example('a')], Tokenizer(), 130, 128)
    for n in [1, 7, 8, 9, 113]:
        shards = [list(rank_indices(n, rank, 8)) for rank in range(8)]
        assert len({len(s) for s in shards}) == 1
        assert sorted(i for s in shards for i, keep in s if keep) == list(range(n))
    assert evaluation_interval(610, 8, 2, .25) == 10
    assert evaluation_interval(3000, 8, 2, .25) == 47


def test_fixed_probe_covers_sources_and_pair_dedup(tmp_path):
    rows = [example(str(i), source='s' if i < 5 else 't') for i in range(8)]
    assert {r['source_id'] for r in select_train_probe(rows, 2)} == {'s', 't'}
    assert select_train_probe(list(reversed(rows)), 3) == select_train_probe(rows, 3)
    p = dict(before='b', after='a', source_id='s')
    path = tmp_path/'pairs.jsonl'
    path.write_text((json.dumps(p)+'\n')*2)
    assert read_pairs(path) == [p]


def test_semantic_cli_rejects_bad_settings():
    base = ['--model', 'm', '--eval-file', 'e', '--train-file', 't', '--output-dir', 'o']
    for flags in [['--semantic-eval'], ['--mode', 'train', '--eval-every-fraction', '0'],
                  ['--mode', 'train', '--semantic-eval-steps', '0']]:
        with pytest.raises(SystemExit):
            parse_args(base + flags)


def test_callback_selection_save_and_restore(tmp_path, monkeypatch):
    import training.b_sft.semantic_callback as module
    monkeypatch.setattr(module, 'preserve_rng', nullcontext)
    row = example('a')
    responses = iter([[prediction(row, ['want'])], [prediction(row)], [prediction(row)], [prediction(row, ['want'])]])
    monkeypatch.setattr(module, 'generate_predictions', lambda *a, **k: next(responses))
    cli = SimpleNamespace(output_dir=str(tmp_path), model='original', resume=None,
                          early_stopping_patience=2, generation_max_new_tokens=128,
                          loss_backend='liger', gradient_accumulation=2)
    class Model:
        training = True
        def train(self, state):
            self.training = state
    trainer = SimpleNamespace(model=Model(), processing_class=None, args=SimpleNamespace(world_size=8),
                              evaluate=lambda: {'eval_loss': 1.0}, is_world_process_zero=lambda: True)
    state = SimpleNamespace(global_step=0, epoch=0, max_steps=30, best_metric=None, best_model_checkpoint=None)
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback = make_semantic_callback(object, cli, {'validation': [row]}, {'validation': []}, [], 10)
    callback.trainer = trainer
    callback.on_train_begin(None, state, control)
    state.global_step = 10
    callback.on_step_end(None, state, control)
    assert state.best_model_checkpoint == str(tmp_path/'checkpoint-10')
    assert control.should_save
    callback.on_save(None, state, control)
    (tmp_path/'checkpoint-10'/'trainer_state.json').write_text('{}')
    cli.resume = str(tmp_path/'checkpoint-10')
    resumed = make_semantic_callback(object, cli, {'validation': [row]}, {'validation': []}, [], 10)
    resumed.trainer = trainer
    assert resumed.selection.best_step == 10
    state.global_step = 20
    resumed.on_step_end(None, state, control)
    state.global_step = 30
    resumed.on_step_end(None, state, control)
    assert control.should_training_stop
    assert state.best_model_checkpoint == str(tmp_path/'checkpoint-10')
    assert trainer.model.training


def test_generation_uses_no_labels_restores_mode_and_bounds_logits(monkeypatch):
    import sys
    import torch
    from training.b_sft.generation import generate_predictions
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(GenerationConfig=lambda **kw: SimpleNamespace(**kw)))
    class Model:
        training = True
        generation_config = SimpleNamespace(eos_token_id=9)
        def train(self, value):
            self.training = value
        def eval(self):
            self.train(False)
        def generate(self, **kwargs):
            assert not self.training and not torch.is_grad_enabled()
            assert 'labels' not in kwargs and kwargs['skip_logits'] is False
            assert kwargs['logits_to_keep'] == 1 and kwargs['synced_gpus'] is False
            assert kwargs['generation_config'].do_sample is False
            assert kwargs['generation_config'].use_cache is True
            return torch.tensor([[1, 2, 7, 9]])
    class Tokenizer:
        eos_token_id, pad_token_id, bos_token_id = 9, 9, None
        def decode(self, ids, **kwargs):
            assert ids == [7, 9]
            return response()
    model = Model()
    trainer = SimpleNamespace(model_wrapped=model, args=SimpleNamespace(process_index=0, world_size=1, device='cpu'),
                              accelerator=SimpleNamespace(unwrap_model=lambda m: m, autocast=nullcontext))
    results = generate_predictions(trainer, [dict(id='a', input_ids=[1, 2])], Tokenizer(), 128, 'liger')
    assert results[0]['status'] == 'ok' and results[0]['generated_tokens'] == 2
    assert model.training


def test_rng_is_restored():
    import random
    import numpy as np
    import torch
    from training.b_sft.generation import preserve_rng
    random.seed(32)
    np.random.seed(32)
    torch.manual_seed(32)
    with preserve_rng():
        inside = random.random(), np.random.rand(), torch.rand(1).item()
    outside = random.random(), np.random.rand(), torch.rand(1).item()
    assert inside == outside


def test_heldout_eval_never_selects_or_saves(tmp_path, monkeypatch):
    import training.b_sft.semantic_callback as module
    monkeypatch.setattr(module, 'preserve_rng', nullcontext)
    row = example('a')
    monkeypatch.setattr(module, 'generate_predictions', lambda *a, **k: [prediction(row)])
    base = ['--model', 'm', '--eval-file', 'e', '--output-dir', str(tmp_path), '--semantic-eval']
    cli = parse_args(base + ['--mode', 'eval', '--eval-split', 'ood_test'])
    with pytest.raises(SystemExit):
        parse_args(base + ['--mode', 'train', '--train-file', 't', '--eval-split', 'test'])
    model = SimpleNamespace(training=False)
    model.train = lambda value: setattr(model, 'training', value)
    trainer = SimpleNamespace(model=model, processing_class=None, args=SimpleNamespace(world_size=1),
                              is_world_process_zero=lambda: True)
    callback = make_semantic_callback(object, cli, {'ood_test': [row]}, {'ood_test': []}, [], 1)
    callback.trainer = trainer
    state = SimpleNamespace(global_step=0, epoch=0)
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback.run(state, control, select=False, include_loss=False, existing_loss_metrics={'eval_loss': 1.2})
    assert not control.should_save and not control.should_training_stop
    assert not (tmp_path/'selection.json').exists()
    assert (tmp_path/'semantic/step-000000/ood_test/questions.csv').is_file()
    from training.b_sft.report import render
    assert '1.2000' in render(tmp_path) and '/ood_test/' in render(tmp_path)


def test_new_corpus_ready_and_file_integrity(tmp_path):
    import hashlib
    from training.b_sft.data import check_corpus_export
    (tmp_path/'manifest.json').write_text(json.dumps({'version': 'b-corpus-n345-v2'}))
    row = tmp_path/'train.jsonl'
    row.write_text('example\n')
    with pytest.raises(ValueError, match='incomplete'):
        check_corpus_export(row)
    hashes = tmp_path/'checksums.json'
    hashes.write_text(json.dumps({'train.jsonl': hashlib.sha256(row.read_bytes()).hexdigest()}))
    (tmp_path/'READY.json').write_text(json.dumps({'complete': True, 'checksums_sha256': hashlib.sha256(hashes.read_bytes()).hexdigest()}))
    check_corpus_export(row)
    row.write_text('tampered\n')
    with pytest.raises(ValueError, match='checksum mismatch'):
        check_corpus_export(row)


def test_baseline_requires_identical_prompts_and_decoding(tmp_path):
    import hashlib
    row = example('a')
    path = tmp_path/'baseline.jsonl'
    pred = prediction(row)
    pred['prompt_sha256'] = hashlib.sha256(b'actual prompt').hexdigest()
    pred['decoding'] = dict(do_sample=False, num_beams=1, max_new_tokens=128, enforced_greedy=True)
    path.write_text(json.dumps(pred)+'\n')
    cli = SimpleNamespace(output_dir=str(tmp_path), resume=None, baseline_predictions=str(path),
                          eval_split='test', generation_max_new_tokens=128)
    make_semantic_callback(object, cli, {'test': [row]}, {'test': [dict(id='a', prompt='actual prompt')]}, [], 1)
    with pytest.raises(ValueError, match='prompt/template/tools'):
        make_semantic_callback(object, cli, {'test': [row]}, {'test': [dict(id='a', prompt='changed prompt')]}, [], 1)


def test_small_validation_keeps_sources_and_whole_pairs():
    from training.b_sft.generation import select_validation_pairs
    records = [example(f'{s}{i}', source=s) for s in ('s', 't') for i in range(6)]
    pairs = [dict(source_id=s, before=f'{s}{i}', after=f'{s}{i+1}')
             for s in ('s', 't') for i in (0, 2, 4)]
    selected = select_validation_pairs(records, pairs, 2)
    assert len(selected) == 8
    assert {r['source_id'] for r in selected} == {'s', 't'}
    ids = {r['id'] for r in selected}
    assert all((p['before'] in ids) == (p['after'] in ids) for p in pairs)
    changed = [dict(r, messages=[]) for r in records]
    assert [r['id'] for r in select_validation_pairs(changed, list(reversed(pairs)), 2)] == [r['id'] for r in selected]


def test_all_possible_shortcut_is_visible_without_model_evaluation():
    rows = [example('a', values=('want', 'neutral', 'avoid')), example('b', values=('want',))]
    predictions = [prediction(r, ['want', 'neutral', 'avoid']) for r in rows]
    metrics = score_records(rows, predictions)[0]
    diagnostics = metrics['shortcut_diagnostics']
    assert diagnostics['prediction_counts'] == {'want|neutral|avoid': 2}
    assert diagnostics['all_possible_baseline_exact'] == 0.5
    assert diagnostics['excess_exact_over_all_possible'] == 0.0
    assert diagnostics['informative_questions']['n'] == 1
    assert diagnostics['informative_questions']['exact_rate_all'] == 0.0


def test_restart_reuses_verified_baseline_without_loss_or_generation(tmp_path, monkeypatch):
    import hashlib
    import training.b_sft.semantic_callback as module
    monkeypatch.setattr(module, 'preserve_rng', nullcontext)
    monkeypatch.setattr(module, 'generate_predictions', lambda *a, **k: pytest.fail('Must reuse baseline'))
    old = tmp_path/'old'
    saved = old/'semantic/step-000000/validation'
    saved.mkdir(parents=True)
    dataset = tmp_path/'eval.jsonl'
    dataset.write_text('dataset')
    (old/'run_manifest_1.json').write_text(json.dumps(dict(arguments={'model': 'original'},
        eval_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest())))
    row = example('a')
    pred = prediction(row)
    pred.update(prompt_sha256=hashlib.sha256(b'prompt').hexdigest(),
                decoding=dict(do_sample=False, num_beams=1, max_new_tokens=64, enforced_greedy=True))
    (saved/'predictions.jsonl').write_text(json.dumps(pred)+'\n')
    cli = parse_args(['--model', 'original', '--train-file', 't', '--eval-file', str(dataset),
                      '--output-dir', str(tmp_path/'new'), '--mode', 'train', '--semantic-eval',
                      '--skip-eval-loss', '--train-probe-size', '0', '--generation-max-new-tokens', '64',
                      '--reuse-baseline-run', str(old)])
    callback = make_semantic_callback(object, cli, {'validation': [row]},
                                     {'validation': [dict(id='a', prompt='prompt')]}, [], 100)
    model = SimpleNamespace(training=True)
    model.train = lambda value: setattr(model, 'training', value)
    callback.trainer = SimpleNamespace(model=model, processing_class=None,
        args=SimpleNamespace(world_size=1),
        is_world_process_zero=lambda: True,
        evaluate=lambda: pytest.fail('Must skip loss'))
    state = SimpleNamespace(global_step=0, epoch=0)
    control = SimpleNamespace(should_save=False, should_training_stop=False)
    callback.on_train_begin(None, state, control)
    assert callback.selection.best_step == 0
    assert callback.selection.best_score == 1.0
    assert (tmp_path/'new/semantic/step-000000/validation/predictions.jsonl').exists()
    cli.model = 'different'
    with pytest.raises(ValueError, match='model differs'):
        make_semantic_callback(object, cli, {'validation': [row]}, {'validation': []}, [], 100)


def test_export_uses_selected_model_and_skips_original(tmp_path, capsys):
    from training.b_sft.export import main, resolve_source
    path = tmp_path/'selection.json'
    path.write_text(json.dumps(dict(selected_model='/models/original', selected_original=True)))
    main(['--selection-file', str(path)])
    assert json.loads(capsys.readouterr().out)['export_required'] is False
    path.write_text(json.dumps(dict(selected_model='/runs/checkpoint-10', selected_original=False)))
    assert resolve_source(selection_file=path) == ('/runs/checkpoint-10', False)
    with pytest.raises(ValueError):
        resolve_source(checkpoint='x', selection_file=path)


def test_v2_answer_only_prompt_rejects_reasoning_preface():
    assert parse_response(response(), allow_preface=False)['status'] == 'ok'
    assert parse_response('Reasoning text\n' + response(), allow_preface=False)['status'] == 'protocol_failure'
    assert parse_response('Reasoning text\n' + response(), allow_preface=True)['status'] == 'ok'
