"""Optional real-kernel acceptance test: python -m pytest training/b_sft/test_liger_cuda.py -q."""

import pytest


def test_qwen3_fused_loss_and_accumulated_gradients(tmp_path):
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available():
        pytest.skip('Requires a CUDA GPU and compatible Liger installation')
    pytest.importorskip('liger_kernel')
    transformers = pytest.importorskip('transformers')
    from training.b_sft.loss_backend import (
        FusedLossMixin, backend_options, validate_liger_support, verify_patch,
    )
    validate_liger_support()
    torch.manual_seed(42)
    config = transformers.Qwen3Config(
        vocab_size=256, hidden_size=64, intermediate_size=128, num_hidden_layers=2,
        num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        attention_dropout=0.0, tie_word_embeddings=False, use_cache=False,
    )
    model = transformers.Qwen3ForCausalLM(config).to(device='cuda', dtype=torch.bfloat16)
    model.train()
    batches = []
    for target_length in (3, 7):
        ids = torch.randint(0, 256, (1, 24), device='cuda')
        labels = ids.clone()
        labels[:, :-target_length] = -100
        batches.append(dict(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels))
    # Unequal target counts expose accidental mean-of-microbatch-means normalization.
    denominator = torch.tensor(10, device='cuda')
    baseline = 0.0
    for batch in batches:
        loss = model(**batch, num_items_in_batch=denominator).loss
        baseline += loss.detach().float()
        loss.backward()
    gradients = {name: p.grad.detach().clone() for name, p in model.named_parameters()}
    model.zero_grad(set_to_none=True)

    class Trainer(FusedLossMixin, transformers.Trainer):
        pass
    args = transformers.TrainingArguments(
        output_dir=str(tmp_path), bf16=True, report_to=[], **backend_options('liger'))
    trainer = Trainer(model=model, args=args)
    verify_patch(model)
    fused = 0.0
    for batch in batches:
        loss, outputs = trainer.compute_loss(model, batch, return_outputs=True, num_items_in_batch=denominator)
        assert outputs.logits is None
        fused += loss.detach().float()
        loss.backward()
    torch.testing.assert_close(fused, baseline, rtol=0.01, atol=0.01)
    for name, parameter in model.named_parameters():
        assert parameter.grad is not None, name
        # BF16 kernels need not be bitwise equal; compare relative gradient norm per parameter.
        reference = gradients[name].float()
        relative_error = (parameter.grad.float() - reference).norm() / reference.norm().clamp_min(1e-8)
        assert relative_error < 0.08, (name, relative_error.item())
    model.eval()
    with torch.no_grad():
        loss, outputs = trainer.compute_loss(model, batches[0], return_outputs=True,
                                              num_items_in_batch=denominator)
    assert outputs.logits is None
    assert torch.isfinite(loss)
    # Generation must materialize only last-position logits, then allow loss/backward again.
    from training.b_sft.generation import generate_predictions
    class Tokenizer:
        eos_token_id, pad_token_id, bos_token_id = 255, 255, None
        def decode(self, ids, **kwargs):
            return ' '.join(map(str, ids))
    model.generation_config.eos_token_id = 255
    model.train()
    predictions = generate_predictions(trainer, [dict(id='tiny', input_ids=[1, 2, 3])], Tokenizer(), 4, 'liger')
    assert len(predictions) == 1 and predictions[0]['generated_tokens'] <= 4
    assert model.training
    model.zero_grad(set_to_none=True)
    loss, outputs = trainer.compute_loss(model, batches[0], return_outputs=True)
    assert outputs.logits is None
    loss.backward()
    assert torch.isfinite(loss)
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


def test_zero3_fused_head_eval_generate_backward():
    """Opt-in two-GPU regression; ordinary local pytest never starts distributed work.

    torchrun --standalone --nproc_per_node=2 -m pytest -q \
        training/b_sft/test_liger_cuda.py -k zero3
    """
    import os
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available() or int(os.environ.get('WORLD_SIZE', '1')) < 2:
        pytest.skip('Requires CUDA and an explicit multi-rank torchrun invocation')
    ds = pytest.importorskip('deepspeed')
    transformers = pytest.importorskip('transformers')
    pytest.importorskip('liger_kernel')
    from liger_kernel.transformers.monkey_patch import apply_liger_kernel_to_qwen3
    from training.b_sft.loss_backend import register_zero3_fused_head, backend_options
    from deepspeed.utils import safe_get_full_grad
    torch.cuda.set_device(int(os.environ['LOCAL_RANK']))
    ds.init_distributed()
    torch.manual_seed(42)
    config = transformers.Qwen3Config(
        vocab_size=256, hidden_size=64, intermediate_size=128, num_hidden_layers=2,
        num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        tie_word_embeddings=False, use_cache=False, eos_token_id=255, pad_token_id=255)
    ds_config = dict(train_micro_batch_size_per_gpu=1, gradient_accumulation_steps=1,
                     bf16={'enabled': True}, zero_allow_untested_optimizer=True,
                     zero_optimization=dict(stage=3, overlap_comm=False,
                                            stage3_param_persistence_threshold=0))
    apply_liger_kernel_to_qwen3(**backend_options('liger')['liger_kernel_config'])
    with ds.zero.Init(config_dict_or_path=ds_config):
        model = transformers.Qwen3ForCausalLM(config)
    assert register_zero3_fused_head(model)['registered']
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    engine, _, _, _ = ds.initialize(model=model, optimizer=optimizer, config=ds_config)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    ids = torch.tensor([[1, 2, 3, 4, 5, 6]], device=engine.device)
    labels = ids.clone()
    labels[:, :3] = -100
    batch = dict(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels,
                 skip_logits=True)
    for _ in range(2):
        engine.eval()
        with torch.no_grad():
            output = engine(**batch)
            assert output.logits is None and torch.isfinite(output.loss)
            generated = model.generate(input_ids=ids[:, :3],
                                       attention_mask=torch.ones_like(ids[:, :3]),
                                       do_sample=False, max_new_tokens=2, use_cache=True,
                                       synced_gpus=True, skip_logits=False, logits_to_keep=1)
            assert generated.shape[1] > 3
        engine.train()
        output = engine(**batch)
        assert output.logits is None and torch.isfinite(output.loss)
        engine.backward(output.loss)
        gradient = safe_get_full_grad(model.lm_head.weight)
        assert gradient is not None and torch.isfinite(gradient).all()
        assert gradient.abs().sum() > 0
        engine.step()
