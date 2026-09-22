import gzip,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'new/training_chain_evidence_20260921/old_bp/validation'
OUT=Path(__file__).resolve().parent

def read(p):return json.loads(gzip.decompress(p.read_bytes()))
def valid(r):return r['score']['status']=='ok' and r['completion']['finish_reason']!='length'
reports=[]
for step in range(0,201,10):
    p=SOURCE/f'{"860494" if step<=100 else "861241"}-step-{step}.json.gz'
    d=read(p);rows={r['task']['id']:r for r in d['bp_calls']}
    reports.append((step,d,rows,p))
base=reports[0][2];assert len(base)==45
for _,d,rs,_ in reports:
    assert set(rs)==set(base)
    for k,r in rs.items():
        assert r['prompt_ids']==base[k]['prompt_ids'],(k,'changed tokens')
        assert r['task']['teacher']==base[k]['task']['teacher'],(k,'changed teacher')
summary=[];changes=[]
for idx,(step,d,rs,p) in enumerate(reports):
    row=dict(completed_updates=step,optimizer_step=d['optimizer_step'],
             B_correct=sum(r['score']['correct'] for r in rs.values() if r['task']['task']=='B'),
             P_correct=sum(r['score']['correct'] for r in rs.values() if r['task']['task']=='P'),
             invalid=sum(not valid(r) for r in rs.values()),
             explicit_request_temperatures=sorted({str(r['request'].get('temperature','unspecified')) for r in rs.values()}))
    if idx:
        prev=reports[idx-1][2]
        lost=[k for k in rs if prev[k]['score']['correct'] and not rs[k]['score']['correct']]
        gained=[k for k in rs if not prev[k]['score']['correct'] and rs[k]['score']['correct']]
        recovered=[k for k in lost if any(later[2][k]['score']['correct'] for later in reports[idx+1:])]
        row.update(lost=len(lost),gained=len(gained),legal_losses=sum(valid(rs[k]) for k in lost),later_recovered=len(recovered))
        changes.append(dict(from_updates=reports[idx-1][0],to_updates=step,lost=lost,gained=gained,later_recovered=recovered))
    summary.append(row)
output=dict(identity='860494 through checkpoint99, then resumed861241; completed_updates=optimizer_step+1 except Q0',
    same_prompt_tokens_and_teacher_all_points=True,points=summary,transitions=changes,
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for _,_,_,p in reports})
(OUT/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(summary,indent=2))
