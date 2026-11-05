"""CPU end-to-end audit of actual native800 requests, decoding and scoring."""
from new import qualified_parents_6535_20261104 as p
from examples.strategic_slices.native800.decision import Decision
from examples.strategic_slices.native800.prompt import request,VERSION as PROMPT_VERSION
from examples.strategic_slices.native800.scoring import score,CONTRACT,VERSION as SCORE_VERSION
from training.strategic_slices.named_prompt_v7 import canonical
from training.strategic_slices.terminal_training import group_advantages
from training.b_sft.review_prompt import SYSTEM
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import unittest
import numpy as np
import scipy

VERSION='native800-prompt-score-v1'
ROOT=p.m.ROOT
REG=ROOT/'examples/strategic_slices/versions/native800_prompt_score_v1_20261105/SNAPSHOT.json'


def snapshot(out,config,inputs):
    registered=json.loads(REG.read_text())
    assert registered['version']==VERSION
    for name,digest in registered['source_hashes'].items():assert p.m.sha(ROOT/name)==digest,name
    out.mkdir(parents=True,exist_ok=False)
    for name in registered['source_hashes']:
        target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    shutil.copyfile(REG,out/'registered_snapshot_at_start.json')
    p.m.write(out/'pipeline_snapshot.json',dict(version=VERSION,date='2026-11-05',actual_argv=sys.argv,
        resolved_config=config,input_identity=inputs,source_hashes=registered['source_hashes'],registration_sha256=p.m.sha(REG),
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,scipy=scipy.__version__,
            platform=platform.platform(),threads={key:os.environ.get(key,'NOT_RECORDED')for key in p.m.THREAD_KEYS}),
        prompt_version=PROMPT_VERSION,score_contract=CONTRACT,model='NOT_USED',D='NOT_MEASURED',
        sampling='NO_MODEL_SAMPLING; request seed/temp are preview fixtures only',
        advantage='UNCHANGED existing same-context sample-std GRPO',training='NOT_STARTED_NOT_MIGRATED',
        production_active='terminal-node-regret-grpo-readable-v8'))


def output(call):
    name,args=call
    return dict(finish_reason='stop',completion=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))])))


def expected_preferences(rules,node,world,names):
    facts=set();labels={-1:'avoid',0:'neutral',1:'want'};actor=rules.actor(node)
    for player,rows in rules.catalogues.items():
        for g in range(len(rules.spec.goals)):
            if len({r[g]for r in rows})==1:facts.add((names.players[player],names.goals[g],labels[rows[0][g]]))
    for g,value in enumerate(world[actor]):facts.add((names.players[actor],names.goals[g],labels[value]))
    for player,g in p.observed_slots(node,actor):facts.add((names.players[player],names.goals[g],labels[world[player][g]]))
    return facts


def actual_preferences(text):
    area=text.split('PUBLIC PREFERENCES\n',1)[1].split('BACKGROUND PREFERENCE DISTRIBUTION',1)[0]
    result=set()
    for line in area.splitlines():
        if line.startswith('|'):
            cells=tuple(x.strip()for x in line.strip('|').split('|'))
            if len(cells)==3 and cells[-1]in('want','neutral','avoid'):result.add(cells)
    return result


