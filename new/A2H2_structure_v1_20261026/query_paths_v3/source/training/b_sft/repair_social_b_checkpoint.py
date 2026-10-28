"""Recover a checkpoint from retained worker files without overwriting the failed copy."""
import argparse
from pathlib import Path
from roll.utils.upload_utils import FileSystemUploader
from roll.utils.checkpoint_integrity import complete_deepspeed_checkpoint


def repair(run_dir, step, world_size):
    run = Path(run_dir).resolve()
    name = f'checkpoint-{step}'
    recovered = name + '-recovered'
    target = run/'checkpoints'/recovered
    if target.exists():
        raise FileExistsError(f'Will not overwrite recovery: {target}')
    sources = [run/f'actor_train-{rank}'/name for rank in range(world_size)]
    pipeline = run/'checkpoints'/name/'pipeline'
    if not all(p.is_dir() for p in sources) or not pipeline.is_dir():
        raise FileNotFoundError('Recovery requires every worker source and the pipeline state')
    publisher = FileSystemUploader(str(run/'checkpoints'), use_hardlinks=True)
    for source in sources:
        publisher.upload(recovered, str(source))
    publisher = FileSystemUploader(str(target), use_hardlinks=True)
    publisher.upload('pipeline', str(pipeline))
    complete_deepspeed_checkpoint(target, world_size, step)
    print(target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--step', type=int, required=True)
    parser.add_argument('--world-size', type=int, required=True)
    args = parser.parse_args()
    repair(args.run_dir, args.step, args.world_size)
