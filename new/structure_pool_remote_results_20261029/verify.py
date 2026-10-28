"""Verify archive and all original file sizes and SHA-256 values."""
import hashlib,json,tarfile
from pathlib import Path
root=Path(__file__).resolve().parent;m=json.loads((root/'MANIFEST.json').read_text());archive=root/m['archive']['name']
def digest(f):
 h=hashlib.sha256()
 for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
assert archive.stat().st_size==m['archive']['size']
with archive.open('rb') as f:assert digest(f)==m['archive']['sha256']
expected={x['path']:x for x in m['files']};count=len(expected)
with tarfile.open(archive,'r:gz') as tar:
 for member in tar:
  x=expected.pop(member.name);assert member.isfile() and member.size==x['size'],member.name
  with tar.extractfile(member) as f:assert digest(f)==x['sha256'],member.name
assert not expected
print(f'Verified {count} original files.')
