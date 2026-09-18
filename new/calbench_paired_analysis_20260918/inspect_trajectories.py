import json,sys
from pathlib import Path
roots={
'q0':Path('runs/remote-results/calbench-three-model-results/runs/calbench-three-models-20260917-154659/q0'),
'marshal':Path('runs/remote-results/calbench-external-4096-results/runs/calbench-marshal-4096-20260917-170425'),
'socialr1':Path('runs/remote-results/calbench-external-4096-results/runs/calbench-socialr1-4096-20260917-174119'),
'bp':Path('runs/calbench_soc/bp-step139-formal-857442'),
'mixed':Path('runs/calbench_soc/mixed-step59-formal-857444'),
'sp':Path('runs/calbench_soc/selfplay-step69-formal-857446')}
def inspect(model,case):
 p=roots[model]/'games'/case
 print('\n###',model,case)
 s=json.loads((p/'scenario.json').read_text());print('CAL',s['calendars'])
 for i,line in enumerate((p/'events.jsonl').read_text().splitlines(),1):
  e=json.loads(line);d=e['data']
  if e['type'] in ('turn_end','decide_end','batch_rejected'):
   print('L',i,d.get('turn'),d.get('phase'),'agent',d.get('agent_id'),e['type'])
   print('THINK',str(d.get('thinking') or '')[:450]);print('ACTIONS',d.get('tool_calls') or d.get('conflict_description'))
if __name__=='__main__':
 for arg in sys.argv[1:]:inspect(*arg.split(':'))
