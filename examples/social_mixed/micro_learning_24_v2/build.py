"""Freeze a reviewed 24-task bank and its matched no-B schedule. No model calls."""
import hashlib
import json
import tarfile
from pathlib import Path
from training.b_sft.social_bp_training import reward
from training.b_sft.social_named_probe import present, action_call, gold_answer
from training.social_mixed.stabilization import learning_rate

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent

def read(path):
    return [json.loads(l) for l in (ROOT/path).read_text().splitlines()]

def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()

def build():
    base = read('examples/social_mixed/micro_learning_24_v1/tasks.jsonl')
    paired = {t['id']: t for t in read('examples/social_mixed/paired_bank_v2/tasks.jsonl')}
    old = {t['id']: t for t in read('examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl')}
    audit = {}
    for cohort, name in [('old','old_BP_main'), ('paired','new_D')]:
        audit.update({(cohort,r['task_id']):r for r in read(f'new/task_learning_audit_20260924/{name}.jsonl')})
    # Four retained O and four replacements. Relations are checked below, not
    # inferred from names or the number of different labels.
    o_ids = ['e3126ec00963b34311ed-O','fdfe18407b6a6b382606-O',
             '3a799590f157770c74eb-O','1f64ed25993e73276ecf-O',
             'c119e0ae7c41f47b394c-O','5e9d1a1118542341eb39-O',
             'c446e23c1db418492227-O','55815e1977097e8344fc-O']
    b_choices = [
        ('paired','6723c813877e1f9c28c8-B','insufficient'),
        ('paired','ebeb09c155c1d096d5f2-B','insufficient'),
        ('old','c6be10e40e97777214f6','exclude'),
        ('old','a61c495e88207d9ff764','exclude'),
        ('old','f89382b9233063e37cc1','favored'),
        ('old','68798975a57a43ce9c11','favored'),
        ('paired','c119e0ae7c41f47b394c-B','revealed'),
        ('paired','55815e1977097e8344fc-B','revealed'),
    ]
    records = [r for r in base if r['evidence']['kind']=='P']
    specs = [('paired',tid,'O','action') for tid in o_ids] + [(c,t,'B',op) for c,t,op in b_choices]
    wanted = {}
    bad = {r['id'] for r in json.loads((ROOT/'new/dataset_redesign_20260924/b_prompt_contract.json').read_text())}
    for cohort, tid, kind, operation in specs:
        assert tid not in bad
        task = (old if cohort=='old' else paired)[tid]
        assert task['split']=='train'
        evidence = dict(audit.get((cohort,tid), {}),source_cohort=cohort,kind=kind)
        assert evidence.get('events'), ('No historical exposure',tid)
        if kind in ('B','O'):
            assert evidence['counts'].get('correct',0)>0
            assert sum(e['effective'] for e in evidence['events'])>=2
        wanted[tid] = dict(id=tid,task=task,evidence=evidence,operation=operation,
                           scorer='training.b_sft.social_bp_training.reward')
    archives = [
        'new/old_bp_full_training_calls_20260924/860494-steps-0-102.tar.gz',
        'new/old_bp_full_training_calls_20260924/861241-steps-100-205.tar.gz',
        'new/d_evidence_20260924/training/d0-72-874127.tar.gz',
        'new/d_evidence_20260924/training/d72-148-875169.tar.gz',
    ]
    examples = {}; checks=0
    for archive in archives:
        with tarfile.open(ROOT/archive) as tar:
            for member in tar:
                if 'calls/' not in member.name or '/step-' not in member.name or not member.name.endswith('.jsonl'): continue
                step=int(member.name.split('step-')[1].split('.')[0])
                if '860494' in archive and step>99: continue
                for line in tar.extractfile(member):
                    call=json.loads(line); tid=call['task_id']
                    if tid not in wanted: continue
                    row=wanted[tid]; req=dict(call['request']);req.pop('seed',None);req.pop('model',None)
                    if 'request' in row: assert row['request']==req, ('Changed request',tid)
                    row['request']=req
                    score=reward(row['task'],call['completion'])
                    assert score['correct']==call['score']['correct'],(tid,step)
                    checks+=1
                    examples.setdefault((tid,bool(score['correct'])),dict(task_id=tid,step=step,archive=archive,
                        completion=call['completion'],score=score,advantage=call['task_advantage']))
    for row in wanted.values():
        assert 'request' in row,row['id']
        task=row['task']
        # Independently check score acceptance for every legal action in the
        # selected O tasks, including tolerance already embodied in the teacher.
        if row['evidence']['kind']=='O':
            visible=present(task,task.get('name_variant',0))
            for native,shown in zip(task['input']['legal_actions'],visible['legal_actions']):
                name,args=action_call(shown)
                comp=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop')
                assert reward(task,comp)['correct']==(native in task['teacher']['acceptable_actions'])
        else:
            gold=task['teacher']['gold']; mass=task['teacher'].get('preference_weights')
            if mass:
                assert set(gold['possible_preferences'])=={k for k,v in mass.items() if v>1e-10}
                ranked=sorted(mass,key=mass.get,reverse=True)
                expected=ranked[0] if mass[ranked[0]]-mass[ranked[1]]>task['teacher'].get('favored_margin',.1)+1e-9 else 'undetermined'
                assert gold['favored']==expected,(row['id'],mass,gold)
            previous=task['input'].get('previous_belief')
            if row['operation'] in ('exclude','favored'):
                assert previous!=gold, ('Copyable previous label',row['id'])
        records.append(row)
    base_examples=read('examples/social_mixed/micro_learning_24_v1/examples.jsonl')
    examples.update({(r['task_id'],bool(r['score']['correct'])):r for r in base_examples if r['task_id'] in {x['id'] for x in records[:8]}})
    assert len(records)==24 and len({r['id'] for r in records})==24
    o_tasks={r['task']['canonical_id']:r for r in records if r['evidence']['kind']=='O'}
    relations=[]
    for rel in read('examples/social_mixed/paired_bank_v2/relations.jsonl'):
        if rel['left'] in o_tasks and rel['right'] in o_tasks:
            a=o_tasks[rel['left']];b=o_tasks[rel['right']]
            sa={digest(x) for x in a['task']['teacher']['acceptable_actions']};sb={digest(x) for x in b['task']['teacher']['acceptable_actions']}
            if rel['relation']=='must_change': assert not sa&sb
            relations.append(dict(rel,left_task=a['id'],right_task=b['id'],accepted_intersection=len(sa&sb)))
    assert any(r['relation']=='must_change' and r['fixed_continuation_payoffs_match'] for r in relations)
    assert any(r['relation']=='same_optimal_set' for r in relations)
    assert not set.intersection(*[{digest(x) for x in r['task']['teacher']['acceptable_actions']} for r in o_tasks.values()])
    # Freeze the previous micro24 run's actual LR trajectory by update. Both
    # new arms use it regardless of different response lengths / no-B cost.
    tokens=[0]*40
    with tarfile.open(ROOT/'new/micro_learning_evidence_20260925/training_micro24.tar.gz') as tar:
        for member in tar:
            if '/calls/step-' not in member.name or not member.name.endswith('.jsonl'):continue
            step=int(member.name.split('step-')[1].split('.')[0]);job=member.name.split('/')[2].split('-')[-1]
            if (job=='878813' and step<10) or job=='878930':
                tokens[step]+=sum(len(json.loads(l)['response_ids']) for l in tar.extractfile(member))
    assert all(tokens)
    consumed=0;lr=[]
    for n in tokens:lr.append(learning_rate(consumed,3932160));consumed+=n
    pools={k:sorted(r['id'] for r in records if r['evidence']['kind']==k) for k in ('O','P','B')}
    pools['B']=[r['id'] for offset in (0,1) for op in ('insufficient','exclude','favored','revealed') for r in [sorted((x for x in records if x.get('operation')==op),key=lambda x:x['id'])[offset]]]
    schedule=[dict(update=i,task_ids=[tid for k in ('O','P','B') for tid in pools[k][4*(i%2):4*(i%2)+4]],replicas=8,learning_rate=lr[i]) for i in range(40)]
    def write(name,rows): (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    write('tasks.jsonl',records);write('examples.jsonl',examples.values());write('schedule.jsonl',schedule);write('relations.jsonl',relations)
    manifest=dict(version='micro-learning-24-v2',tasks=24,updates=40,exposures_per_task=20,replicas=8,
        historical_calls_rescored=checks,loss_reference_rows=96,no_b_rows=64,
        lr_policy='frozen micro24-v1 actual LR by update; 878813 steps0-9 +878930 steps10-39, token horizon3932160',
        limitations=['Historical evidence is not a fresh Q0 probe','Directional/subset B learning evidence is weaker; no mastery claim','Some legacy B contain supplied previous qualitative belief; explicitly retained teaching interface','Relation provenance permits prior/evidence changes, not guaranteed single-variable intervention'],
        sha256={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','examples.jsonl','schedule.jsonl','relations.jsonl']})
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(tasks=len(records),calls_checked=checks,relations=len(relations))))

if __name__=='__main__':build()
