"""Read-only CPU checks of current prompt state, private recall and response ties."""
import json
import tarfile
from pathlib import Path
import numpy as np
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.social_terminal_teacher import Investigate
from training.b_sft.decision_policy import optimal_indices
from training.strategic_slices.named_prompt import request,visible
from training.strategic_slices.common import file_hash
from training.strategic_slices.pipeline_versions import registered_snapshot
from training.strategic_slices.terminal_training import VERSION
from training.strategic_slices.named_prompt import VERSION as PROMPT_VERSION
from examples.strategic_slices.export_terminal_prompt_preview import rebuild

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent


def memory_trace():
    fixtures=json.loads((ROOT/'examples/strategic_slices/versions/terminal_v8_readable_20261018/input_fixtures.json').read_text())
    raw=next(c['raw'] for c in fixtures if c['label']=='terminal_private_new_answer')
    rules=PrivateInvestigationRules(raw);rules.background_prior=raw['background_prior']
    node=rules.initial();ego=rules.actor(node);world=rules.worlds[0]
    target,goal=next((p,g) for p,rows in rules.catalogues.items() if p!=ego for g in range(len(rows[0])) if len({r[g] for r in rows})>1)
    _,v,names=visible(rules,node,world[ego]);fact=(names.players[target],names.goals[goal],{1:'want',0:'neutral',-1:'avoid'}[world[target][goal]])
    events=[];focal_calls=[]
    def snapshot(label):
        actor=rules.actor(node);req=request(rules,node,world,42,remaining_decisions=3-len(focal_calls))
        actor_view=visible(rules,node,world[actor])[1]
        record=dict(label=label,actor=actor,phase='response' if node.pending else 'proposal',
            private_results=rules.observation(node,actor,world[actor])['private_results'],
            commitments=node.state.public_state()['commitments'],pending_offer=None if node.pending is None else node.pending.to_dict(),
            messages_roles=[m['role'] for m in req['messages']],prior_assistant_messages=sum(m['role']=='assistant' for m in req['messages']),
            request=req)
        if actor==ego:
            focal_calls.append(record)
            if len(focal_calls)>1:
                assert (target,goal,world[target][goal]) in node.state.private_results[ego]
                area=req['messages'][1]['content'].split('YOUR PRIVATE INFORMATION',1)[1].split('BACKGROUND PREFERENCE DISTRIBUTION',1)[0]
                assert '| '+' | '.join(fact)+' |' in area
        else:
            assert node.state.private_results[actor]==()
            if actor!=target:assert names.goals[goal] not in actor_view['your_private_investigation_answers'].get(names.players[target],{})
        events.append(record)
    snapshot('focal_decision_1_before_investigation')
    node=rules.step(node,Investigate(target,goal),realized_world=world)
    snapshot('partner_proposal_after_private_delivery')
    offer=next(a for a in rules.actions(node) if a.to_dict().get('action')=='OFFER' and a.to_dict()['partner_id']==ego)
    node=rules.step(node,offer,realized_world=world)
    snapshot('focal_decision_2_response_answer_present')
    accept=next(a for a in rules.actions(node) if a.to_dict().get('response')=='ACCEPT')
    node=rules.step(node,accept,realized_world=world)
    assert node.pending is None and any(any(r) for r in node.state.public_state()['commitments'])
    snapshot('next_partner_proposal_binding_commitments_without_pending_offer')
    offer=next(a for a in rules.actions(node) if a.to_dict().get('action')=='OFFER' and a.to_dict()['partner_id']==ego)
    node=rules.step(node,offer,realized_world=world)
    snapshot('focal_decision_3_response_answer_still_present')
    assert len(focal_calls)==3
    return dict(focal=ego,queried_slot=dict(player=target,goal=goal,value=world[target][goal]),
        focal_decisions=3,private_answer_present_at_later_focal_decisions=True,
        binding_commitments_exist_at_proposal_stage=True,assistant_chat_history_carried=False,
        model_called=False,events=events)


