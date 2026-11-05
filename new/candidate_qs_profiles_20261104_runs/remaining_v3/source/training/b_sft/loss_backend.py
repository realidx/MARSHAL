"""Select the CE implementation without changing Trainer's loss normalization."""

import inspect
from importlib.metadata import PackageNotFoundError, version


def backend_options(backend):
    if backend == 'standard':
        return {'use_liger_kernel': False}
    if backend != 'liger':
        raise ValueError(f'Unknown loss backend: {backend}')
    return dict(use_liger_kernel=True, liger_kernel_config=dict(
        rope=False, rms_norm=False, swiglu=False, cross_entropy=False,
        fused_linear_cross_entropy=True))


def validate_liger_support():
    """Fail before loading weights, including for versions that fuse training only."""
    try:
        from liger_kernel.transformers.model.qwen3 import lce_forward
        from liger_kernel.transformers.monkey_patch import apply_liger_kernel_to_qwen3
    except ImportError as error:
        raise RuntimeError('Liger backend requires liger-kernel with Qwen3 support in this training environment. '
                           'Install a compatible version, or explicitly use --loss-backend standard for the baseline.') from error
    required = backend_options('liger')['liger_kernel_config']
    if not set(required).issubset(inspect.signature(apply_liger_kernel_to_qwen3).parameters):
        raise RuntimeError('Installed Liger does not expose the required Qwen3 patch controls')
    if 'skip_logits' not in inspect.signature(lce_forward).parameters:
        raise RuntimeError('Installed Liger Qwen3 forward lacks skip_logits; use a version supporting fused eval loss')


def verify_patch(model):
    forward = model.forward
    if (not forward.__module__.startswith('liger_kernel.')
            or 'skip_logits' not in inspect.signature(forward).parameters):
        raise RuntimeError('Qwen3 fused CE patch was not applied; refusing silent full-logits fallback')
    return dict(module=forward.__module__, name=forward.__name__)


def register_zero3_fused_head(model):
    """Register direct lm_head weight use in the enclosing Qwen3 forward.

    Liger bypasses lm_head.__call__, so its ordinary ZeRO module hooks do not
    guarantee that the weight is gathered. Register before engine setup so
    ZeRO coordinates this external parameter in both forward and backward.
    This does not gather the full model or make the head permanently resident.
    """
    verify_patch(model)
    weight = model.lm_head.weight
    if not hasattr(weight, 'ds_id'):
        return dict(registered=False, reason='not_zero3_partitioned')
    # zero is an attribute exported from deepspeed.runtime, not an importable
    # deepspeed.zero subpackage.
    import deepspeed
    deepspeed.zero.register_external_parameter(model, weight)
    return dict(registered=True, parameter='lm_head.weight',
                full_shape=list(weight.ds_shape))


class FusedLossMixin:
    """Use the fused path for both training and loss-only evaluation."""

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        if 'labels' not in inputs:
            raise ValueError('Fused B-SFT requires labels')
        inputs = dict(inputs, skip_logits=True)
        # Keep HF's num_items_in_batch, distributed scaling and gradient accumulation behavior.
        return super().compute_loss(model, inputs, return_outputs=return_outputs,
                                    num_items_in_batch=num_items_in_batch)


def package_versions():
    result = {}
    for name in ('torch', 'transformers', 'accelerate', 'deepspeed', 'liger-kernel', 'triton'):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result
