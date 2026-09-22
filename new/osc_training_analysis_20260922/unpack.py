import tarfile,io,json,hashlib
from pathlib import Path
src=Path('new/osc_training_evidence_20260922');out=Path('/tmp/osc-evidence');out.mkdir(exist_ok=True)
index=[]
for kind in ('training','calbench'):
 expected={line.split()[1]:line.split()[0] for line in (src/kind/'ARCHIVES.sha256').read_text().splitlines()}
 for arm in ('outcome','selfplay','conditioned'):
  parts=sorted((src/kind).glob(arm+'.tar.gz.part-*')) or [src/kind/(arm+'.tar.gz')]
  payload=b''.join(p.read_bytes() for p in parts)
  assert hashlib.sha256(payload).hexdigest()==expected[arm+'.tar.gz']
  with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as tf:
   members=[]
   for m in tf:
    if not m.isfile():continue
    members.append(dict(name=m.name,size=m.size))
    selected=(kind=='training' and not any('/'+x+'/' in '/'+m.name for x in ['calls','units','games'])) or (kind=='calbench' and m.name.endswith('.json'))
    if selected:
     p=out/kind/arm/m.name
     if not p.resolve().is_relative_to(out.resolve()):raise ValueError(m.name)
     p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(tf.extractfile(m).read())
  index.append(dict(kind=kind,arm=arm,sha256=expected[arm+'.tar.gz'],members=members))
  print(kind,arm,len(members),flush=True)
Path('new/osc_training_analysis_20260922/archive_index.json').write_text(json.dumps(index,indent=2))
