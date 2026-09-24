"""Check the actual opt-in bank, including sampled live multi-step prompts."""
import argparse,json,random
from pathlib import Path
from training.social_mixed.interaction_bank import load
from training.social_mixed.interaction_training import static_request
from training.social_mixed.short_interaction import ShortInteraction,decision_request

def main():
 p=argparse.ArgumentParser();p.add_argument('--tokenizer');p.add_argument('--output',required=True);a=p.parse_args()
 tasks,sha=load();tok=None
 if a.tokenizer:
  from transformers import AutoTokenizer
  tok=AutoTokenizer.from_pretrained(a.tokenizer,local_files_only=True)
 lengths=[]
 def check(req):
  if tok:
   ids=tok.apply_chat_template(req['messages'],tools=req['tools'],tokenize=True,add_generation_prompt=True)
   lengths.append(len(ids))
   if len(ids)+1024>4096:raise ValueError(f'Actual interaction prompt exceeds training context: {len(ids)}+1024 > 4096')
 for task in tasks:
  if task.get('training_mode')!='short_interaction':check(static_request(task))
 decisions=0
 for task in tasks:
  if task.get('training_mode')!='short_interaction':continue
  env=ShortInteraction(task,seconds=10,max_nodes=30000,max_sweeps=128)
  for seed in range(8):
   rng=random.Random(seed)
   def agent(inp):
    nonlocal decisions
    decisions+=1;check(decision_request(inp));return rng.choice(inp['legal_actions'])
   result=env.rollout(agent,seed);assert result['status']=='terminal'
 report=dict(bank_sha256=sha,tasks=len(tasks),short_trajectories=800,live_decisions=decisions,
  tokenizer_checked=tok is not None,max_sampled_prompt_tokens=max(lengths,default=None),
  limitation='Sampled live paths; runtime length checking remains mandatory.')
 Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
