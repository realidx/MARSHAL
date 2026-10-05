import argparse,json,shutil
from pathlib import Path
from training.strategic_slices.terminal_d import load_dataset,load_config,make_protocol,ROOT
from training.strategic_slices.common import digest,file_hash,write_json
from training.strategic_slices.freeze import source_identity
p=argparse.ArgumentParser();p.add_argument('--old',type=Path,required=True);p.add_argument('--new',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
old=json.loads((a.old/'protocol.json').read_text());cfg=load_config();dataset=load_dataset(ROOT/cfg['data'])
assert old['config']['workers']==16 and cfg['workers']==32 and cfg['scheduler']=='completion-refill-v1'
assert {k:v for k,v in old['config'].items() if k!='workers'}=={k:v for k,v in cfg.items() if k not in ('workers','scheduler')}
new=make_protocol(dataset,cfg,old['model_identity'],sorted(dataset.parents))
assert {k:v for k,v in old.items() if k not in ('config','source_identity')}=={k:v for k,v in new.items() if k not in ('config','source_identity')}
assert old['model_identity']['launcher_sha256']==file_hash(ROOT/'examples/strategic_slices/run_terminal_d.py')
assert set(old['source_identity'])==set(new['source_identity'])
changed=[k for k in old['source_identity'] if old['source_identity'][k]!=new['source_identity'][k]]
assert changed==['training/strategic_slices/terminal_d.py'],changed
for name,sha in old['source_identity'].items():assert file_hash(a.old/'source'/name)==sha,name
inherited={}
for path in sorted((a.old/'parents').glob('*.json')):
    saved=json.loads(path.read_text());r=saved['result'];pid=path.stem
    assert digest(r)==saved['sha256'] and r['parent_id']==pid and r['protocol_sha256']==digest(old)
    rows=[r for r in dataset.candidates if r['parent_id']==pid]
    expected={(r['id'],i) for r in rows for i in range(cfg['replicas'])}
    assert len(r['games'])==64 and {(g['slice_id'],g['replica']) for g in r['games']}==expected
    inherited[path.name]=file_hash(path)
manifest=dict(version='terminal-D-execution-migration-v1',old_protocol=old,old_protocol_sha256=digest(old),new_protocol_sha256=digest(new),inherited_parents=inherited,changed_sources=changed,original_evaluation=str(a.old.resolve()),reason='User authorized workers 16 to 32 and completion refill; frozen statistical protocol unchanged.',caveat='Batch scheduling changes can change numerical outputs; inherited and new parents retain distinct protocol identities.')
if a.apply:
    assert not a.new.exists()
    a.new.mkdir(parents=True);(a.new/'parents').mkdir()
    for name in inherited:shutil.copy2(a.old/'parents'/name,a.new/'parents'/name);assert file_hash(a.new/'parents'/name)==inherited[name]
    shutil.copytree(a.old/'source',a.new/'legacy_source')
    for name in new['source_identity']:
        target=a.new/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    write_json(a.new/'protocol.json',new);write_json(a.new/'EXECUTION_MIGRATION.json',manifest)
print(json.dumps(dict(validated=True,applied=a.apply,reusable_parents=len(inherited),reusable_trajectories=len(inherited)*64,old_protocol_sha256=digest(old),new_protocol_sha256=digest(new))))
