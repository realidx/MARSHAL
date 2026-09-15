"""Second design pass: verify discovered witnesses and expose remaining gaps."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_terminal_teacher import TerminalEpisode, VERSION
from training.b_sft.debug.audit_social_design_iteration import (
    fixture, layout_fixture, small_information_fixture, choice_information_fixture,
    root_report, selection_audit, renaming_audit, independent_values,
    belief_examples, investigation_use_audit, planning_review_task, qualitative_audit,
)


def run(out):
    if out.exists():
        raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True)
    reports = []
    tasks = []
    p_tasks = []
    cases = []
    # This seed supplies a two-event favored-only update with two hidden players.
    cases.append((*fixture(104,hidden=2), 'favored_update'))
    cases.append((*small_information_fixture(), 'tiny_investigation_advantage'))
    cases.append((*fixture(225,hidden_goal=3), 'delayed_goal_investigation'))
    cases.append((*choice_information_fixture(514), 'choice_investigation'))
    cases.append((*choice_information_fixture(500), 'investigation_cost_control'))
    for layout in ('one_hidden','same_player_two','two_players','includes_observer'):
        cases.append((*layout_fixture(104,layout), 'layout_'+layout))
    for raw,prefix,role in cases:
        report = dict(role=role,raw=raw,prefix=prefix)
        try:
            e = TerminalEpisode(raw,prefix,seconds=12,max_nodes=30000)
            report.update(status='solved',root=root_report(e),native=independent_values(e.tree))
            if role in ('favored_update','tiny_investigation_advantage','delayed_goal_investigation','choice_investigation'):
                report['initialization'] = selection_audit(raw,prefix,e,seconds=12,max_nodes=30000)
                report['renaming'] = renaming_audit(raw,prefix,e)
            if 'investigation' in role:
                report['result_use'] = investigation_use_audit(e)
                p_tasks.extend(planning_review_task(e,t,social_tolerance=s)
                               for t in (0.,.025,.05,.1) for s in (0.,.025,.05,.1))
            for p,rows in raw['type_catalogues'].items():
                for g in range(len(rows[0])):
                    if len({r[g] for r in rows}) > 1:
                        tasks.extend(belief_examples(e,int(p),g,max_per_kind=2))
        except SearchLimit as exc:
            report.update(status='solver_failure',detail=str(exc))
        reports.append(report)
        print(json.dumps(dict(role=role,status=report['status'])),flush=True)
    q = qualitative_audit(social_tolerances=(0.,.05,.1,.25))
    summary = dict(version=VERSION,actual_LM=False,training_ready=False,
        statuses=dict(Counter(r['status'] for r in reports)),
        b_categories=dict(Counter(t['category'] for t in tasks)),
        p_review_tasks=len(p_tasks), qualitative_statuses=dict(Counter(t['status'] for t in q)),
        supported_claims=['Native transition and full-terminal value replay for every solved followup case',
                          'B formation, assisted maintenance and update are separate inputs',
                          'Near-optimal learner scoring does not change strict partner behavior'],
        open_issues=['Default teacher non-convergence still yields no label; alternative-initialization failures are diagnostics only',
                     'Positive public-investigation value does not establish direct learner use of the result',
                     'Zero gain from hiding the direct result does not rule out indirect inference from later partner behavior',
                     'No production runner integration, formal dataset generation or LM training in this iteration'],
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__),Path('training/b_sft/debug/audit_social_design_iteration.py'),
            Path('training/b_sft/social_terminal_teacher.py'),Path('training/b_sft/social_p_qualitative.py'))})
    for name,obj in [('cases.json',reports),('summary.json',summary),('p_qualitative.json',q)]:
        (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    for name,rows in [('b_review_tasks.jsonl',tasks),('p_review_tasks.jsonl',p_tasks)]:
        (out/name).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    run(args.out)
