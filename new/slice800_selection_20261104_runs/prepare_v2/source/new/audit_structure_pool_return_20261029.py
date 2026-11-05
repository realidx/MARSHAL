"""Verify returned archive and summarize all frozen24; no new solve/selection."""
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

from new import structure_pool_20261026 as p
from new.A2H2_structure_20261026 import IndexedReference
import numpy as np

VERSION='structure-pool-return-audit-v1'
REG=p.ROOT/'examples/strategic_slices/versions/structure_pool_return_audit_v1_20261029/SNAPSHOT.json'
EPS=1e-8
REMOTE='runtime/new/structure_pool_v1_20261026/'
RUN='remote_remaining18_runtime_v4_20261029'
RELOAD='remote_reload18_runtime_v4_20261029'


def digest(data):return hashlib.sha256(data).hexdigest()
def ident(path):return dict(path=str(path.relative_to(p.ROOT)),sha256=p.sha(path))


def archive(root):
    manifest=json.loads((root/'MANIFEST.json').read_text());path=root/manifest['archive']['name']
    assert path.stat().st_size==manifest['archive']['size'] and p.sha(path)==manifest['archive']['sha256']
    expected={x['path']:x for x in manifest['files']};assert len(expected)==len(manifest['files'])
    saved={};copied_sources=0
    frozen=json.loads((p.ROOT/'examples/strategic_slices/versions/structure_pool_v1_20261026/SNAPSHOT.json').read_text())['source_hashes']
    with tarfile.open(path)as t:
        for member in t:
            assert member.isfile() and member.name in expected,member.name
            record=expected.pop(member.name);data=t.extractfile(member).read()
            assert len(data)==record['size']and digest(data)==record['sha256'],member.name
            if '/source/'not in member.name:saved[member.name]=data
            else:
                source=member.name.split('/source/',1)[1]
                assert source in frozen and digest(data)==frozen[source],member.name
                copied_sources+=1
    assert not expected
    return saved,dict(files=len(manifest['files']),source_copies_verified=copied_sources,
        archive_sha256=p.sha(path),bytes=path.stat().st_size)


def read(saved,path):return json.loads(saved[path])


def aggregate(parents):
    measured=[x for x in parents if x['measured']]
    fields=['contexts','private_positive','history_positive','any_positive','current_action_positive',
        'proposal_positive','response_positive','reference_contexts','reference_private_positive',
        'reference_history_positive','reference_any_positive','reference_current_action_positive',
        'private_current_action_positive','history_current_action_positive','all_cells','zero_CF_cells']
    out={k:sum(x[k]for x in measured)for k in fields}
    out.update(requested=len(parents),measured=len(measured),missing=[x['index']for x in parents if not x['measured']],
        private_positive_parents=sum(x['private_positive']>0 for x in measured),
        history_positive_parents=sum(x['history_positive']>0 for x in measured),
        any_positive_parents=sum(x['any_positive']>0 for x in measured),
        reference_any_positive_parents=sum(x['reference_any_positive']>0 for x in measured),
        reference_mass=sum(x['reference_mass']for x in measured),
        reference_positive_mass=sum(x['reference_positive_mass']for x in measured),
        equal_parent_positive_fraction=float(np.mean([x['any_positive']/x['contexts']for x in measured]))if measured else None)
    out['positive_fraction']=out['any_positive']/out['contexts']if out['contexts']else None
    out['reference_occupancy_positive_fraction']=out['reference_positive_mass']/out['reference_mass']if out['reference_mass']else None
    return out


