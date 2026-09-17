"""Filter the reviewed v2 pack by actual goal rules; preserve labels and splits."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from training.b_sft.social_named_probe import request
from training.social_mixed.scoring_scope import ALLOWED_MODES, completion_mode, validate_rows
from training.social_mixed.structure_coverage import audit
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/social_mixed/data_distribution_v2'
OUT=ROOT/'examples/social_mixed/data_binary_linear_v3'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return [json.loads(l) for l in path.read_text().splitlines()]


def main():
    if OUT.exists():raise ValueError('Refusing to overwrite released pack')
    parent=json.loads((SOURCE/'manifest.json').read_text())
    for name,record in parent['files'].items():
        if sha(SOURCE/name)!=record['sha256']:raise ValueError('Parent artifact changed: '+name)
    OUT.mkdir()
    manifest=deepcopy(parent)
    for key in ('expansion_errors','candidate_freeze_sha256','expansion_source_sha256','coverage','counts','files','errors'):
        manifest.pop(key,None)
    manifest.update(dataset_version='binary-linear-v3',parent_manifest_sha256=sha(SOURCE/'manifest.json'),
                    allowed_completion_modes=list(ALLOWED_MODES),model_calls=0,files={},removals={},
                    transformation='Remove heterogeneous goal-completion games; retained records, labels and splits unchanged')
    packs={}
    for name in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation','selfplay_test','diagnostics'):
        path=SOURCE/(name+'.jsonl')
        if not path.exists():continue
        before=read(path);rows=[t for t in before if completion_mode(t) in ALLOWED_MODES]
        validate_rows(rows,name);packs[name]=rows
        manifest['removals'][name]=dict(before=len(before),removed=len(before)-len(rows),after=len(rows))
    def write(name,rows):
        path=OUT/name;path.write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
        manifest['files'][name]=dict(count=len(rows),sha256=sha(path))
    for name,rows in packs.items():write(name+'.jsonl',rows)
    for split in ('train','validation','test'):
        write('requests_'+split+'.jsonl',[dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in packs['bp_'+split]])
    ids={t['id'] for t in packs['bp_train']+packs['diagnostics']}
    links=[r for r in json.loads((SOURCE/'p4_links.json').read_text()) if r['mode'] in ALLOWED_MODES]
    for r in links:
        if not {r['parent'],*r['children'],*r['diagnostic_children']}<=ids:raise ValueError('Dangling P4 link')
    (OUT/'p4_links.json').write_text(json.dumps(links,indent=2)+'\n')
    report=audit(OUT)
    if report['cross_split_families']:raise ValueError('Split geometry overlap')
    (OUT/'structure_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest['artifact_hashes']={n:sha(OUT/n) for n in ('p4_links.json','structure_audit.json')}
    manifest['coverage']=report['counts']
    manifest['counts']={s:dict(Counter(t['kernel'] for t in packs['bp_'+s])) for s in ('train','validation','test')}
    manifest['mode_counts']={name:dict(Counter(completion_mode(t) for t in rows)) for name,rows in packs.items()}
    manifest['prompt_sources']['training/social_mixed/scoring_scope.py']=sha(ROOT/'training/social_mixed/scoring_scope.py')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(removals=manifest['removals'],mode_counts=manifest['mode_counts']),indent=2))

if __name__=='__main__':main()
