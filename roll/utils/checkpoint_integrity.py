"""Completion manifests for synchronous, local DeepSpeed checkpoints."""
import json
from pathlib import Path
import zipfile


def complete_deepspeed_checkpoint(directory, world_size, step):
    root = Path(directory)
    required = [root / 'config.json', root / 'tokenizer_config.json', root / 'tokenizer.json',
                root / 'pipeline/worker_state_pipeline.json', root / 'pipeline/rng_state_pipeline.pth']
    index = root / 'pytorch_model.bin.index.json'
    if index.exists():
        required.append(index)
        required.extend(root / name for name in set(json.loads(index.read_text())['weight_map'].values()))
    else:
        required.append(root / 'pytorch_model.bin')
    for rank in range(world_size):
        required.extend([
            root / f'checkpoint/bf16_zero_pp_rank_{rank}_mp_rank_00_optim_states.pt',
            root / f'checkpoint/zero_pp_rank_{rank}_mp_rank_00_model_states.pt',
        ])
    # ZeRO-2 writes one replicated model-state file, unlike ZeRO-3's per-rank files.
    if (root / 'checkpoint/mp_rank_00_model_states.pt').exists():
        required = [p for p in required if not p.name.startswith('zero_pp_rank_')]
        required.append(root / 'checkpoint/mp_rank_00_model_states.pt')
    for path in required:
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f'Incomplete checkpoint: {path}')
        if path.suffix in ('.bin', '.pt', '.pth'):
            # Directory validation catches interrupted torch.save, without rereading tens of GB.
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist():
                    raise RuntimeError(f'Empty checkpoint archive: {path}')
    manifest = dict(step=step, world_size=world_size,
                    validation='required files, sizes and ZIP directories; not a resume test',
                    files={str(p.relative_to(root)): p.stat().st_size for p in required})
    temporary = root / 'COMPLETE.json.tmp'
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(root / 'COMPLETE.json')
    return manifest
