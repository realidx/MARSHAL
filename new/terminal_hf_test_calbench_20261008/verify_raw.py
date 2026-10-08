"""Verify archive parts and every archived original file against the manifest."""
import hashlib,json,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'raw'
def digest(handle):
 h=hashlib.sha256()
 for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
manifest=json.loads((ROOT/'MANIFEST.json').read_text());total=0
for bundle in manifest['bundles']:
 expected={f['path']:f for f in bundle['files']};seen=set()
 with tempfile.TemporaryFile() as assembled:
  for part in bundle['archives']:
   path=ROOT/part['path'];assert path.stat().st_size==part['bytes'],path
   with path.open('rb') as handle:assert digest(handle)==part['sha256'],path
   with path.open('rb') as handle:
    for block in iter(lambda:handle.read(1024*1024),b''):assembled.write(block)
  assembled.seek(0)
  with tarfile.open(fileobj=assembled,mode='r|gz') as archive:
   for member in archive:
    if member.isdir():continue
    assert member.isfile(),'Unexpected non-regular member: '+member.name
    assert member.name in expected and member.name not in seen,member.name
    entry=expected[member.name];assert member.size==entry['bytes'],member.name
    assert digest(archive.extractfile(member))==entry['sha256'],member.name
    seen.add(member.name)
 assert seen==set(expected),bundle['name']
 total+=len(seen);print(bundle['name'],len(seen),'original files verified',flush=True)
print('VERIFIED',total,'original files across',len(manifest['bundles']),'bundles')