def audit_parent(parent,records,pool,out):
    source=json.loads((ROOT/parent['admission']['path']).read_text())['source']
    assert p.m.sha(ROOT/parent['admission']['path'])==parent['admission']['sha256']
    indexed=p.IndexedReference(source['job']);rules=indexed.rules
    counts=Counter();cases=[];requests=[];changed=[]
    for record in records:
        row=record['oracle_annotation'];node,_=indexed.find(row['node'])
        wi=next(w for w,m in zip(row['world_ids'],row['posterior'])if m>0);world=rules.worlds[wi]
        seed=int(p.digest([42,VERSION,record['id']])[:8],16)
        before=p.stable(node.state.public_state());before_private=deepcopy(node.state.private_results)
        binding=Decision(indexed,row['node'],world,row,seed)
        req=binding.request;text=req['messages'][1]['content']
        assert [m['role']for m in req['messages']]==['system','user']
        assert req['messages'][0]['content']==SYSTEM
        for heading in ['GAME RULES','GOAL REQUIREMENTS BY PLAYER','PUBLIC PREFERENCES','YOUR PRIVATE INFORMATION',
                        'BACKGROUND PREFERENCE DISTRIBUTION','EVENTS IN ORDER','ALREADY ACCEPTED COMMITMENTS','PUBLIC TURN STATUS','CURRENT DECISION','RESPONSE INSTRUCTIONS']:
            assert heading in text,heading
        assert 'Briefly explain'in text and 'other players'in text and 'opportunities remaining'in text
        for forbidden in ['DECISIONS IN THIS EXERCISE','YOUR CONTROL WINDOW','DECISION OBJECTIVE','precomputed','SCORING CUTOFF',
                          'Who knows','true investigation answer','posterior','root_Q','PUBLIC PREFERENCE SUPPORT']:
            assert forbidden not in text,forbidden
        from training.social_mixed.frozen.bp_display import Names
        names=Names(dict(game=rules.public_game()))
        assert actual_preferences(text)==expected_preferences(rules,node,world,names)
        schema={canonical(tool['function']['name'],args)for tool in req['tools']for args in tool['function']['parameters']['enum']}
        expected={canonical(name,args)for name,args in binding.action_calls};assert schema==expected
        for alternate in rules.worlds:
            if alternate[row['actor']]!=world[row['actor']]:continue
            if any(alternate[a][g]!=world[a][g]for a,g in p.observed_slots(node,row['actor'])):continue
            assert request(rules,node,alternate,seed)==req
            counts['same_visible_world_requests']+=1
        assert before==p.stable(node.state.public_state())and before_private==node.state.private_results
        details=[]
        for ai,call in enumerate(binding.action_calls):
            result=binding.score(output(call));assert result['action_index']==ai and result['valid']
            assert result['correct']==(ai in row['optimal'])
            details.append(result);counts['legal_tool_roundtrips']+=1
        old=set(row['own_optimal']);new=set(details[0]['optimal_indices'])
        if old!=new:changed.append(dict(id=record['id'],node=row['node'],cell=row['cell'],old_own_optimal=sorted(old),new_protocol_optimal=sorted(new),scores=details))
        if record['primary_role']=='response_social':
            assert all(d['active_axis']=='others_sum'for d in details)
            rewards=[d['task_reward']for d in details]*4;advs,_,_=group_advantages(rewards)
            assert max(advs)>0 and min(advs)<0;counts['social_entries_nonzero_existing_GRPO']+=1
        bad=dict(finish_reason='stop',completion=dict(raw_message=dict(tool_calls=[])))
        assert not binding.score(bad)['valid']
        truncated=output(binding.action_calls[0]);truncated['finish_reason']='length'
        assert binding.score(truncated)['status']=='truncated'
        duplicate=output(binding.action_calls[0]);duplicate['completion']['raw_message']['tool_calls']*=2
        assert not binding.score(duplicate)['valid']
        legacy=output(('act',dict(action_index=0)));assert not binding.score(legacy)['valid']
        if row['phase']=='response':assert 'You are RESPONDING'in text and 'NOT yet binding'in text
        else:assert 'There is no pending offer'in text
        for player in range(parent['players']):
            assert f'{names.players[player]}={rules.offer_limit-node.state.offer_used[player]}'in text
        requests.append(dict(entry_id=record['id'],request=req))
        cases.append(dict(entry_id=record['id'],parent_index=parent['index'],source=parent['source_key'],node=row['node'],cell=row['cell'],
            phase=row['phase'],players=parent['players'],private_answers=len(row['private_answers']),
            binding_commitments=any(any(x)for x in node.state.snapshot_commitments()),
            offer_available=any(a.get('action')=='OFFER'for a in row['actions']),
            query_available=any(a.get('action')=='INVESTIGATE'for a in row['actions']),
            primary_role=record['primary_role'],request=req,scores=details))
        counts['entries']+=1;counts['response_entries']+=row['phase']=='response'
    folder=out/'cases'/str(parent['index']);folder.mkdir(parents=True)
    with gzip.open(folder/'requests.jsonl.gz','wt')as f:
        for r in requests:f.write(p.stable(r)+'\n')
    p.m.write(folder/'AUDIT.json',dict(index=parent['index'],counts=dict(counts),changed_own_only_correctness=changed,
        request_file_sha256=p.m.sha(folder/'requests.jsonl.gz')))
    print(dict(index=parent['index'],entries=len(records),actions=counts['legal_tool_roundtrips'],status='PASS'),flush=True)
    return dict(index=parent['index'],counts=dict(counts),cases=cases,changed_count=len(changed))


