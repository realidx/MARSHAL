"""Small native CollabSim configuration, without editing upstream rules or prompts.
By default prepare and validate offline. --run explicitly starts native experiments.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path(__file__).resolve().parents[2]
UPSTREAM=ROOT/'third_party/CollabSim'
SOURCE=ROOT/'third_party/CollabSim.source.json'


def verify_source():
    manifest=json.loads(SOURCE.read_text())
    for name,expected in manifest['files'].items():
        if hashlib.sha256((UPSTREAM/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Upstream file changed: '+name)
    return manifest


def config(condition,swapped,model,base_url):
    name={'private':'baseline','dashboard':'awareness_dashboard'}[condition]
    base=yaml.safe_load((UPSTREAM/f'configs/study_conditions/shapefactory/{name}.yml').read_text())
    out=deepcopy(base)
    out['experiment']['id']='native-lite-'+('square-circle' if swapped else 'circle-square')+'-'+condition
    out['agents']=out['agents'][:2]
    for a in out['agents']:
        a['model'].update(provider='litellm',name=model if model.startswith('openai/') else 'openai/'+model,api_base=base_url)
    out['task'].update(shapes_order=1,shapes_types=2,shape_options=['circle','square'] if swapped else ['square','circle'],
        specialties={'A':'square' if swapped else 'circle','B':'circle' if swapped else 'square'})
    # Preserve native timing, concurrency cap, probes, persona and visibility settings.
    return base,out


def differences(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        return [d for k in sorted(a.keys()|b.keys()) for d in differences(a.get(k),b.get(k),path+'.'+k)]
    return [] if a==b else [dict(path=path.lstrip('.'),before=a,after=b)]


def prepare(output,model,base_url):
    source=verify_source();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    jobs=[]
    for swapped in (False,True):
        for condition in ('private','dashboard'):
            base,cfg=config(condition,swapped,model,base_url)
            name=cfg['experiment']['id'];folder=output/name
            cfg['logging']['output_dir']=str(folder)
            path=output/(name+'.yml');path.write_text(yaml.safe_dump(cfg,sort_keys=False))
            # Validate using the actual upstream schema without importing model backends.
            code='from src.config.loader import load_experiment_config; from src.config.schema import validate_config_schema; import sys; validate_config_schema(load_experiment_config(sys.argv[1]))'
            subprocess.run([sys.executable,'-c',code,str(path)],cwd=UPSTREAM,check=True)
            jobs.append(dict(id=name,config=str(path),output=str(folder),changes=differences(base,cfg)))
    manifest=dict(version='shapefactory-lite-native-v1',upstream_commit=source['commit'],
        upstream_manifest_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        all_agents_same_model=True,prompts_and_native_source_unchanged=True,
        note='Small-scale diagnostic, not the paper baseline or previous fixed-clock Lite. Native 900s wall-clock and probes retained.',jobs=jobs)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return jobs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',required=True,help='Model served by the local OpenAI-compatible endpoint')
    p.add_argument('--base-url',required=True,help='For example http://127.0.0.1:8000/v1')
    p.add_argument('--run',action='store_true',help='Run four native 900-second sessions sequentially')
    a=p.parse_args();jobs=prepare(a.output,a.model,a.base_url)
    if not a.run:
        print(f'Prepared {len(jobs)} configs; no model calls. Add --run with a fresh output directory to execute.');return
    env=os.environ.copy();env.setdefault('LITELLM_API_KEY','EMPTY')
    for job in jobs:
        with (a.output/(job['id']+'.log')).open('w') as log:
            result=subprocess.run([sys.executable,'-m','src.cli',job['config'],'--run-id',job['id'],
                '--output-dir',job['output']],cwd=UPSTREAM,env=env,stdout=log,stderr=subprocess.STDOUT)
        (a.output/(job['id']+'.exit_code')).write_text(str(result.returncode)+'\n')
        from examples.final_evaluation.shapefactory_native_summary import summarize
        (a.output/'evaluation_summary.json').write_text(json.dumps(summarize(a.output),indent=2)+'\n')
        if result.returncode:raise SystemExit(result.returncode)
    (a.output/'COMPLETE').write_text('ok\n')

if __name__=='__main__':main()
