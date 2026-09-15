"""Export a completed native checkpoint on CPU for the existing A100 vLLM."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('checkpoint',type=Path)
    cli.add_argument('output',type=Path)
    args=cli.parse_args()
    if not (args.checkpoint/'COMPLETE.json').is_file():raise ValueError('Checkpoint not complete')
    if args.output.exists():raise FileExistsError(args.output)
    # CPU conversion in the existing SoC environment; does not occupy a GPU.
    os.environ['CUDA_VISIBLE_DEVICES']=''
    from mcore_adapter.models.converter.post_converter import convert_checkpoint_to_hf
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=Path(tempfile.mkdtemp(prefix='.social-export-',dir=args.output.parent))
    try:
        convert_checkpoint_to_hf(str(args.checkpoint),str(tmp/'model'),verbose=False)
        files=list((tmp/'model').glob('*.safetensors'))
        if not files or not (tmp/'model/config.json').is_file():raise RuntimeError('HF conversion incomplete')
        (tmp/'model/export_source.json').write_text(json.dumps(dict(checkpoint=str(args.checkpoint.resolve()),
            native_completion=json.loads((args.checkpoint/'COMPLETE.json').read_text())))+'\n')
        (tmp/'model').rename(args.output)
    finally:shutil.rmtree(tmp)


if __name__=='__main__':main()
