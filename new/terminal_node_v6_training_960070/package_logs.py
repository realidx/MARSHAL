"""Archive original job 960070 evidence without model/optimizer tensors."""
import hashlib,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEST=Path(__file__).resolve().parent
SOURCE=Path('/home/e/e1300530/tmp/terminal-node-v6-qwen3-4b-instruct-single96-full-20261016T145337Z')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 raw=DEST/'raw';raw.mkdir(exist_ok=True)
 files=[];excluded=[]
 for f in sorted(SOURCE.rglob('*')):
  if not f.is_file():continue
  rel=f.relative_to(SOURCE)
  if 'checkpoints' in rel.parts and (f.suffix in ('.distcp','.pt','.pth') or f.name=='.metadata'):
   excluded.append(dict(path=str(rel),size=f.stat().st_size));continue
  files.append((f,'run/'+rel.as_posix()))
 stdout=ROOT/'slurm-terminal-node-v6-single96-960070.out'
 if stdout.exists():files.append((stdout,'scheduler/'+stdout.name))
 snapshot=DEST/'scheduler_status.txt'
 with snapshot.open('w') as out:
  subprocess.run(['sacct','-j','960070','--format=JobID,JobName%35,State,Elapsed,ExitCode,NodeList','-P'],stdout=out,check=True)
 files.append((snapshot,'scheduler/'+snapshot.name))
 archive=raw/'training-960070.tar.gz'
 manifest=dict(source=str(SOURCE),files=[],excluded_checkpoint_tensors=excluded)
 with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
  for f,name in files:
   entry=dict(path=name,source=str(f),size=f.stat().st_size,sha256=sha(f))
   tar.add(f,arcname=name,recursive=False);manifest['files'].append(entry)
 print('ARCHIVE',archive.stat().st_size,flush=True)
 parts=[]
 with archive.open('rb') as src:
  i=0
  while chunk:=src.read(32*1024**2):
   part=raw/(archive.name+f'.part{i:03d}');part.write_bytes(chunk)
   parts.append(dict(path=part.name,size=len(chunk),sha256=sha(part)));i+=1
 manifest['archive']=dict(name=archive.name,sha256=sha(archive),size=archive.stat().st_size,parts=parts)
 (raw/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
 with tarfile.open(archive,'r:gz') as tar:
  entries={e['path']:e for e in manifest['files']}
  for member in tar:
   h=hashlib.sha256();f=tar.extractfile(member)
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
   assert h.hexdigest()==entries.pop(member.name)['sha256'],member.name
  assert not entries
 archive.unlink()
 print('VERIFIED',len(files),'files',len(parts),'parts',flush=True)
if __name__=='__main__':main()
