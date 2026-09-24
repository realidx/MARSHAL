"""Verify and run the frozen native CollabSim diagnostic suite."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from examples.final_evaluation.shapefactory_lite import ROOT,verify_source,config as sf_config
from examples.final_evaluation.hidden_profile_local import config as hp_config
FROZEN=ROOT/'examples/final_evaluation/collabsim_frozen_v1'
def templates():
 configs={}
 for swapped in (False,True):
  for condition in ('private','dashboard'):
   _,cfg=sf_config(condition,swapped,'FROZEN_MODEL','http://FROZEN_ENDPOINT/v1')
   cfg['logging']['output_dir']='FROZEN_OUTPUT';configs[cfg['experiment']['id']]=cfg
 _,cfg=hp_config('FROZEN_MODEL','http://FROZEN_ENDPOINT/v1');cfg['logging']['output_dir']='FROZEN_OUTPUT'
 configs['hidden-profile']=cfg
 return configs

def verify():
 source=verify_source();manifest=json.loads((FROZEN/'manifest.json').read_text())
 for path,expected in manifest['files'].items():
  if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:raise ValueError('Frozen dependency changed: '+path)
 if source['commit']!=manifest['upstream_commit']:raise ValueError('Upstream version changed')
 if templates()!=json.loads((FROZEN/'templates.json').read_text()):raise ValueError('Native effective configuration changed')
 return manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true')
 p.add_argument('--model');p.add_argument('--base-url');p.add_argument('--checkpoint-id');p.add_argument('--output',type=Path)
 p.add_argument('--run',action='store_true');a=p.parse_args();manifest=verify()
 if a.verify and not a.output:print('Frozen CollabSim configuration verified');return
 if not all((a.model,a.base_url,a.checkpoint_id,a.output)):p.error('Require model, base-url, checkpoint-id and output')
 if any(k.startswith('COLLABSIM_MODEL_') and v for k,v in os.environ.items()):raise ValueError('Unset COLLABSIM_MODEL_* overrides')
 a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
 receipt=dict(protocol=manifest['version'],manifest_sha256=hashlib.sha256((FROZEN/'manifest.json').read_bytes()).hexdigest(),
  checkpoint_id=a.checkpoint_id,checkpoint_identity_verified=False,model=a.model,base_url=a.base_url,
  serving_requirements=manifest['serving_requirements'],serving_configuration_verified=False,run_requested=a.run)
 (a.output/'protocol.json').write_text(json.dumps(receipt,indent=2)+'\n')
 for module,name,extra in [('shapefactory_lite','shapefactory',[]),('hidden_profile_local','hidden_profile',['--repeats','3','--checkpoint-id',a.checkpoint_id])]:
  args=[sys.executable,'-m','examples.final_evaluation.'+module,'--model',a.model,'--base-url',a.base_url,'--output',str(a.output/name),*extra]
  if a.run:args.append('--run')
  subprocess.run(args,cwd=ROOT,check=True)
 if a.run:(a.output/'COMPLETE').write_text('Native CLI runs completed; not a task success or transport health certificate.\n')
 else:(a.output/'PREPARED').write_text('Seven runs configured and schema-validated; no model calls.\n')
if __name__=='__main__':main()
