from pathlib import Path
from collections import Counter
import hashlib,json
from examples.final_evaluation.calbench_local import verify_source
from examples.final_evaluation.calbench_stage_context import stage_context
verify_source()
from calendar_game.prompts import build_turn_message,build_system_prompt
root=Path(__file__).resolve().parents[5];base=root/'examples/final_evaluation/calbench_diagnostic_data/20261102/v11_minimal';dest=root/'examples/strategic_slices/versions/general_ms_calbench_v12_inbox_20261102/validation';dest.mkdir(exist_ok=True)
inputs={};rows=[];counts={}
for run in sorted(p for p in base.iterdir() if (p/'games').is_dir()):
 count=Counter()
 for p in sorted((run/'games').glob('*/events.jsonl')):
  inputs[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
  for event in map(json.loads,p.read_text().splitlines()):
   if event['type']!='turn_start':continue
   e=event['data'];inbox=e.get('inbox_drained',[])
   if not inbox or not e.get('prompt_sent','').startswith('=== ROUND '):continue
   # Event preview contains round builder only. Mirror the pinned native client's
   # explicit first-turn composition, using the independently logged inbox.
   raw=e['prompt_sent']+'\n\n'+build_turn_message(inbox,e['turn'],4,'dm')
   system=build_system_prompt(dict(num_agents=4,num_slots=8,agent_id=e['agent_id'],all_agent_ids=[0,1,2,3],decision_retries=1,communication_protocol='dm'))
   native=[dict(role='system',content=system),dict(role='user',content=raw)]
   c=stage_context(native)
   for msg in inbox:
    assert msg['content'] in c.messages[-1]['content']
    assert msg['content'] not in c.action_instructions
    assert f"from Agent {msg['from']} (meeting {msg['meeting_id']})" in c.messages[-1]['content']
   following=native+[dict(role='assistant',content='{"thinking":"fixture","actions":[]}'),dict(role='user',content=build_turn_message([],e['turn']+1,4,'dm'))]
   later=stage_context(following)
   assert all(m['content'] in later.messages[1]['content'] for m in inbox)
   count['first_turn_inboxes']+=1;count['messages_preserved_before_MS']+=len(inbox);count['messages_retained_in_later_MS_history']+=len(inbox)
   rows.append(dict(run=run.name,case=p.parent.name,round=e['round'],turn=e['turn'],agent=e['agent_id'],message_count=len(inbox),MS_inbox_preserved=True,later_history_preserved=True,action_directives_exclude_inbox=True))
 counts[run.name]=dict(count)
out=dict(scope='Offline adapter replay of all logged first-turn inbox events, including cases later aborted; original native round preview + native turn builder with independently logged delivered inbox. No new model outputs or scores.',turn_limit=4,counts=counts,checks=rows,input_events_sha256=inputs)
(dest/'real_inbox_replay.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(counts))
