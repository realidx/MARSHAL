"""Verify archive and all source bytes, including85 certified NPZ references."""
import hashlib,json,tarfile
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'raw/MANIFEST.json').read_text())
archive=root/'raw'/manifest['archive']['path']
def digest(f):
 h=hashlib.sha256()
 for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
assert archive.stat().st_size==manifest['archive']['size']
with archive.open('rb') as f:assert digest(f)==manifest['archive']['sha256']
expected={x['path']:x for x in manifest['files']};original=dict(expected)
with tarfile.open(archive,'r:gz') as tar:
 for member in tar:
  item=expected.pop(member.name)
  assert member.isfile() and member.size==item['size'],member.name
  with tar.extractfile(member) as f:assert digest(f)==item['sha256'],member.name
assert not expected
refs=json.loads((root/'CERTIFIED_REFERENCES.json').read_text())['references']
assert len(refs)==85 and len({r['index'] for r in refs})==85
for r in refs:
 assert original[r['reference_path']]['sha256']==r['reference_sha256']
 assert original[r['result_path']]['sha256']==r['result_sha256']
print(f'Verified {len(original)} original files and85 certified reference provenance entries.')
