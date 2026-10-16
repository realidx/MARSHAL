"""CPU-only exactness and warm-cache timing on frozen train questions; no model."""
import argparse
import json
from pathlib import Path
import time
import numpy as np

from training.strategic_slices.common import write_json
from training.strategic_slices.train_terminal import ROOT
from training.strategic_slices.terminal_training import TrainingData
from training.strategic_slices.values import extreme_value,cached_extreme_value


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--pool',type=Path,default=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4')
    cli.add_argument('--selection',type=Path,default=ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    if args.output.exists():raise ValueError('Use a fresh output path')
    data=TrainingData(args.pool,args.selection);selected={}
    for row in data.train:
        n=data.parents[row['parent_id']]['raw']['game']['n_players']
        selected.setdefault((n,row['k']),row)
    records=[]
    for (players,k),row in sorted(selected.items()):
        tree,cache=data.reference(row);before=tree.reference_identity()[0]
        member=row['members'][0];inputs=(tree,row['ego'],member['root_index'],member['world_weights'],k)
        started=time.perf_counter();old=extreme_value(*inputs);old_seconds=time.perf_counter()-started
        started=time.perf_counter();cold=cached_extreme_value(*inputs,cache=cache);cold_seconds=time.perf_counter()-started
        started=time.perf_counter();warm=cached_extreme_value(*inputs,cache=cache);warm_seconds=time.perf_counter()-started
        for value in (cold,warm):
            np.testing.assert_allclose(value['root_Q'],old['root_Q'],atol=1e-12,rtol=0)
            assert abs(value['value']-old['value'])<=1e-12
            assert value['policy'].keys()==old['policy'].keys()
            for index in old['policy']:np.testing.assert_array_equal(value['policy'][index],old['policy'][index])
        np.testing.assert_allclose(warm['root_Q'],member['root_Q'],atol=1e-7,rtol=0)
        assert tree.reference_identity()[0]==before
        _,again=data.reference(row)
        tail_key=('frozen-terminal-tail-v1',row['ego'])
        if tail_key in cache:assert again[tail_key] is cache[tail_key]
        records.append(dict(id=row['id'],players=players,k=k,tree_nodes=len(tree.entries),
            exhaustive_seconds=old_seconds,cold_seconds=cold_seconds,warm_seconds=warm_seconds,
            window_nodes=warm['window_nodes'],cold_tail_nodes=cold['tail_nodes_computed'],warm_tail_nodes=warm['tail_nodes_computed'],
            root_Q_max_error=float(np.max(np.abs(np.asarray(warm['root_Q'])-old['root_Q']))),
            values_and_policies_equal=True,frozen_reference_unchanged=True))
        print(json.dumps(records[-1]),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write_json(args.output,dict(dataset_sha256=data.sha,records=records,cache_metrics=data.cache_metrics(),
        gpu_tested=False,new_model_calls=0,limitation='CPU solver timing only; not end-to-end training or GPU throughput.'))


if __name__=='__main__':main()
