"""Tiny NCCL diagnostic; no model, optimizer or training is created."""
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import torch
import torch.distributed as dist
import torch.multiprocessing as mp


def check_rank(rank, world_size, init_file):
    torch.cuda.set_device(rank)
    dist.init_process_group('nccl', init_method='file://' + init_file,
                            rank=rank, world_size=world_size, timeout=timedelta(seconds=30))
    try:
        value = torch.tensor([float(rank + 1)], device='cuda')
        dist.all_reduce(value)
        assert value.item() == world_size * (world_size + 1) / 2
        print(f'NCCL rank {rank}: all_reduce passed', flush=True)
    finally:
        dist.destroy_process_group()


def main():
    visible = os.environ.get('CUDA_VISIBLE_DEVICES', '').split(',')
    if len(visible) != 4 or len(set(visible)) != 4:
        raise SystemExit('Set CUDA_VISIBLE_DEVICES to the four assigned GPUs')
    if torch.version.cuda != '11.8':
        raise SystemExit(f'Expected working CUDA 11.8 torch, got {torch.version.cuda}')
    mapped = [line for line in Path('/proc/self/maps').read_text().splitlines() if 'libnccl.so' in line]
    expected = str(Path('new/local_data/b_grpo_runtime/nccl_cu11/lib/libnccl.so.2').resolve())
    assert mapped and all(expected in line for line in mapped), mapped
    print('NCCL loaded from:', expected, flush=True)
    with tempfile.TemporaryDirectory(prefix='b-grpo-nccl-') as tmp:
        mp.spawn(check_rank, args=(4, str(Path(tmp) / 'init')), nprocs=4, join=True)
    print('Four-GPU NCCL check passed; model training has not been tested.', flush=True)


if __name__ == '__main__':
    main()
