"""CPU-only consolidation of a trusted local Trainer/DeepSpeed checkpoint."""

import argparse
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path


def independent_shard_tensors(tensors):
    """Retain every checkpoint key/value, copying only storage aliases per shard."""
    result, storages = {}, set()
    for name, tensor in tensors.items():
        storage = (tensor.device, tensor.untyped_storage().data_ptr())
        if tensor.numel() and storage in storages:
            tensor = tensor.clone()
        elif tensor.numel():
            storages.add(storage)
        result[name] = tensor.contiguous()
    return result


@contextmanager
def safetensors_alias_support():
    # DeepSpeed imports save_file inside its converter. Scope this adaptation
    # to our single-threaded CPU export and restore it even on failure.
    import safetensors.torch
    original = safetensors.torch.save_file
    def save(tensors, filename, metadata=None):
        return original(independent_shard_tensors(tensors), filename, metadata=metadata)
    safetensors.torch.save_file = save
    try:
        yield
    finally:
        safetensors.torch.save_file = original


def inspect_weight_checkpoint(checkpoint):
    """Weight export does not require HF's later-written trainer_state.json.

    This is only a layout check. DeepSpeed must still deserialize the shards,
    verify partition counts and reconstruct the parameter shapes successfully.
    """
    checkpoint = Path(checkpoint)
    latest = checkpoint/'latest'
    if not latest.is_file():
        raise ValueError('ZeRO export requires latest pointing to a saved step')
    tag = latest.read_text().strip()
    if not re.fullmatch(r'global_step\d+', tag):
        raise ValueError('Unexpected ZeRO latest tag')
    step = int(tag.removeprefix('global_step'))
    if re.fullmatch(r'checkpoint-\d+', checkpoint.name) and int(checkpoint.name.split('-')[-1]) != step:
        raise ValueError('ZeRO latest step differs from checkpoint directory')
    directory = checkpoint/tag
    models = list(directory.glob('*_model_states.pt'))
    optimizers = list(directory.glob('*_optim_states.pt'))
    if not models or not optimizers or any(p.stat().st_size == 0 for p in models+optimizers):
        raise ValueError('Missing or empty ZeRO weight/optimizer shards')
    return dict(tag=tag, model_shards=len(models), optimizer_shards=len(optimizers),
                trainer_state_present=(checkpoint/'trainer_state.json').is_file())


def resolve_source(checkpoint=None, selection_file=None):
    if bool(checkpoint) == bool(selection_file):
        raise ValueError('Provide exactly one checkpoint or selection file')
    if checkpoint:
        return str(checkpoint), False
    selection = json.loads(Path(selection_file).read_text())
    source = selection.get('selected_model')
    original = selection.get('selected_original')
    if not isinstance(source, str) or not source or type(original) is not bool:
        raise ValueError('Invalid semantic selection file')
    return source, original


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--checkpoint', help='checkpoint-N containing latest/global_stepN')
    source_group.add_argument('--selection-file', help='Export the model actually selected by semantic validation')
    parser.add_argument('--output-dir')
    cli = parser.parse_args(argv)
    source, original = resolve_source(cli.checkpoint, cli.selection_file)
    if original:
        print(json.dumps(dict(selected_model=source, export_required=False,
                              reason='Original HF model was selected; use its existing path.')))
        return
    if not cli.output_dir:
        parser.error('--output-dir is required when consolidating a ZeRO checkpoint')
    checkpoint, output = Path(source), Path(cli.output_dir)
    inspection = inspect_weight_checkpoint(checkpoint)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Export requires a fresh output directory')
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    os.environ['DS_ACCELERATOR'] = 'cpu'
    from deepspeed.utils.zero_to_fp32 import convert_zero_checkpoint_to_fp32_state_dict
    from transformers import AutoConfig, AutoTokenizer, GenerationConfig

    print(json.dumps(dict(export_preflight=inspection,
                         note='Weight export only; shard contents are checked during consolidation.')), flush=True)
    with safetensors_alias_support():
        convert_zero_checkpoint_to_fp32_state_dict(str(checkpoint), str(output),
                                                   tag=inspection['tag'], max_shard_size='2GB', safe_serialization=True)
    AutoConfig.from_pretrained(checkpoint).save_pretrained(output)
    AutoTokenizer.from_pretrained(checkpoint).save_pretrained(output)
    if (checkpoint / 'generation_config.json').exists():
        GenerationConfig.from_pretrained(checkpoint).save_pretrained(output)
    (output / 'export_manifest.json').write_text(json.dumps(
        dict(checkpoint=str(checkpoint.resolve()), selection_file=cli.selection_file, weights_dtype='float32',
             checkpoint_inspection=inspection, consolidation_completed=True,
             shared_tensor_serialization='copy storage aliases within each shard; preserve keys and config',
             note='Load with explicit torch_dtype=bfloat16 for BF16 inference.'), indent=2) + '\n')


if __name__ == '__main__':
    main()
