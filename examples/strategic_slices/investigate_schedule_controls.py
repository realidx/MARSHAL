"""Native complete-game schedule controls for the historical query mechanism.

Same payoff geometry, private catalogues, prior, and native investigation cost.
Each player has the same number of proposal opportunities across variants;
only their order changes. These are diagnostic parents, never active data.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import time

from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import file_hash, write_json, save_reference
from training.strategic_slices.diagnose_bounded import count_bounded_nodes
from training.strategic_slices.early_investigation import measure_early_investigation
from training.strategic_slices.values import masked_answer_value


def run(out):
    out.mkdir(parents=True,exist_ok=True)
    source=Path('examples/strategic_slices/fixtures/information_acquisition.json')
    raw0=json.loads(source.read_text())['raw'];results=[]
    for schedule in ([1,0,0,1],[1,0,1,0]):
        name=''.join(map(str,schedule));raw=deepcopy(raw0);raw['game']['round_robin']=schedule
        write_json(out/f'raw_{name}.json',raw);start=time.monotonic()
        result=dict(name=name,schedule=schedule,status='started')
        try:
            rules=PrivateInvestigationRules(raw)
            count=count_bounded_nodes(rules,rules.initial(),3)['unfolded_public_history_nodes'];result['nodes']=count
            if count>160000:
                raise RuntimeError('Preflight node budget exceeded')
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),
                lookahead_rr=3,max_nodes=160000,seconds=90,large_tree_ordered_sweeps=8).solve()
            tree.deadline=time.monotonic()+120
            audit=tree.audit_native();assert audit['cutoff_leaves']==0
            save_reference(out/f'reference_{name}.npz',tree)
            rows=measure_early_investigation(tree,name)
            masks=[]
            # Check the actual initial actor and every positive early advantage.
            for r in rows:
                if r['root_index']!=0 and r['delta_investigate']<=1e-8:
                    continue
                for q in r['query_details']:
                    if not q['informative']:continue
                    v=masked_answer_value(tree,ego=r['ego'],root_index=r['root_index'],
                        root_weights=r['world_weights'],query_slot=tuple(q['slot']),k=2*len(schedule))
                    masks.append(dict(entrance_id=r['id'],root_index=r['root_index'],ego=r['ego'],
                        own=r['own'],slot=q['slot'],V_full=v['V_full'],V_mask=v['V_mask'],S=v['S']))
            result.update(status='certified',certificate=tree.certificate,native_audit=audit,early_rows=rows,
                masks=masks,max_delta=max(r['delta_investigate'] for r in rows),
                max_measured_S=max((m['S'] for m in masks),default=0))
        except Exception as exc:
            result.update(status='failed',error=str(exc),oracle_label=None)
        result['seconds']=time.monotonic()-start;results.append(result)
        write_json(out/f'result_{name}.json',result)
        write_json(out/'summary.json',dict(source_sha256=file_hash(source),script_sha256=file_hash(Path(__file__)),
            scope='Two complete native parents, two rounds with one proposal per player in each round; only second-round order changes. Invalid shortened-schedule attempts remain separately recorded in v1.',results=results))
        print(name,result['status'],result.get('max_delta'),result.get('max_measured_S'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
