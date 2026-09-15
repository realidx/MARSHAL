"""User-run pinned model download, using the existing huggingface_hub package."""
import hashlib
import argparse
import json
from pathlib import Path
import sys


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('destination', type=Path)
    cli.add_argument('--local-only', action='store_true', help='Verify existing pinned model without network')
    args = cli.parse_args()
    profile = json.loads(Path(__file__).with_name('qwen17_profile.json').read_text())
    destination = args.destination.resolve()
    print(f"Model: {profile['repo_id']} @ {profile['revision']} -> {destination}", flush=True)
    if args.local_only:
        recorded = json.loads((destination/'probe_revision.json').read_text())
        if any(recorded[k] != profile[k] for k in ('repo_id', 'revision')):
            raise ValueError('Existing model does not match pinned revision')
    else:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=profile['repo_id'], revision=profile['revision'], local_dir=str(destination),
                          allow_patterns=['*.json', '*.safetensors', 'merges.txt', 'vocab.json', 'LICENSE'],
                          max_workers=4)
    for name, digest in profile['model_files_sha256'].items():
        if hashlib.sha256((destination/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Downloaded model metadata/tokenizer mismatch: '+name)
    index = json.loads((destination/'model.safetensors.index.json').read_text())
    for name in set(index['weight_map'].values()):
        if not (destination/name).is_file() or (destination/name).stat().st_size == 0:
            raise ValueError('Missing weight shard: '+name)
    if not args.local_only:
        (destination/'probe_revision.json').write_text(json.dumps(profile, indent=2)+'\n')
    print('Existing pinned model verified; no download.' if args.local_only else 'Pinned model download complete.', flush=True)


if __name__ == '__main__':
    main()
