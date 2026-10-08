"""Archive the original local experiment evidence without rewriting its contents."""
import hashlib,json,tarfile,shutil
from pathlib import Path
BASE=Path('/home/e/e1300530/tmp')
REPO=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'raw'
OUT.mkdir(exist_ok=True)
manifest=[]
def pack(name,sources):
 archive=OUT/(name+'.tar.gz')
 entries=[]
 with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
  for source,arc in sources:
   source=Path(source)
   assert source.exists(),source
   paths=sorted(source.rglob('*')) if source.is_dir() else [source]
   for path in paths:
    if path.is_file() and not path.is_symlink():
     relative=(Path(arc)/path.relative_to(source)) if source.is_dir() else Path(arc)
     h=hashlib.sha256()
     with path.open('rb') as handle:
      for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
     entries.append(dict(path=str(relative),source=str(path),bytes=path.stat().st_size,sha256=h.hexdigest()))
   tar.add(source,arcname=arc,recursive=True)
 size=archive.stat().st_size
 if size>48*1024*1024:
  parts=[]
  with archive.open('rb') as handle:
   index=0
   while block:=handle.read(32*1024*1024):
    part=OUT/(archive.name+f'.part{index:03d}');part.write_bytes(block);parts.append(part);index+=1
  archive.unlink()
 else:parts=[archive]
 manifest.append(dict(name=name,files=entries,archives=[dict(path=part.name,bytes=part.stat().st_size,sha256=hashlib.sha256(part.read_bytes()).hexdigest()) for part in parts]))
 print(name,len(entries),'files',size,'compressed bytes',flush=True)
for label,job in [('best',919181),('latest',919182)]:
 root=BASE/f'terminal-test-{label}-{job}'
 pack('terminal-'+label,[(root,root.name),(Path(str(root)+'.log'),root.name+'.log'),(Path(str(root)+'.EXIT_CODE'),root.name+'.EXIT_CODE'),(Path(str(root)+'.server'),root.name+'.server')])
 root=BASE/f'terminal-calbench-{label}-{job}'
 pack('calbench-'+label,[(root,root.name)])
root=BASE/'terminal-train-qwen3-4b-instruct-single96-full-20261006'
pack('training-915731',[(p,root.name+'/'+p.name) for p in sorted(root.iterdir()) if p.name!='checkpoints'])
pack('frozen-terminal-data',[(REPO/'new/local_data'/name,'new/local_data/'+name) for name in ['strategic_slices_oracle_consistent_candidates_v4','strategic_slices_terminal_selected_v4']])
pack('calbench-source',[(REPO/'third_party/calbench','third_party/calbench')])
pack('export-logs',[(BASE/f'export-terminal-hf-{job}.{suffix}',f'export-terminal-hf-{job}.{suffix}') for job in [919151,919152] for suffix in ['out','err']])
(OUT/'MANIFEST.json').write_text(json.dumps(dict(schema=1,excluded='Native checkpoint tensor/optimizer files and HF weight shards remain local; model identities and checkpoint provenance are included.',bundles=manifest),indent=2)+'\n')