def measure(job,result,raw_labels,ref,args):
    cf=result['summary']['counterfactual'];on=result['summary']['on_reference'];counts=Counter()
    groups=defaultdict(list);best={};positive=[];refmass=positive_mass=0.
    with gzip.GzipFile(fileobj=io.BytesIO(raw_labels))as stream:
        for line in stream:
            row=json.loads(line);assert row['counterfactual_mass']>0
            pri=(row['S_private']or 0)>EPS;hist=(row['S_history']or 0)>EPS;anypos=pri or hist
            regret=any(x.get('S',0)>EPS and x.get('entry_action_regret',0)>EPS for x in row['S_items'])
            counts['contexts']+=1;counts['private_positive']+=pri;counts['history_positive']+=hist
            counts['any_positive']+=anypos;counts['current_action_positive']+=regret
            counts['proposal_positive']+=anypos and row['phase']=='proposal'
            counts['response_positive']+=anypos and row['phase']=='response'
            for channel in ('private','history'):
                counts[channel+'_current_action_positive']+=any(x.get('S',0)>EPS and x.get('entry_action_regret',0)>EPS
                    and x['omitted'][0]==channel for x in row['S_items'])
            refmass+=row['reference_mass'];positive_mass+=row['reference_mass']*anypos
            if row['reference_mass']>0:
                counts['reference_contexts']+=1;counts['reference_any_positive']+=anypos
                counts['reference_private_positive']+=pri;counts['reference_history_positive']+=hist
                counts['reference_current_action_positive']+=regret
            if anypos:
                positive.append({k:row[k]for k in ('node','cell','actor','phase','turn','S_private','S_history','reference_mass')})
            for item in row['S_items']:
                channel=item['omitted'][0]
                if item.get('S',0)>EPS:
                    rank=(item['S'],row['reference_mass'],-row['node'],-row['cell'])
                    if channel not in best or rank>best[channel][0]:best[channel]=(rank,row,item)
                if channel=='private'and row['phase']=='proposal':
                    mask=item['omitted'];other=[x for x in row['private_answers']if x[:2]!=mask[1:]]
                    key=p.stable([row['node'],row['actor'],row['own_type'],other,mask])
                    groups[key].append((set(row['own_optimal']),item.get('S',0)>EPS))
    assert counts['contexts']==cf['contexts'] and counts['private_positive']==cf['private_S_positive']
    assert counts['history_positive']==cf['history_S_positive'] and counts['reference_contexts']==on['contexts']
    assert counts['reference_private_positive']==on['private_S_positive']and counts['reference_history_positive']==on['history_S_positive']
    ambiguous=[items for items in groups.values()if len(items)>1]
    masks=dict(ambiguous_private_proposal_groups=len(ambiguous),
        no_common_own_optimum=sum(not set.intersection(*(x[0]for x in items))for items in ambiguous),
        positive_S_groups=sum(any(x[1]for x in items)for items in ambiguous))
    # Reuse global reference only for predeclared representative native suffix checks.
    replay=[]
    with np.load(io.BytesIO(ref))as loaded:flat=loaded['probabilities']
    indexed=IndexedReference(job,flat)
    for channel,(_,row,item)in sorted(best.items()):
        started=time.monotonic();node,offset=indexed.find(row['node']);nodes=indexed.stats(node)[0]
        record=dict(channel=channel,row=row,item=item,remaining_nodes=nodes)
        if nodes<=args.replay_max_nodes:
            _,checked=indexed.replay(row,args.replay_max_nodes,args.replay_seconds)
            record.update(status='NATIVE_TERMINAL_Q_MATCH',check=checked)
        else:record.update(status='SKIPPED_DECLARED_NODE_CAP')
        record['elapsed_seconds']=time.monotonic()-started;replay.append(record)
    # Counter keys with zero counts remain explicit for later group summaries.
    for key in ['reference_contexts','reference_any_positive','reference_private_positive','reference_history_positive','reference_current_action_positive']:
        counts[key]+=0
    return dict(index=job['index'],pair_id=job['pair_id'],arm=job['arm'],configuration=job['configuration'],
        measured=True,solver_status=result['status'],**dict(counts),all_cells=result['summary']['all_cells'],
        zero_CF_cells=result['summary']['zero_CF_cells'],reference_mass=refmass,reference_positive_mass=positive_mass,
        positive_fraction=counts['any_positive']/counts['contexts'],
        reference_occupancy_positive_fraction=positive_mass/refmass,
        private_proposal_groups=masks,positive_contexts=positive,replay_checks=replay,
        max_private_S=cf['max_private_S'],max_history_S=cf['max_history_S'],
        source_scope='same480 source hashes; native terminal certificate and saved-reference audit provenance verified')


