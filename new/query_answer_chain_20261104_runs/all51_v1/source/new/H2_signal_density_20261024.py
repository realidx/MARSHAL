"""Count decision contexts, without using signal density to select parents."""
import gzip
import json
from new.three_player_complexity_v1_20261023.common import ROOT, snapshot, identity, write, sha


def main():
    run = ROOT/'new/three_player_complexity_v1_20261023/local_H2_33_v1'
    out = ROOT/'new/three_player_complexity_v1_20261023/local_H2_signal_density_v1'
    results = [r for r in json.loads((run/'results.json').read_text())if r.get('labels')=='MEASURED']
    inputs = {'results':identity(run/'results.json'),'script':identity(__file__),
              'run_snapshot':identity(run/'pipeline_snapshot.json')}
    paths = {}
    for result in results:
        path = run/str(__import__('pathlib').Path(result['result_path']).parent)/'labels.jsonl.gz'
        assert sha(path)==result['labels_sha256']
        paths[result['index']] = path
        inputs[str(result['index'])] = identity(path)
    snapshot(out,dict(operation='H2 decision-context signal density, no parent selection',
        requested=33,measured=31,missing_original_indices=[46,76],epsilon=1e-8,
        unit='One stored positive-CF current information context (node, information cell)',
        warning='S=0 does not mean no Q/D training value; no model D measured'),inputs)
    counts = {scope:dict(contexts=0,private_S_positive=0,history_S_positive=0,
        any_S_positive=0,any_entry_action_positive=0)for scope in ('counterfactual','on_reference')}
    for result in results:
        with gzip.open(paths[result['index']],'rt')as stream:
            for line in stream:
                row = json.loads(line)
                for scope in ('counterfactual','on_reference'):
                    if scope=='on_reference'and row['reference_mass']<=0:continue
                    c=counts[scope];c['contexts']+=1
                    c['private_S_positive']+=row['S_private']>1e-8
                    c['history_S_positive']+=row['S_history']>1e-8
                    c['any_S_positive']+=max(row['S_private'],row['S_history'])>1e-8
                    c['any_entry_action_positive']+=any(item.get('entry_action_regret',0)>1e-8 for item in row['S_items'])
    for c in counts.values():c['any_S_positive_fraction']=c['any_S_positive']/c['contexts']
    all_cells=sum(r['summary']['all_cells']for r in results)
    zero=sum(r['summary']['zero_CF_cells']for r in results)
    write(out/'DENSITY.json',dict(measured=31,counts=counts,all_information_cells=all_cells,
        zero_CF_cells=zero,zero_CF_status='S_UNAVAILABLE_NOT_ZERO',
        limitation='No relation to GRPO reward variance has been measured. These are oracle information contexts, not sampled model responses.'))
    write(out/'COMPLETE.json',dict(density_sha256=sha(out/'DENSITY.json'),pipeline_snapshot_sha256=sha(out/'pipeline_snapshot.json')))
    print(json.dumps(counts,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
