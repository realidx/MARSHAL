"""User-run pinned model download, using the existing huggingface_hub package."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    from huggingface_hub import snapshot_download
    profile = json.loads(Path(__file__).with_name('qwen17_profile.json').read_text())
    destination = Path(sys.argv[1]).resolve()
    print(f"Model: {profile['repo_id']} @ {profile['revision']} -> {destination}", flush=True)
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
    (destination/'probe_revision.json').write_text(json.dumps(profile, indent=2)+'\n')
    print('Pinned model download complete.', flush=True)


if __name__ == '__main__':
    main()
