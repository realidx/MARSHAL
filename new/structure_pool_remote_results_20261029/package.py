"""Archive original remote runs, verification and resource evidence."""
import hashlib,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
BASE=Path('/home/e/e1300530/tmp/structure_pool_remote_20261029');DATA=BASE/'runtime/new/structure_pool_v1_20261026'
RUNS=['remote_remaining18_runtime_v4_20261029','remote_reload18_runtime_v4_20261029','remote_retry11_v1_20261029','remote_reload_retry11_v1_20261029']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def read(p):return json.loads(p.read_text())
def main():
 summary={}
 for name in RUNS:
  p=DATA/name;c=read(p/'COMPLETE.json');assert sha(p/'results.json')==c['results_sha256'];assert sha(p/'pipeline_snapshot.json')==c['pipeline_snapshot_sha256']
  rows=read(p/'results.json')
  for r in rows:
   if r.get('reference_path'):assert sha(p/r['reference_path'])==r['reference_sha256']
   if r.get('labels_sha256'):
    folder=p/Path(r['result_path']).parent;assert sha(folder/'labels.jsonl.gz')==r['labels_sha256'];assert sha(folder/'examples.json')==r['examples_sha256']
  summary[name]=dict(completion=c,rows=[{k:r.get(k) for k in ['index','arm','status','labels','reference_accepted','error','phase','elapsed_seconds','summary','reference_path','reference_sha256']} for r in rows])
 assert summary[RUNS[0]]['completion']['certified']==17
 assert summary[RUNS[1]]['completion']['independently_passed']==17
 assert summary[RUNS[2]]['completion']['unavailable']==[11]
 assert summary[RUNS[3]]['completion']['original_certified']==0
 (OUT/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 with (OUT/'SCHEDULER_ACCOUNTING.txt').open('w') as f:subprocess.run(['sacct','-j','1032520,1032528,1032536,1032547,1032578','--format=JobID,JobName%35,State,Elapsed,TotalCPU,AllocCPUS,MaxRSS,ExitCode,NodeList','-P'],stdout=f,check=True)
 folders=[DATA/name for name in RUNS]+[DATA/'remote_remaining18_20261029']+[BASE/name for name in ['preflight','preflight_runtime_v4','resources','resources_runtime_v3','resources_runtime_v4','resources_retry11_v1']]
 files=[]
 for d in folders:
  if d.exists():files.extend(f for f in d.rglob('*') if f.is_file() and '__pycache__' not in f.parts)
 files.extend(p for p in BASE.glob('slurm-*.out') if p.is_file())
 files.append(BASE/'RUNTIME_MANIFEST.json')
 for rel in ['new/structure_pool_v1_20261026/raw_v1/parents.jsonl','new/structure_pool_v1_20261026/raw_v1/manifest.json','new/structure_pool_v1_20261026/raw_v1/pipeline_snapshot.json','examples/strategic_slices/versions/structure_pool_v1_20261026/SNAPSHOT.json']:
  files.append(BASE/'runtime'/rel)
 files=sorted(set(files));archive=OUT/'results.tar.gz';manifest=[]
 with tarfile.open(archive,'w:gz',compresslevel=6) as t:
  for p in files:
   assert not p.is_symlink();rel=str(p.relative_to(BASE));manifest.append(dict(path=rel,size=p.stat().st_size,sha256=sha(p)));t.add(p,arcname=rel,recursive=False)
 (OUT/'MANIFEST.json').write_text(json.dumps(dict(source_root=str(BASE),files=manifest,archive=dict(name=archive.name,size=archive.stat().st_size,sha256=sha(archive)),excluded=['python312 Conda environment binaries; package builds recorded in conda-explicit.txt','generated __pycache__ bytecode']),indent=2)+'\n')
 print('ARCHIVED',len(files),'BYTES',archive.stat().st_size)
if __name__=='__main__':main()