def main():
    a=argparse.ArgumentParser();a.add_argument('--input',type=Path,default=p.ROOT/'new/structure_pool_remote_results_20261029')
    a.add_argument('--local',type=Path,default=p.ROOT/'new/structure_pool_v1_20261026/local_pilot_v1')
    a.add_argument('--output',type=Path,required=True);a.add_argument('--replay-max-nodes',type=int,default=50000)
    a.add_argument('--replay-seconds',type=float,default=30.);args=a.parse_args()
    for name in ('input','local','output'):setattr(args,name,getattr(args,name).resolve())
    base=p.ROOT/'examples/strategic_slices/versions/structure_pool_v1_20261026/SNAPSHOT.json'
    sources=json.loads(base.read_text())['source_hashes'];pool=p.ROOT/'new/structure_pool_v1_20261026/raw_v1/parents.jsonl'
    inputs={str(q.relative_to(p.ROOT)):ident(q)for q in [pool,base,args.input/'MANIFEST.json',args.input/'results.tar.gz',args.input/'SUMMARY.json',args.local/'pipeline_snapshot.json',args.local/'results.json',args.local/'COMPLETE.json',args.local.parent/'local_reload_v1/COMPLETE.json']}
    p.VERSION,p.REG=VERSION,REG
    p.snapshot(args.output,dict(operation='Returned frozen24 integrity, parent-balanced pairing and representative native suffix Q replay',
        numerical_epsilon=EPS,replay_max_nodes=args.replay_max_nodes,replay_seconds=args.replay_seconds,
        selection='All local0..5 and remote runtime_v4 indices6..23; failed4/11 never zero or substituted',
        pairing='Only10 complete pairs for mask comparison;12 structural strata descriptive, no causal or powered efficacy claim',
        reference='Reuse first certified saved policies, no search/repair/reselection',
        witnesses='Maximum S per measured parent per channel; ties reference mass then earliest node/cell; skip above declared cap',
        private_groups='Same public node/actor/own type/other answers/omission; intersect own-optimal current actions only among positive-CF cells',
        denominator='Positive counterfactual contexts only; reference occupancy weighted by saved reference mass, not modelD',
        excluded='Cancelled wrong-environment run and two pre-case failures',model='NOT_USED',D='NOT_MEASURED',training='NOT_RUN'),inputs)
    saved,verified=archive(args.input)
    assert digest(saved['runtime/new/structure_pool_v1_20261026/raw_v1/parents.jsonl'])==p.sha(pool)
    assert digest(saved['runtime/examples/strategic_slices/versions/structure_pool_v1_20261026/SNAPSHOT.json'])==p.sha(base)
    jobs=list(map(json.loads,pool.read_text().splitlines()));remote=read(saved,REMOTE+RUN+'/results.json')
    remote_snapshot=read(saved,REMOTE+RUN+'/pipeline_snapshot.json');local_snapshot=json.loads((args.local/'pipeline_snapshot.json').read_text())
    assert remote_snapshot['source_hashes']==sources==local_snapshot['source_hashes']
    for name in (RUN,RELOAD,'remote_retry11_v1_20261029','remote_reload_retry11_v1_20261029'):
        complete=read(saved,REMOTE+name+'/COMPLETE.json')
        for field,file in [('results_sha256','results.json'),('pipeline_snapshot_sha256','pipeline_snapshot.json')]:
            assert digest(saved[REMOTE+name+'/'+file])==complete[field]
    assert [j['index']for j in read(saved,REMOTE+RUN+'/jobs.json')]==list(range(6,24))
    assert read(saved,REMOTE+RELOAD+'/COMPLETE.json')['independently_passed']==17
    assert json.loads((args.local.parent/'local_reload_v1/COMPLETE.json').read_text())['independently_passed']==5
    reloaded=read(saved,REMOTE+RELOAD+'/results.json');assert all(x['status']=='independently_reloaded'for x in reloaded)
    assert {x['index']for x in reloaded}=={x['index']for x in remote if x.get('labels')=='MEASURED'}
    results={x['index']:x for x in json.loads((args.local/'results.json').read_text())+remote}
    assert set(results)==set(range(24));parents=[]
    for job in jobs:
        i=job['index'];result=results[i]
        if result.get('labels')!='MEASURED':
            parents.append(dict(index=i,pair_id=job['pair_id'],arm=job['arm'],configuration=job['configuration'],
                measured=False,solver_status=result['status'],error=result.get('error')));continue
        assert result['cutoff_leaves']==0 and result['native_audit']['cutoff_leaves']==0
        native=result['native_audit'];assert all(native[x]for x in ('native_transitions_match','native_action_set_complete','leaf_payoffs_match'))
        assert native['cutoff']==len(job['raw']['game']['round_robin'])
        cert=result['certificate'];assert cert['verified']and cert['own_utility_epsilon_nash_verified']and cert['response_only_social_ties_verified']
        if i<6:
            folder=args.local/Path(result['result_path']).parent
            data=(folder/'labels.jsonl.gz').read_bytes();ref=(folder/'reference.npz').read_bytes()
            request=json.loads((folder/'request.json').read_text())
        else:
            folder=REMOTE+RUN+'/'+str(Path(result['result_path']).parent)
            data=saved[folder+'/labels.jsonl.gz'];ref=saved[folder+'/reference.npz'];request=read(saved,folder+'/request.json')
        assert request['job']==job and digest(data)==result['labels_sha256']and digest(ref)==result['reference_sha256']
        parent=measure(job,result,data,ref,args);parents.append(parent)
        p.write(args.output/'PARENTS.json',parents)
        print(dict(index=i,any_S=parent['any_positive'],private_S=parent['private_positive'],history_S=parent['history_positive'],replays=len(parent['replay_checks'])),flush=True)
    pairs=[]
    for i in range(12):
        aa,bb=parents[2*i:2*i+2];assert aa['pair_id']==bb['pair_id']==i
        pairs.append(dict(pair_id=i,configuration=aa['configuration'],indices=[aa['index'],bb['index']],
            complete=aa['measured']and bb['measured'],uniform=aa,shared_goal=bb))
    matched=[x for x in pairs if x['complete']];paired={}
    for arm in ('uniform','shared_goal'):paired[arm]=aggregate([x[arm]for x in matched])
    strata={}
    for key in ('geometry','scoring','goals'):
        strata[key]={str(v):aggregate([x for x in parents if x['configuration'][key]==v])for v in sorted({x['configuration'][key]for x in parents})}
    summary=dict(version=VERSION,integrity=verified,all24=aggregate(parents),
        arms={arm:aggregate([x for x in parents if x['arm']==arm])for arm in ('uniform_mask','shared_goal_mask')},
        complete_pairs=len(matched),incomplete_pair_ids=[x['pair_id']for x in pairs if not x['complete']],paired=paired,strata=strata,
        runtime_comparison=dict(local=local_snapshot['environment'],remote=remote_snapshot['environment'],
            algorithm_config_differences={k:[local_snapshot['resolved_config'].get(k),v]for k,v in remote_snapshot['resolved_config'].items()
                if local_snapshot['resolved_config'].get(k)!=v}),
        terminal='All22 have zero nonterminal cutoff leaves, endpoint equals native6 proposal turns; generic bounded certificate wording not promoted to formal exact/sequential equilibrium',
        limits='No LP or cross-equilibrium invariance checks on new labels; Q replay checks only selected suffixes; no modelD/advantage/training effects',
        completed_on='2026-10-29')
    p.write(args.output/'PAIRS.json',pairs);p.write(args.output/'SUMMARY.json',summary)
    checks=[c for x in parents if x['measured']for c in x['replay_checks']]
    p.write(args.output/'COMPLETE.json',dict(requested=24,measured=summary['all24']['measured'],
        missing=summary['all24']['missing'],archive_files_verified=verified['files'],complete_pairs=len(matched),
        witness_Q_checks=sum(c['status']=='NATIVE_TERMINAL_Q_MATCH'for c in checks),
        skipped_witness_checks=sum(c['status']!='NATIVE_TERMINAL_Q_MATCH'for c in checks),
        summary_sha256=p.sha(args.output/'SUMMARY.json'),pipeline_snapshot_sha256=p.sha(args.output/'pipeline_snapshot.json')))
    print(p.stable(summary['all24']),flush=True)


if __name__=='__main__':main()
