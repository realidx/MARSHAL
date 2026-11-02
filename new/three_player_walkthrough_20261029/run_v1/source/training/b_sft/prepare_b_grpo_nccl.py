"""Extract the cu11 NCCL binary privately; never overwrite site-packages."""
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile
import base64

EXPECTED = 'Tejvap0n5F4OPQZ8gf3ApxA8sxjjRVfaJZSaQjCpyq8'


def digest(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')


def verify_library(path):
    path=Path(path).resolve()
    if digest(path.read_bytes())!=EXPECTED:
        raise RuntimeError(f'Private NCCL does not match the cu11 binary used by the completed B run: {path}')
    return str(path)


def verify_loaded_library(path, maps_path='/proc/self/maps'):
    expected=str(Path(path).resolve())
    mapped=sorted({line.split()[-1] for line in Path(maps_path).read_text().splitlines() if 'libnccl.so' in line})
    if not mapped or any(p!=expected for p in mapped):
        raise RuntimeError(f'Expected verified private NCCL {expected}, actually loaded {mapped}; check LD_PRELOAD')
    return mapped


def main():
    root = Path('new/local_data/b_grpo_runtime')
    target = root / 'nccl_cu11/lib/libnccl.so.2'
    if target.exists():
        assert digest(target.read_bytes()) == EXPECTED, 'Unexpected private NCCL binary'
        print(target, 'verified')
        return
    wheel_dir = root / 'wheels'
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheels = list(wheel_dir.glob('nvidia_nccl_cu11-2.21.5-*.whl'))
    if not wheels:
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps',
                        '--dest', str(wheel_dir), 'nvidia-nccl-cu11==2.21.5'], check=True)
        wheels = list(wheel_dir.glob('nvidia_nccl_cu11-2.21.5-*.whl'))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        binary = archive.read('nvidia/nccl/lib/libnccl.so.2')
    assert digest(binary) == EXPECTED, 'NCCL wheel does not match cu11 package record'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(binary)
    print(target, 'extracted and verified')


if __name__ == '__main__':
    main()
