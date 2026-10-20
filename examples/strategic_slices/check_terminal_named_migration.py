"""Replay archived public contexts through the new renderer without a model/Oracle solve."""
from collections import Counter
import json
from pathlib import Path
import tarfile

from examples.strategic_slices.export_terminal_prompt_preview import rebuild,OUT
from training.social_mixed.frozen.bp_display import preference_facts
from training.strategic_slices.named_prompt import request,calls_for,visible
from training.strategic_slices.named_prompt_v7 import request as v7_request
from training.strategic_slices.common import decode,digest,file_hash


def main():
    if (OUT/'SNAPSHOT.json').exists():raise ValueError('Frozen evidence cannot be overwritten; create a new version')
    root=Path.cwd();archive=root/'new/terminal_node_v6_training_960070/raw/training-960070.tar.gz.part000'
    parents={r['id']:r['raw'] for r in map(json.loads,(root/'new/local_data/strategic_slices_oracle_consistent_candidates_v4/parents.jsonl').read_text().splitlines())}
    seen=set();counts=Counter();rows=[];novel_private=None
    with tarfile.open(archive,'r|gz') as tar:
        for member in tar:
            if not member.name.startswith('run/calls/') or int(Path(member.name).stem.split('-')[-1])>306:continue
            for line in tar.extractfile(member):
                c=json.loads(line);key=c['prompt_sha256']
                if key in seen:continue
                seen.add(key);v=json.loads(c['request']['messages'][-1]['content']);raw=parents[c['parent_id']]
                rules,node,world=rebuild(raw,v)
                native=[dict(index=i,action=a.to_dict()) for i,a in enumerate(rules.actions(node))]
                assert native==v['legal_actions'];assert node.state.public_state()==v['public_state']
                mapping=calls_for(rules,node)
                opts=dict(remaining_decisions=v['evaluation_window']['remaining_controlled_decisions'])
                req=request(rules,node,world,42,**opts);old=v7_request(rules,node,world,42,**opts)
                assert req['tools']==old['tools'];assert req['messages'][0]==old['messages'][0]
                _,shown,_=visible(rules,node,world[rules.actor(node)])
                expected={(f['player'],f['goal'],f['preference']) for f in preference_facts(shown)}
                text=req['messages'][1]['content']
                area=text.split('PUBLIC PREFERENCES\n',1)[1].split('BACKGROUND PREFERENCE DISTRIBUTION',1)[0]
                actual={tuple(x.strip() for x in line.strip('|').split('|')) for line in area.splitlines()
                    if line.startswith('|') and line.strip('|').split('|')[-1].strip() in ('want','neutral','avoid')}
                assert actual==expected
                counts['visible_fact_sets_identical']+=1
                allowed={(t['function']['name'],json.dumps(a,sort_keys=True)) for t in req['tools'] for a in t['function']['parameters']['enum']}
                assert len(allowed)==len(mapping)
                for i,(name,args) in enumerate(mapping):
                    assert (name,json.dumps(args,sort_keys=True)) in allowed
                    result=dict(completion=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))])))
                    assert decode(result,rules.actions(node),mapping)==(i,'ok')
                    counts['native_actions_roundtripped']+=1
                for hidden in ('root_Q','oracle_step','world_index','action_index','Who knows / source','PUBLIC PREFERENCE SUPPORT'):
                    assert hidden not in json.dumps(req)
                if v['private_results']:
                    counts['contexts_with_private_results']+=1
                    novel=any(g not in shown['public_preferences'].get(p,{}) for p,gs in shown['your_private_investigation_answers'].items() for g in gs)
                    if novel:
                        counts['contexts_with_nonpublic_investigation_answer']+=1
                        if novel_private is None:novel_private=dict(label='terminal_private_new_answer',raw=raw,visible=v)
                counts['response_contexts' if v['pending_offer'] else 'proposal_contexts']+=1
                rows.append(dict(old_prompt_sha256=key,new_request_sha256=digest(req),native_actions=len(mapping),task_id=c['task_id']))
    fixtures=OUT/'input_fixtures.json';cases=json.loads(fixtures.read_text())
    if novel_private and not any(c['label']==novel_private['label'] for c in cases):
        cases.append(novel_private);fixtures.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    report=dict(archive_sha256=file_hash(archive),unique_contexts=len(seen),counts=dict(counts),mismatches=0,
        model_called=False,gpu_tested=False,
        scope='Native menus/tool mappings/visible fact sets/system/tools; no re-solving Q or causal performance claim',contexts=rows)
    (OUT/'native_interface_migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='contexts'},indent=2))


if __name__=='__main__':main()