def response_ties():
    pool=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    parents={r['id']:r for r in map(json.loads,(pool/'parents.jsonl').read_text().splitlines())}
    selected=list(map(json.loads,(ROOT/'new/local_data/strategic_slices_terminal_selected_v4/candidates.jsonl').read_text().splitlines()))
    checked=[];mismatches=[]
    for row in selected:
        if row['decision_kind']!='response':continue
        rules=PrivateInvestigationRules(parents[row['parent_id']]['raw'])
        for mi,member in enumerate(row['members']):
            node=rules.initial()
            for ai in member['history']:node=rules._apply(node,rules.actions(node)[ai])
            assert node.pending is not None
            actions=rules.actions(node);children=[rules._apply(node,a) for a in actions]
            if not all(n.state.is_terminal for n in children):continue
            masses=np.array(member['world_weights'])
            q=np.array([masses@np.array([rules.terminal_payoffs(n,w) for w in rules.worlds]) for n in children])
            assert np.allclose(q[:,row['ego']],member['root_Q'],rtol=0.,atol=1e-9)
            own=q[:,row['ego']];others=q.sum(axis=1)-own
            old=np.flatnonzero(own>=own.max()-1e-7).tolist()
            intended=optimal_indices(q,row['ego'],actions,1e-9).tolist()
            record=dict(slice_id=row['id'],parent_id=row['parent_id'],member_index=mi,
                actions=[a.to_dict() for a in actions],Q_own=own.tolist(),Q_others_sum=others.tolist(),
                current_own_only_correct_indices=old,response_tie_correct_indices=intended,
                current_training_rewards=(own-own.max()).tolist())
            checked.append(record)
            if set(old)!=set(intended):mismatches.append(record)
    refs=list(map(json.loads,(pool/'references.jsonl').read_text().splitlines()))
    return dict(scope='Selected 100 training slices, terminal response nodes only; no held-out audit or new equilibrium solving',
        frozen_references=len(refs),frozen_references_response_tie_certified=sum(r['certificate'].get('response_only_social_ties_verified',False) for r in refs),
        terminal_response_members_checked=len(checked),members_where_current_correct_set_differs=len(mismatches),
        mismatches=mismatches,checked=checked)


def logged_response_ties():
    """Find actual sampled contexts where own-only labels omit a social tie."""
    archive=ROOT/'new/terminal_node_v6_training_960070/raw/training-960070.tar.gz.part000'
    pool=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    parents={r['id']:r['raw'] for r in map(json.loads,(pool/'parents.jsonl').read_text().splitlines())}
    seen=set();examples=[];checked=0
    with tarfile.open(archive,'r|gz') as tar:
        for member in tar:
            if not member.name.startswith('run/calls/'):continue
            for line in tar.extractfile(member):
                call=json.loads(line);key=call['prompt_sha256']
                if key in seen:continue
                seen.add(key);v=json.loads(call['request']['messages'][-1]['content'])
                if not v['pending_offer']:continue
                rules,node,_=rebuild(parents[call['parent_id']],v)
                actions=rules.actions(node);children=[rules._apply(node,a) for a in actions]
                if not all(n.state.is_terminal for n in children):continue
                checked+=1;masses=np.array(call['oracle_step']['posterior'])
                q=np.array([masses@np.array([rules.terminal_payoffs(n,w) for w in rules.worlds]) for n in children])
                own=q[:,v['player']];others=q.sum(axis=1)-own
                assert np.allclose(own,call['oracle_step']['Q'],rtol=0.,atol=1e-9)
                if np.ptp(own)>1e-9 or np.ptp(others)<=1e-9:continue
                examples.append(dict(archive_member=member.name,task_id=call['task_id'],parent_id=call['parent_id'],
                    actions=[a.to_dict() for a in actions],Q_own=own.tolist(),Q_others_sum=others.tolist(),
                    current_correct_indices=np.flatnonzero(own.max()-own<=1e-7).tolist(),
                    response_tie_correct_indices=optimal_indices(q,v['player'],actions,1e-9).tolist(),
                    current_reward=(own-own.max()).tolist(),sampled_action_index=call['action_index'],
                    logged_binary_correct=call['binary_reward']))
                if len(examples)==3:return dict(scope='First 3 counterexamples from actual v6 training contexts; not a prevalence estimate',
                    terminal_contexts_checked_until_stop=checked,examples=examples)
    return dict(scope='Actual v6 training contexts',terminal_contexts_checked_until_stop=checked,examples=examples)


def main():
    registered=registered_snapshot(VERSION,PROMPT_VERSION)
    trace=memory_trace();ties=response_ties();logged=logged_response_ties()
    (OUT/'memory_trace.json').write_text(json.dumps(trace,indent=2)+'\n')
    (OUT/'response_tie_audit.json').write_text(json.dumps(ties,indent=2)+'\n')
    (OUT/'logged_response_ties.json').write_text(json.dumps(logged,indent=2)+'\n')
    (OUT/'summary.json').write_text(json.dumps(dict(active=registered,private_recall_verified=True,
        frozen_references_response_tie_certified=ties['frozen_references_response_tie_certified'],
        terminal_response_members_checked=ties['terminal_response_members_checked'],
        mismatched_response_members=ties['members_where_current_correct_set_differs'],
        actual_training_context_counterexamples=len(logged['examples']),
        production_sources_changed=False,dataset_changed=False,model_called=False,gpu_tested=False),indent=2)+'\n')
    print(json.dumps({k:v for k,v in ties.items() if k not in ('checked','mismatches')},indent=2))
    print(json.dumps(ties['mismatches'][:1],indent=2))
    print(json.dumps(logged,indent=2))
    assert registered_snapshot(VERSION,PROMPT_VERSION)==registered


if __name__=='__main__':main()
