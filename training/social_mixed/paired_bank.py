import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'examples/social_mixed/paired_bank_v1'
def load(split='train'):
 manifest=json.loads((PATH/'manifest.json').read_text());payload=(PATH/'tasks.jsonl').read_bytes()
 if hashlib.sha256(payload).hexdigest()!=manifest['tasks_sha256']:raise ValueError('Paired bank checksum mismatch')
 rows=[json.loads(l) for l in payload.splitlines()]
 return [r for r in rows if r['split']==split]


def development_panel():
    from collections import defaultdict
    groups=defaultdict(list)
    for task in sorted(load('validation'),key=lambda t:t['canonical_id']):
        if task['paired_view']=='O':groups[(task['kernel'],task['completion_mode'])].append(task)
    panel=[]
    while len(panel)<24 and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(panel)<24:panel.append(groups[key].pop(0))
    return panel
