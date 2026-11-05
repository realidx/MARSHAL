"""Prespecified small native terminal subgames, not new frozen parent membership."""
import argparse
import hashlib
import json
from pathlib import Path

from .common import ROOT,identity,parents,snapshot,stable,write,sha
from new.strategic_game_v1_20261021.rules import StrategicRules


def make_job(index,parent,raw,setup,arm,kind):
    return dict(index=index,id=hashlib.sha256(stable(dict(raw=raw,setup=setup,arm=arm)).encode()).hexdigest()[:24],
        original_index=parent['index'],original_parent_id=parent['id'],arm=arm,kind=kind,raw=raw,setup=setup,
        claim='Certified native terminal subgame only; does not certify original opening equilibrium')


def first_rr_queries(raw):
    rules=StrategicRules(raw);node=rules.initial();setup=[]
    for _ in range(rules.spec.n_players):
        actions=rules.actions(node);queries=[a for a in actions if a.to_dict().get('action')=='INVESTIGATE']
        a=queries[0] if queries else next(a for a in actions if a.to_dict().get('action')=='PASS')
        setup.append(a.to_dict());node=rules._apply(node,a)
    return setup


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pool',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot(args.output,dict(operation='Freeze prespecified small efficacy diagnostics and parent25 value tests',
        original_three_player_indices=[3,7],arms=['baseline','H2','H3','A2H2'],
        three_player_setup='Every first-RR proposal queries first legal unknown preference, else PASS; no offers; no hidden truth used',
        parent25_setup='P0 query P1/G2; P1 query P0/G1 orG2; P0 PASS; then final P1 proposal',
        tests_through='native terminal, no depth-limited leaf',not_full_parent_certification=True),{'pool':identity(args.pool)})
    variants=list(map(json.loads,args.pool.read_text().splitlines()));original=parents();jobs=[]
    for index in (3,7):
        parent=original[index]
        for arm in ('baseline','H2','H3','A2H2'):
            raw=parent['raw'] if arm=='baseline' else next(r['raw'] for r in variants if r['original_index']==index and r['arm']==arm)
            jobs.append(make_job(len(jobs),parent,raw,first_rr_queries(raw),arm,'three_player_terminal_endgame_diagnostic'))
    p=original[25];special=[]
    for goal in (1,2):
        setup=[dict(action='INVESTIGATE',player=1,goal=2),dict(action='INVESTIGATE',player=0,goal=goal),dict(action='PASS')]
        special.append(make_job(len(special),p,p['raw'],setup,f'parent25-query-G{goal}','original_parent25_terminal_endgame_diagnostic'))
    for name,rows in [('three_player_subgames.jsonl',jobs),('parent25_subgames.jsonl',special)]:
        (args.output/name).write_text(''.join(stable(r)+'\n' for r in rows))
    # Optional one existing exact full-parent reference; hash and raw equality
    # are checked before reuse, followed by full independent native acceptance.
    candidate=next(r for r in variants if r['original_index']==7 and r['arm']=='H2')
    raw_path=ROOT/'new/sparse_solver_v1_20261023/capacity_v1/cases/7-hidden2/raw.json'
    ref_path=ROOT/'new/sparse_solver_v1_20261023/capacity_v1/cases/7-hidden2/reference.npz'
    reusable=[]
    if raw_path.exists() and ref_path.exists() and stable(json.loads(raw_path.read_text()))==stable(candidate['raw']):
        job=dict(candidate,index=0,reuse=dict(raw_path=str(raw_path.relative_to(ROOT)),raw_sha256=sha(raw_path),
            reference_path=str(ref_path.relative_to(ROOT)),reference_sha256=sha(ref_path)))
        reusable=[job]
    (args.output/'optional_full_parent_reuse.jsonl').write_text(''.join(stable(r)+'\n' for r in reusable))
    write(args.output/'COMPLETE.json',dict(three_player_subgames=len(jobs),parent25_subgames=len(special),
        reusable_full_parent=len(reusable),files={name:sha(args.output/name) for name in
            ('three_player_subgames.jsonl','parent25_subgames.jsonl','optional_full_parent_reuse.jsonl')},
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(three_player_subgames=len(jobs),parent25_subgames=len(special),reusable_full_parent=len(reusable)))


if __name__=='__main__':main()