def export_previews(cases,out):
    tests=[('proposal_two_player',lambda c:c['phase']=='proposal'and c['players']==2),
        ('proposal_three_player',lambda c:c['phase']=='proposal'and c['players']==3),
        ('response_own_tradeoff',lambda c:c['phase']=='response'and c['scores'][0]['active_axis']=='own'),
        ('response_social_tie',lambda c:c['primary_role']=='response_social'),
        ('proposal_after_investigation',lambda c:c['phase']=='proposal'and c['private_answers']>0),
        ('response_after_investigation',lambda c:c['phase']=='response'and c['private_answers']>0),
        ('proposal_existing_commitments',lambda c:c['phase']=='proposal'and c['binding_commitments']),
        ('proposal_offer_quota_exhausted',lambda c:c['phase']=='proposal'and not c['offer_available'])]
    folder=out/'previews';folder.mkdir();text=['# Native800完整prompt及回应评分预览','',
        '实际Decision.request生成，保留9月短system＋user＋具名tools；没有模型采样。',
        '每个状态都完整披露规则/目标/偏好/历史/预算/生效承诺；CURRENT DECISION按proposal/response切换。',
        '评分仅在回应自身Q平局时使用其他玩家效用总和；Q/S和GRPO算法不改。','']
    metadata=[]
    for label,predicate in tests:
        chosen=next(c for c in cases if predicate(c))
        p.m.write(folder/(label+'.json'),chosen['request'])
        meta={k:chosen[k]for k in ('entry_id','parent_index','source','node','cell','primary_role')};meta.update(label=label,scores=chosen['scores']);metadata.append(meta)
        text += ['## '+label,'',f'父{chosen["parent_index"]} / {chosen["source"]} / node{chosen["node"]}, cell{chosen["cell"]}。',
            '', '### System','','```text',chosen['request']['messages'][0]['content'],'```',
            '', '### User','','```text',chosen['request']['messages'][1]['content'],'```',
            '', '### Tools','','```json',json.dumps(chosen['request']['tools'],ensure_ascii=False,indent=2),'```','',
            '### 同一动作集合的评分','','```json',json.dumps(chosen['scores'],ensure_ascii=False,indent=2),'```','']
    (folder/'PROMPT_PREVIEW.md').write_text('\n'.join(text)+'\n');p.m.write(folder/'EXAMPLES.json',metadata)


