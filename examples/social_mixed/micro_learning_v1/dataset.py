"""Explicit loader for the isolated micro experiment, not the O/C/D bank."""
import hashlib,json,os
from copy import deepcopy
from pathlib import Path
NAME=os.environ.get('SOCIAL_MICRO_VARIANT','13')
if NAME not in ('13','24','24v2','24v2_no_b','24v1_o','24v1_c','24v1_d'):raise ValueError('Unknown micro variant')
ROOT=Path(__file__).parent if NAME=='13' else Path(__file__).parent.parent/('micro_learning_24_v2' if NAME.startswith('24v2') else 'micro_learning_24_v1')
if NAME.startswith('24v1_'):ROOT=Path(__file__).parent.parent/'micro_learning_24_v1_matched'
KINDS={'24v1_o':('O',),'24v1_c':('O','P')}.get(NAME,('O','P','B') if NAME!='24v2_no_b' else ('O','P'))
NO_B='B' not in KINDS
FROZEN_LR=NAME.startswith(('24v1_','24v2'))

def row_weight():
 # The objective averages rows: (2/3)/64 == 1/96 for shared O/P.
 return len(KINDS)/3

def scheduled_learning_rate(update):
 if not FROZEN_LR:return None
 return json.loads((ROOT/'schedule.jsonl').read_text().splitlines()[update])['learning_rate']

def load():
 manifest=json.loads((ROOT/'manifest.json').read_text())
 for name,digest in manifest['sha256'].items():
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Micro dataset hash mismatch: '+name)
 return [json.loads(l) for l in (ROOT/'tasks.jsonl').read_text().splitlines()]

def batch(update,seed=42):
 if not 0<=update<40:raise ValueError('Micro pilot supports updates 0..39')
 by_id={r['id']:r for r in load()}
 plan=json.loads((ROOT/'schedule.jsonl').read_text().splitlines()[update])
 rows=[by_id[tid] for tid in plan['task_ids'] if by_id[tid]['evidence']['kind'] in KINDS];result=[]
 for row in rows:
  for replica in range(8):
   request=deepcopy(row['request'])
   request['seed']=int(hashlib.sha256(f'{seed}:{update}:{row["id"]}:{replica}'.encode()).hexdigest()[:8],16)
   result.append(dict(task_id=row['id'],group=f'{update}:{row["id"]}',replica=replica,request=request))
 return result

def score(task_id,completion):
 from training.b_sft.social_bp_training import reward
 row=next(r for r in load() if r['id']==task_id)
 return reward(row['task'],completion)
