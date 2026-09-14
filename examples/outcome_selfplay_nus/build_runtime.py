"""Build v3 from frozen v2 plus reviewed display/rollout sources only."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def build():
    old=HERE/'runtime_v2.tar.gz'
    assert hashlib.sha256(old.read_bytes()).hexdigest()==(HERE/'runtime_v2.sha256').read_text().split()[0]
    with tarfile.open(old) as tar:
        files={m.name:tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    prefix='outcome_rollout_runtime/'
    for name in ('rollout.py','selfplay_prompt.py','bp_display.py'):
        files[prefix+'runs/outcome_selfplay_screen/'+name]=(HERE/name).read_bytes()
    manifest=json.loads(files[prefix+'runtime_manifest.json'])
    manifest.update(version='outcome-rollout-runtime-v3',base_archive_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),prompt_version='outcome-readable-prompt-v3')
    manifest['files']={name[len(prefix):]:hashlib.sha256(data).hexdigest() for name,data in files.items() if name!=prefix+'runtime_manifest.json'}
    manifest['python_sources']=sum(name.endswith('.py') for name in files)
    files[prefix+'runtime_manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    out=HERE/'runtime_v3.tar.gz'
    with out.open('wb') as raw, gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as gz, tarfile.open(fileobj=gz,mode='w') as tar:
        for name,data in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
            tar.addfile(info,io.BytesIO(data))
    (HERE/'runtime_v3.sha256').write_text(hashlib.sha256(out.read_bytes()).hexdigest()+'  runtime_v3.tar.gz\n')
    print(out)

if __name__=='__main__':build()
