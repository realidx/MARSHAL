"""Small mechanism diagnostics; never modifies the active game or candidate pool.

gift: supply one private preference for free at an early decision, holding the
partner reference fixed. This is a counterfactual information upper comparison,
not a re-solved zero-cost-query game or a dataset S label.
fixture: solve the old acquisition fixture from initial state, then inspect its
historical PASS prefix using the *same* profile. Also solve that prefix as the
old exogenous control, explicitly separate from the full-game result.
"""
import argparse
from collections import defaultdict
from copy import copy
import json
from pathlib import Path
import time

import numpy as np

from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import file_hash, write_json, save_reference, replay_node
from training.strategic_slices.diagnose_bounded import count_bounded_nodes
from training.strategic_slices.early_investigation import terminal_response_values, measure_early_investigation
from training.strategic_slices.oracle_consistent import oracle_reach
from training.strategic_slices.terminal_candidates import TerminalCandidates
from training.strategic_slices.values import masked_answer_value


def gifted_values(tree, ego, slot):
    """Refine focal information by one true slot at every future own decision.

    For a first-proposal root, earlier own actions did not know this slot. Their
    reference likelihood is constant inside each original own-information cell,
    so global counterfactual reach gives the same conditional future beliefs.
    Only values at that root and its descendants are used.
    """
    view=copy(tree); view.information_groups=dict(tree.information_groups)
    for i, entry in enumerate(tree.entries):
        if entry.actor != ego:
            continue
        refined=[]
        for ids in tree.information_groups[i]:
            groups=defaultdict(list)
            for wi in ids:
                groups[tree.worlds[int(wi)][slot[0]][slot[1]]].append(int(wi))
            refined.extend(np.array(v,dtype=int) for v in groups.values())
        view.information_groups[i]=tuple(refined)
    return terminal_response_values(view, ego)


def gift(out):
    source=Path('new/local_data/strategic_slices_oracle_consistent_candidates_v3')
    early=Path('new/local_data/strategic_slices_early_investigation_v1')
    data=TerminalCandidates(source)
    # Fixed convenience diagnostic: five retained positive entry-answer parents
    # and the early weak acquisition-action case. No random-yield claim.
    pids=sorted({g['parent_id'] for g in data.entry_answer_relations})[:5]
    pids.append('dbe956b01542c8a7ebaf14f5')
    write_json(out/'gift_config.json',dict(parents=pids,source_manifest_sha256=file_hash(source/'manifest.json'),
        script_sha256=file_hash(Path(__file__)),scope='Fixed-profile free private signal, not a new equilibrium or candidate corpus. First proposal for every player/type/public history in six convenience parents.'))
    results=[]
    for pid in pids:
        path=out/f'gift_{pid}.json'
        if path.exists():
            result=json.loads(path.read_text())
        else:
            start=time.monotonic()
            row=next(r for r in data.candidates if r['parent_id']==pid)
            tree=data.reference(row)
            roots=json.loads((early/(pid+'.json')).read_text())['rows']
            rows=[]
            for ego in range(tree.n):
                cells=[r for r in roots if r['ego']==ego]
                slots=sorted({tuple(q['slot']) for r in cells for q in r['query_details'] if q['informative']})
                for slot in slots:
                    values=gifted_values(tree,ego,slot)
                    for r in cells:
                        q=next(q for q in r['query_details'] if tuple(q['slot'])==slot)
                        if not q['informative']:
                            continue
                        v=float(np.array(r['world_weights'])@values[r['root_index']])
                        if v<r['V_full']-1e-8:
                            raise AssertionError('A free signal reduced full best-response value')
                        rows.append(dict(entrance_id=r['id'],root_index=r['root_index'],ego=ego,
                            own=r['own'],world_weights=r['world_weights'],slot=list(slot),
                            V_original=r['V_full'],V_free_signal=v,gain=max(0.,v-r['V_full']),
                            original_delta_investigate=r['delta_investigate'],
                            oracle_information_set_mass=r['oracle_information_set_mass']))
            result=dict(parent_id=pid,rows=rows,seconds=time.monotonic()-start,
                reference_id=row['reference_id'],policy_sha256=tree.certificate['policy_sha256'])
            write_json(path,result)
        results.append(result)
        print(pid,'free_signal_max',max((r['gain'] for r in result['rows']),default=0),flush=True)
        rows=[r for result in results for r in result['rows']]
        write_json(out/'gift_summary.json',dict(parents=len(results),comparisons=len(rows),
            positive_comparisons=sum(r['gain']>1e-8 for r in rows),strong_comparisons=sum(r['gain']>.05 for r in rows),
            max_gain=max((r['gain'] for r in rows),default=0),solver_calls=0,model_calls=0))


