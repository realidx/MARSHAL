"""Real HF callback/save integration; optional on hosts without Transformers."""

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('policy,expected_saves', [('all-evals', [1, 2, 3]), ('best-and-periodic', [1, 3])])
def test_real_trainer_protects_best_and_stops(tmp_path, monkeypatch, policy, expected_saves):
    torch = pytest.importorskip('torch')
    hf = pytest.importorskip('transformers')
    pytest.importorskip('accelerate')
    from training.b_sft.data import ToolCollator
    from training.b_sft.semantic_callback import make_semantic_callback
    from training.b_sft.test_semantic import example, prediction
    import training.b_sft.semantic_callback as callback_module
    row = example('a')
    responses = iter([[prediction(row, ['want'])], [prediction(row)], [prediction(row)], [prediction(row, ['want'])]])
    monkeypatch.setattr(callback_module, 'generate_predictions', lambda *a, **k: next(responses))
    cli = SimpleNamespace(output_dir=str(tmp_path), model='original', resume=None,
                          early_stopping_patience=2, generation_max_new_tokens=128,
                          loss_backend='standard', gradient_accumulation=1, checkpoint_policy=policy,
                          skip_eval_loss=True)
    callback = make_semantic_callback(hf.TrainerCallback, cli, {'validation': [row]}, {'validation': []}, [], 1)
    config = hf.Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
                           num_attention_heads=2, num_key_value_heads=2, head_dim=16, use_cache=False)
    model = hf.Qwen3ForCausalLM(config)
    args = hf.TrainingArguments(output_dir=str(tmp_path), use_cpu=True, max_steps=4,
                               per_device_train_batch_size=1, per_device_eval_batch_size=1,
                               save_steps=3, save_total_limit=2, eval_strategy='no', report_to=[],
                               logging_steps=1, disable_tqdm=True)
    data = [dict(input_ids=[1, 2, 3, 4], attention_mask=[1]*4, labels=[-100, -100, 3, 4])]*4
    trainer = hf.Trainer(model=model, args=args, train_dataset=data, eval_dataset=data[:1],
                         data_collator=ToolCollator(0), callbacks=[callback])
    callback.trainer = trainer
    monkeypatch.setattr(trainer, 'evaluate', lambda *a, **k: pytest.fail('Loss evaluation must be skipped'))
    saves = []
    original_save = trainer._save_checkpoint
    def save(*args, **kwargs):
        saves.append(trainer.state.global_step)
        return original_save(*args, **kwargs)
    monkeypatch.setattr(trainer, '_save_checkpoint', save)
    trainer.train()
    assert saves == expected_saves
    assert trainer.state.global_step == 3
    assert [r['step'] for r in trainer.state.log_history if 'loss' in r] == [1, 2, 3]
    assert callback.selection.best_step == 1
    assert {p.name for p in tmp_path.glob('checkpoint-*')} == {'checkpoint-1', 'checkpoint-3'}
    assert (tmp_path/'checkpoint-3'/'semantic_selection.json').is_file()
    assert trainer.state.best_model_checkpoint == str(tmp_path/'checkpoint-1')


def test_real_qwen_generation_then_backward(tmp_path):
    torch = pytest.importorskip('torch')
    hf = pytest.importorskip('transformers')
    pytest.importorskip('accelerate')
    from training.b_sft.generation import generate_predictions
    config = hf.Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
                           num_attention_heads=2, num_key_value_heads=2, head_dim=16, use_cache=False)
    model = hf.Qwen3ForCausalLM(config)
    model.generation_config.eos_token_id = 31
    model.generation_config.do_sample = True
    model.generation_config.temperature = 0.7
    model.generation_config.top_k = 20
    model.generation_config.top_p = 0.8
    original_prepare = model._prepare_generation_config
    def prepare(*args, **kwargs):
        config, model_kwargs = original_prepare(*args, **kwargs)
        assert config.do_sample is False
        assert config.num_beams == 1
        assert config.temperature == 1.0 and config.top_p == 1.0
        return config, model_kwargs
    model._prepare_generation_config = prepare
    args = hf.TrainingArguments(output_dir=str(tmp_path), use_cpu=True, report_to=[])
    trainer = hf.Trainer(model=model, args=args)
    class Tokenizer:
        eos_token_id, pad_token_id, bos_token_id = 31, 31, None
        def decode(self, ids, **kwargs):
            return ' '.join(map(str, ids))
    shapes = []
    hook = model.lm_head.register_forward_hook(lambda module, inputs, output: shapes.append(tuple(output.shape)))
    model.gradient_checkpointing_enable()
    model.train()
    results = generate_predictions(trainer, [dict(id='a', input_ids=[1, 2, 3])], Tokenizer(), 4, 'standard')
    hook.remove()
    assert model.training and model.is_gradient_checkpointing
    assert shapes and all(shape == (1, 1, 32) for shape in shapes)
    assert results[0]['generated_tokens'] <= 4
    ids = torch.tensor([[1, 2, 3, 4]])
    loss = model(input_ids=ids, labels=ids).loss
    loss.backward()
    assert torch.isfinite(loss)
    assert all(p.grad is not None for p in model.parameters())