def memory_trace(parent,record,pool,max_nodes=20000):
    source=json.loads((ROOT/parent['admission']['path']).read_text())['source']
    with np.load(pool/parent['reference']['path'])as a:flat=a['probabilities']
    indexed=p.IndexedReference(source['job'],flat);sparse=p.sparse_impl.SparseNative(indexed,8192)
    row=record['oracle_annotation'];focal=row['actor'];wi=next(w for w,m in zip(row['world_ids'],row['posterior'])if m>0);world=indexed.rules.worlds[wi]
    query=next((i for i,a in enumerate(row['actions'])if a['action']=='INVESTIGATE'and i in row['optimal']),None)
    if query is None:return None
    visited=0
    def search(gi,path,frames):
        nonlocal visited
        visited+=1
        if visited>max_nodes:return None
        node,offset=sparse.locate(gi);actor=indexed.rules.actor(node)
        if actor is None:return None
        req=request(indexed.rules,node,world,42)
        current=frames+([dict(node=gi,actor=actor,request=req)]if actor==focal else[])
        if len(current)>=3:return dict(focal=focal,world_id=wi,actions=path,frames=current,visited=visited)
        _,_,actions,children=sparse.expand(gi)
        options=([query]if not path else list(range(len(actions))))if actor==focal else[
            i for i in range(len(actions))if flat[offset:offset+len(actions)*indexed.w].reshape(len(actions),indexed.w)[i,wi]>0]
        for ai in options:
            result=search(children[ai][1],path+[dict(node=gi,actor=actor,action=actions[ai].to_dict())],current)
            if result:return result
        return None
    result=search(row['node'],[],[])
    if result:
        action=result['actions'][0]['action'];from training.social_mixed.frozen.bp_display import Names
        names=Names(dict(game=indexed.rules.public_game()));pref={-1:'avoid',0:'neutral',1:'want'}[world[action['player']][action['goal']]]
        fact=(names.players[action['player']],names.goals[action['goal']],pref)
        for frame in result['frames'][1:]:assert fact in actual_preferences(frame['request']['messages'][1]['content'])
        result.update(parent_index=parent['index'],source=parent['source_key'],persistent_answer=fact,
            scope='CPU supported-path search to exercise three focal decisions; not rollout sampling distribution or model performance')
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--pool',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    for k in ('dataset','pool','output'):setattr(args,k,getattr(args,k).resolve())
    manifest=json.loads((args.dataset/'MANIFEST.json').read_text());records=[]
    for name in ('train.jsonl','validation.jsonl'):
        assert p.m.sha(args.dataset/name)==manifest['files'][name]['sha256']
        records += [json.loads(l)for l in(args.dataset/name).read_text().splitlines()]
    parents=[json.loads(l)for l in(args.pool/'parents.jsonl').read_text().splitlines()]
    snapshot(args.output,dict(operation='Actual800request/action/scoring audit plus frozen complete previews',workers=args.workers,
        system='Exact SeptemberD short system retained by explicit user choice',
        prompt='State-specific native800readable-v1; no cutoff/window/reference/explanation-history text',
        tie_tolerance=1e-9,old_correctness_epsilon=1e-7,GRPO='UNCHANGED',main_Q_S='UNCHANGED',
        runtime='Current player continues to terminal; request rebuilt from full public history and own cumulative direct answers',
        memory_test='At most20000supported native nodes per candidate; require three focal decisions including investigation',
        D='NOT_MEASURED',sampling_defaults='NOT_CHANGED; seed42/temperature1 here are CPUpreview settings'),
        dict(dataset=p.ident(args.dataset/'MANIFEST.json'),parents=p.ident(args.pool/'parents.jsonl')))
    suite=unittest.defaultTestLoader.loadTestsFromName('examples.strategic_slices.native800.test_protocol')
    with(args.output/'unit_tests.txt').open('w')as handle:tested=unittest.TextTestRunner(stream=handle,verbosity=2).run(suite)
    assert tested.wasSuccessful()
    from training.b_sft.review_prompt import SYSTEM
    september=json.loads((ROOT/'examples/strategic_slices/versions/september_d_881010/prompt_request.json').read_text())
    assert SYSTEM==september['messages'][0]['content']
    groups={i:[r for r in records if r['parent_index']==i]for i in range(100)};results=[]
    with ProcessPoolExecutor(max_workers=args.workers)as executor:
        fs=[executor.submit(audit_parent,parents[i],rs,args.pool,args.output)for i,rs in groups.items()]
        for future in as_completed(fs):results.append(future.result())
    results.sort(key=lambda r:r['index']);cases=[c for r in results for c in r.pop('cases')]
    counts=Counter()
    for r in results:counts.update(r['counts'])
    cases.sort(key=lambda c:(c['parent_index'],c['node'],c['cell']));export_previews(cases,args.output)
    trace=None
    for record in records:
        if record['primary_role']!='acquire_required':continue
        trace=memory_trace(parents[record['parent_index']],record,args.pool)
        if trace:break
    assert trace is not None,'No three-focal-decision memory trace verified'
    p.m.write(args.output/'MEMORY_TRACE.json',trace)
    summary=dict(counts=dict(counts),all800_request_information_and_legal_tools_pass=True,
        all_legal_action_scores_match_saved_protocol_optimal_sets=True,
        old_own_only_correctness_changed_entries=sum(r['changed_count']for r in results),
        units=tested.testsRun,three_focal_decision_memory_verified=True,
        prompt_version=PROMPT_VERSION,scoring_version=SCORE_VERSION,
        new_model_D='NOT_MEASURED',GPU='NOT_USED',old_production='UNCHANGED_V8')
    p.m.write(args.output/'PARENTS.json',results);p.m.write(args.output/'SUMMARY.json',summary)
    p.m.write(args.output/'COMPLETE.json',dict(status='CPU_REQUEST_SCORE_ALIGNED_PENDING_PROMPT_REVIEW_AND_NEW_MODEL_D',
        summary_sha256=p.m.sha(args.output/'SUMMARY.json'),memory_sha256=p.m.sha(args.output/'MEMORY_TRACE.json'),
        preview_sha256=p.m.sha(args.output/'previews/PROMPT_PREVIEW.md'),pipeline_snapshot_sha256=p.m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
