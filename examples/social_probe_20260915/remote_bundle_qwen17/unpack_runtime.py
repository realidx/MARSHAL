"""Verify and unpack the frozen v2 runtime; stdlib only, no model execution."""
import hashlib,json,sys,tarfile
from pathlib import Path,PurePosixPath

def unpack(archive,checksum,destination):
    archive=Path(archive);destination=Path(destination)
    expected=Path(checksum).read_text().split()[0]
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise ValueError('Runtime archive checksum mismatch')
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        names=set()
        for member in members:
            path=PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts or path.parts[0]!='outcome_rollout_runtime' or member.name in names:
                raise ValueError('Invalid runtime archive member')
            names.add(member.name)
            if (destination/member.name).exists():raise FileExistsError(destination/member.name)
        for member in members:
            target=destination/member.name;target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(member) as source:target.write_bytes(source.read())
    root=destination/'outcome_rollout_runtime';manifest=json.loads((root/'runtime_manifest.json').read_text())
    for name,digest in manifest['files'].items():
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:raise ValueError('Invalid manifest path')
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError(f'Runtime source mismatch: {name}')
    print(f'Runtime verified: {len(manifest["files"])} files; {root}')
    return root

if __name__=='__main__':unpack(*sys.argv[1:])
