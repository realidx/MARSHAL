from types import SimpleNamespace

import pytest

from training.b_sft.loss_backend import FusedLossMixin, backend_options, verify_patch


def test_only_linear_ce_is_replaced():
    flags = backend_options('liger')['liger_kernel_config']
    assert [name for name, enabled in flags.items() if enabled] == ['fused_linear_cross_entropy']
    assert backend_options('standard') == {'use_liger_kernel': False}


def test_fused_eval_and_train_forward_normalization_unchanged():
    class Parent:
        def compute_loss(self, model, inputs, **kwargs):
            return inputs, kwargs
    class Trainer(FusedLossMixin, Parent):
        pass
    original = {'labels': [1, -100]}
    inputs, kwargs = Trainer().compute_loss(None, original, True, 17)
    assert inputs['skip_logits'] is True
    assert 'skip_logits' not in original
    assert kwargs == {'return_outputs': True, 'num_items_in_batch': 17}


def test_patch_must_support_explicit_skip_logits():
    def forward(skip_logits=None):
        pass
    with pytest.raises(RuntimeError, match='not applied'):
        verify_patch(SimpleNamespace(forward=forward))
    forward.__module__ = 'liger_kernel.transformers.model.qwen3'
    assert verify_patch(SimpleNamespace(forward=forward))['name'] == 'forward'


def test_zero3_fused_head_registers_owner_without_materializing(monkeypatch):
    import sys
    from training.b_sft.loss_backend import register_zero3_fused_head
    def forward(skip_logits=None):
        pass
    forward.__module__ = 'liger_kernel.transformers.model.qwen3'
    # A partitioned weight can have an empty local shape despite its full shape.
    weight = SimpleNamespace(ds_id=1, ds_shape=(256, 64), shape=(0,))
    model = SimpleNamespace(forward=forward, lm_head=SimpleNamespace(weight=weight))
    calls = []
    # Match the real package layout: zero is an attribute, not a submodule.
    from types import ModuleType
    package = ModuleType('deepspeed')
    package.zero = SimpleNamespace(
        register_external_parameter=lambda owner, parameter: calls.append((owner, parameter)))
    monkeypatch.setitem(sys.modules, 'deepspeed', package)
    monkeypatch.delitem(sys.modules, 'deepspeed.zero', raising=False)
    result = register_zero3_fused_head(model)
    assert calls == [(model, weight)]
    assert result['registered'] and result['full_shape'] == [256, 64]
    assert weight.shape == (0,)
    model.lm_head.weight = SimpleNamespace(shape=(256, 64))
    assert not register_zero3_fused_head(model)['registered']
    assert len(calls) == 1
