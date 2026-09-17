import pytest
from training.b_sft.export import inspect_weight_checkpoint


def test_weight_export_allows_missing_trainer_state(tmp_path):
    root = tmp_path/'checkpoint-100'
    shards = root/'global_step100'
    shards.mkdir(parents=True)
    (root/'latest').write_text('global_step100\n')
    for rank in range(8):
        (shards/f'zero_pp_rank_{rank}_mp_rank_00_model_states.pt').write_bytes(b'layout-only')
        (shards/f'bf16_zero_pp_rank_{rank}_mp_rank_00_optim_states.pt').write_bytes(b'layout-only')
    result = inspect_weight_checkpoint(root)
    assert result == dict(tag='global_step100', model_shards=8, optimizer_shards=8,
                          trainer_state_present=False)
    assert not (root/'trainer_state.json').exists()
    (root/'latest').write_text('global_step101')
    with pytest.raises(ValueError, match='differs'):
        inspect_weight_checkpoint(root)
    (root/'latest').write_text('../global_step100')
    with pytest.raises(ValueError, match='tag'):
        inspect_weight_checkpoint(root)


def test_weight_export_rejects_absent_or_empty_shards(tmp_path):
    root = tmp_path/'checkpoint-1'
    root.mkdir()
    with pytest.raises(ValueError, match='latest'):
        inspect_weight_checkpoint(root)
    (root/'latest').write_text('global_step1')
    (root/'global_step1').mkdir()
    with pytest.raises(ValueError, match='Missing or empty'):
        inspect_weight_checkpoint(root)


def test_shared_storage_roundtrip_and_hook_restored(tmp_path):
    torch = pytest.importorskip('torch')
    st = pytest.importorskip('safetensors.torch')
    from training.b_sft.export import safetensors_alias_support
    weight = torch.arange(12).reshape(3, 4).float()
    original = st.save_file
    path = tmp_path/'model.safetensors'
    with safetensors_alias_support():
        from safetensors.torch import save_file
        save_file({'model.embed_tokens.weight': weight, 'lm_head.weight': weight}, path,
                  metadata={'format': 'pt'})
    assert st.save_file is original
    loaded = st.load_file(path)
    for key in ('model.embed_tokens.weight', 'lm_head.weight'):
        torch.testing.assert_close(loaded[key], weight, rtol=0, atol=0)
    with pytest.raises(RuntimeError, match='interrupted'):
        with safetensors_alias_support():
            raise RuntimeError('interrupted')
    assert st.save_file is original


def test_tied_qwen_hf_load_preserves_weights_and_logits(tmp_path):
    torch = pytest.importorskip('torch')
    hf = pytest.importorskip('transformers')
    st = pytest.importorskip('safetensors.torch')
    from training.b_sft.export import safetensors_alias_support
    config = hf.Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=64,
                           num_hidden_layers=1, num_attention_heads=2,
                           num_key_value_heads=2, head_dim=16, tie_word_embeddings=True)
    model = hf.Qwen3ForCausalLM(config).eval()
    assert model.lm_head.weight is model.model.embed_tokens.weight
    config.save_pretrained(tmp_path)
    with safetensors_alias_support():
        st.save_file(model.state_dict(), tmp_path/'model.safetensors', metadata={'format': 'pt'})
    loaded, info = hf.Qwen3ForCausalLM.from_pretrained(tmp_path, output_loading_info=True)
    loaded.eval()
    assert not info['missing_keys'] and not info['unexpected_keys']
    assert loaded.lm_head.weight is loaded.model.embed_tokens.weight
    ids = torch.tensor([[1, 2, 3]])
    with torch.no_grad():
        torch.testing.assert_close(model(ids).logits, loaded(ids).logits, rtol=0, atol=0)