def fixture(out):
    fixture_path=Path('examples/strategic_slices/fixtures/information_acquisition.json')
    f=json.loads(fixture_path.read_text());raw=f['raw'];rules=PrivateInvestigationRules(raw)
    write_json(out/'fixture_raw.json',raw)
    results=[]
    for name, history in [('initial',[]),('external_pass_control',f['history'])]:
        start=time.monotonic();root=replay_node(rules,history)
        result=dict(case=name,history=history,status='started')
        try:
            count=count_bounded_nodes(rules,root,len(rules.spec.round_robin))['unfolded_public_history_nodes']
            result['nodes']=count
            if count>160000:
                result.update(status='node_budget',oracle_label=None)
            else:
                tree=BoundedPrivateWindow(rules,root,rules.worlds,
                    world_weights=world_weights(rules.worlds,raw['background_prior']),
                    lookahead_rr=len(rules.spec.round_robin),max_nodes=160000,seconds=90).solve()
                tree.deadline=time.monotonic()+120
                native=tree.audit_native();assert native['cutoff_leaves']==0
                save_reference(out/f'{name}.npz',tree)
                result.update(status='certified',certificate=tree.certificate,native_audit=native)
                if name=='initial':
                    result['early_rows']=measure_early_investigation(tree,'old_acquisition_fixture')
                    reach,_=oracle_reach(tree);i=0
                    for ai in f['history']: i=tree.entries[i].children[ai]
                    result['historical_pass_prefix_mass']=float(reach.get(i,np.zeros(tree.w)).sum())
                    result['historical_pass_index']=i
                else:
                    roots=[0]
                    result['prefix_belief_scope']='External PASS; initial prior restored, separately solved. Not full-game oracle reach.'
                    result['query_comparisons']=[]
                    e=tree.entries[0]
                    for ids in tree.information_groups[0]:
                        w=np.zeros(tree.w);w[ids]=tree.world_weights[ids];w/=w.sum()
                        for ai,a in enumerate(e.actions):
                            a=a.to_dict()
                            if a.get('action')!='INVESTIGATE':continue
                            slot=(a['player'],a['goal'])
                            val=masked_answer_value(tree,ego=e.actor,root_index=0,root_weights=w,
                                query_slot=slot,k=2*len(rules.spec.round_robin))
                            result['query_comparisons'].append(dict(slot=list(slot),own=list(tree.worlds[int(ids[0])][e.actor]),
                                V_full=val['V_full'],V_mask=val['V_mask'],S=val['S']))
        except Exception as exc:
            result.update(status='failed',error=str(exc),oracle_label=None)
        result['seconds']=time.monotonic()-start
        write_json(out/f'fixture_{name}.json',result);results.append(result)
        print(name,result['status'],result.get('historical_pass_prefix_mass'),result['seconds'],flush=True)
    write_json(out/'fixture_summary.json',dict(results=results,fixture_sha256=file_hash(fixture_path),script_sha256=file_hash(Path(__file__))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['gift','fixture'],required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    (gift if a.mode=='gift' else fixture)(a.output)
