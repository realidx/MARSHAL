"""Record and verify committed Git source, with legacy archive support."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def verify_source(root):
    root = Path(root).resolve()
    if (root / '.git').exists():
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
        commit = git('rev-parse', 'HEAD')
        expected = os.environ.get('SOCIAL_SOURCE_COMMIT')
        if expected and expected != commit:
            raise ValueError(f'Checkout changed after submission: expected {expected}, got {commit}')
        if git('status', '--porcelain', '--untracked-files=normal'):
            raise ValueError('Training requires a clean Git checkout; commit changes and use a detached worktree')
        result = dict(kind='git', commit=commit, clean=True)
    else:
        manifest = root / 'examples/social_mixed/bundle_manifest.json'
        data = json.loads(manifest.read_text())
        for name, expected in data['files'].items():
            path = root / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'Incomplete or changed source archive: {name}')
        result = dict(kind='archive', sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    print('SOURCE_VERIFIED ' + json.dumps(result), flush=True)
    return result
