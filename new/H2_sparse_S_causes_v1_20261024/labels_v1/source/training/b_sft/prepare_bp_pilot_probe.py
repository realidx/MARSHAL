"""Freeze only train/validation visible inputs for the existing SoC probe env."""
import hashlib
import json
from pathlib import Path
from training.b_sft.social_bp_grpo import read, validate_tasks, sha
from training.b_sft.social_named_probe import request


def main():
    source = Path('examples/social_bp/data'); out = Path('examples/bp_pilot_probe_nus/bundle')
    tasks = read(source/'tasks.jsonl'); validate_tasks(tasks)
    audit = json.loads((source/'solver_audit.json').read_text())
    assert audit['tasks_sha256'] == sha(source/'tasks.jsonl')
    out.mkdir(parents=True,exist_ok=True)
    stages = []
    for split,n,count in (('train',8,256),('validation',4,64)):
        rows=[]
        for t in tasks:
            if t['split']!=split: continue
            req=request(t,'action_tools',t['name_variant'])
            req.update(temperature=.8,top_p=1.,top_k=-1,repetition_penalty=1.)
            rows.append(dict(task_id=t['id'],task=t['task'],split=split,pool=t['pool'],stage=t['stage'],output_arm='action_tools',request=req))
        assert len(rows)==count
        path=out/f'{split}_requests.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        stages.append(dict(name=split,requests=path.name,conditions=count,group_size=n,formal_requests=count*n))
    sampler=Path('examples/bp_probe_nus/bundle/remote_bp_probe.py')
    (out/sampler.name).write_bytes(sampler.read_bytes())
    manifest=dict(version='bp-pilot-baseline-v1',stages=stages,formal_requests=2304,preflight_requests=2,
                  source_tasks_sha256=sha(source/'tasks.jsonl'),template_sha256=audit['summary']['tokenizer']['template_sha256'],
                  files={name:sha(out/name) for name in ('train_requests.jsonl','validation_requests.jsonl','remote_bp_probe.py')})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
