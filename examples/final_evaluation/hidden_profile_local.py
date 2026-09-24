"""Run unchanged native Hidden Profile baseline against a local model endpoint.
Default: prepare configs and validate only. --run starts the experiment.
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
from examples.final_evaluation.shapefactory_lite import UPSTREAM, SOURCE, verify_source, differences


def config(model,base_url):
    base=yaml.safe_load((UPSTREAM/'configs/study_conditions/hidden_profile/baseline.yml').read_text())
    result=deepcopy(base)
    for a in result['agents']:
        a['model'].update(provider='litellm',name=model if model.startswith('openai/') else 'openai/'+model,
                          api_base=base_url)
    return base,result


def prepare(output,model,base_url,repeats=1,checkpoint_id=None):
    if repeats<1:raise ValueError('repeats must be positive')
    source=verify_source();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    jobs=[]
    for repeat in range(repeats):
        base,cfg=config(model,base_url)
        name=f'hidden-profile-{repeat:02d}'
        cfg['logging']['output_dir']=str(output/name)
        path=output/(name+'.yml');path.write_text(yaml.safe_dump(cfg,sort_keys=False))
        code='from src.config.loader import load_experiment_config; from src.config.schema import validate_config_schema; import sys; validate_config_schema(load_experiment_config(sys.argv[1]))'
        subprocess.run([sys.executable,'-c',code,str(path)],cwd=UPSTREAM,check=True)
        jobs.append(dict(id=name,config=str(path),output=str(output/name),changes=differences(base,cfg)))
    manifest=dict(version='hidden-profile-native-local-v1',upstream_commit=source['commit'],
        upstream_manifest_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        checkpoint_id=checkpoint_id,checkpoint_identity_verified=False,
        all_seats_same_model=True,temperature=0.2,seed=42,
        native_rules_prompts_materials_roles_probes_unchanged=True,
        repetitions_are_not_independent_task_instances=True,jobs=jobs)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return jobs


def execute(output,jobs):
    output=Path(output).resolve();env=os.environ.copy()
    # Refuse hidden configuration overrides; secrets stay in the process environment.
    for key in ('COLLABSIM_MODEL_PROVIDER','COLLABSIM_MODEL_NAME','COLLABSIM_MODEL_TEMPERATURE'):
        if env.get(key):raise ValueError('Unset '+key+'; use explicit model configuration')
    env.setdefault('LITELLM_API_KEY','EMPTY')
    for job in jobs:
        with (output/(job['id']+'.log')).open('w') as log:
            result=subprocess.run([sys.executable,'-m','src.cli',job['config'],'--run-id',job['id'],
                '--output-dir',job['output']],cwd=UPSTREAM,env=env,stdout=log,stderr=subprocess.STDOUT)
        (output/(job['id']+'.exit_code')).write_text(str(result.returncode)+'\n')
        if result.returncode:raise RuntimeError('Native run failed; see '+str(output/(job['id']+'.log')))
    (output/'COMPLETE').write_text('Native CLI completed; not a task-success label.\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',required=True)
    p.add_argument('--base-url',required=True,help='OpenAI-compatible endpoint including /v1')
    p.add_argument('--checkpoint-id',help='Provenance label/hash supplied by operator; not remotely verified')
    p.add_argument('--repeats',type=int,default=1)
    p.add_argument('--run',action='store_true')
    a=p.parse_args()
    if a.repeats<1:p.error('--repeats must be positive')
    jobs=prepare(a.output,a.model,a.base_url,a.repeats,a.checkpoint_id)
    if a.run:execute(a.output,jobs)
    else:print(f'Prepared {len(jobs)} native baseline runs; no model calls. Use --run with a fresh output directory to execute.')

if __name__=='__main__':main()
