"""Verify archive parts and all original archived bytes without extraction."""
import hashlib,json,tarfile,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent/'raw'
m=json.loads((root/'MANIFEST.json').read_text())
with tempfile.TemporaryFile() as merged:
 whole=hashlib.sha256()
 for entry in m['archive']['parts']:
  p=root/entry['path'];h=hashlib.sha256();size=0
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1024*1024),b''):
    h.update(b);whole.update(b);merged.write(b);size+=len(b)
  assert size==entry['size'] and h.hexdigest()==entry['sha256'],p
 assert merged.tell()==m['archive']['size']
 assert whole.hexdigest()==m['archive']['sha256']
 merged.seek(0);expected={e['path']:e for e in m['files']}
 with tarfile.open(fileobj=merged,mode='r:gz') as tar:
  for member in tar:
   entry=expected.pop(member.name);h=hashlib.sha256()
   assert member.size==entry['size'],member.name
   f=tar.extractfile(member)
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
   assert h.hexdigest()==entry['sha256'],member.name
 assert not expected
print(f"Verified {len(m['files'])} original files and {len(m['archive']['parts'])} archive parts.")
