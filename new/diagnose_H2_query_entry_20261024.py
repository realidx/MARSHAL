"""Check whether original35's positive query examples already infer the answer."""
import json
from new.three_player_complexity_v1_20261023.common import ROOT, snapshot, identity, write, sha
from new.strategic_game_v1_20261021.rules import StrategicRules


def main():
    case = ROOT/'new/three_player_complexity_v1_20261023/local_H2_33_v1/cases/11/execution-0000'
    out = ROOT/'new/three_player_complexity_v1_20261023/query35_entry_belief_v1'
    request = json.loads((case/'request.json').read_text())
    examples = json.loads((case/'examples.json').read_text())['query_advantage']
    snapshot(out, dict(operation='Original35 entry posterior support diagnostic; no solver changes',
        selection='Same two positive-query examples as query35_channel_v1',
        distinction='Inference-known targets remain legal by the confirmed query rule',
        tolerance='stored strictly positive posterior support, no new probability cutoff'),
        {name:identity(case/name) for name in ('request.json','examples.json','result.json')} |
        {'diagnostic_script':identity(__file__)})
    worlds = StrategicRules(request['job']['raw']).worlds
    checks = []
    for row in examples:
        query = next(a for a in row['actions'] if a['action']=='INVESTIGATE')
        target = query['player'],query['goal'];belief = {}
        for wi, mass in zip(row['world_ids'],row['posterior']):
            if mass>0:
                value = worlds[wi][target[0]][target[1]]
                belief[str(value)] = belief.get(str(value),0.)+mass
        assert abs(sum(belief.values())-1.)<1e-8
        checks.append(dict(node=row['node'],own_type=row['own_type'],query=query,
            posterior=row['posterior'],target_belief=belief,
            answer_already_inferred_at_entry=len(belief)==1,history=row['history']))
    write(out/'DIAGNOSTIC.json',dict(original_index=35,checks=checks,
        limitation='Inference is relative to the frozen reference likelihood, not a logical truth under arbitrary opponent strategies.'))
    write(out/'COMPLETE.json',dict(checks=len(checks),
        diagnostic_sha256=sha(out/'DIAGNOSTIC.json'),pipeline_snapshot_sha256=sha(out/'pipeline_snapshot.json')))
    print(json.dumps(checks,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
