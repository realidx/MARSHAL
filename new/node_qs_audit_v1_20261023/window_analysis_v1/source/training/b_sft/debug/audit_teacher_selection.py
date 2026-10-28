"""Diagnose existing teacher player-renaming failures without changing its rules.

The diagnostic preserves the current solve implementation verbatim except the
two player-iteration orders. It is never installed in the production oracle.
"""
import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import textwrap

import numpy as np

from training.b_sft.debug.audit_social_semantics import read, rename, rename_action, root_choices, compare_roots
from training.b_sft.debug.audit_menu_information import direct_value
from training.b_sft.social_b_oracle import BeliefOracle, canonical
from training.b_sft.social_b_random_window import RandomTieWindow
from training.b_sft.shared_teacher import SearchLimit, TOL
from training.b_sft.social_b_dataset import observer_belief, judgment


def ordered_tree(oracle, order):
    source=textwrap.dedent(inspect.getsource(RandomTieWindow.solve))
    assert source.count('for p in range(self.n):')==2
    altered=source.replace('for p in range(self.n):','for p in self.audit_order:')
    scope=dict(np=np,SearchLimit=SearchLimit,TOL=TOL)
    exec(compile(altered,'<diagnostic-only-player-order>','exec'),scope)
    cls=type('DiagnosticOrderWindow',(RandomTieWindow,),dict(solve=scope['solve']))
    tree=cls(oracle.rules,oracle.node,oracle.worlds,turns=oracle.turns,
             max_nodes=3000,seconds=5,world_weights=oracle.weights)
    assert sorted(order)==list(range(tree.n))
    tree.audit_order=order
    return tree.solve()


def run(audit,sources_path,tasks_path,out):
    if out.exists():raise ValueError('Use a new output directory')
    failures=[r for r in read(audit/'root_renaming.jsonl') if r['status']=='different']
    sources={s['id']:s for s in read(sources_path)}
    tasks=read(tasks_path);root_reports=[];task_reports=[]
    for failure in failures:
        s=sources[failure['source']];n=s['raw']['game']['n_players']
        mapping={p:n-1-p for p in range(n)};inverse={v:k for k,v in mapping.items()}
        raw,prefix=rename(s['raw'],s['prefix'],mapping)
        original=BeliefOracle(s['raw'],s['prefix'],max_nodes=3000,seconds=5)
        renamed=BeliefOracle(raw,prefix,max_nodes=3000,seconds=5)
        aligned=BeliefOracle(raw,prefix,max_nodes=3000,seconds=5)
        aligned._tree=ordered_tree(aligned,[mapping[p] for p in range(n)])
        left=root_choices(original);right=root_choices(renamed);fixed=root_choices(aligned)
        assert compare_roots(left,right,inverse)
        assert not compare_roots(left,fixed,inverse)
        # Re-execute every root action for every actor type in all three policies.
        for o,rows in ((original,left),(renamed,right),(aligned,fixed)):
            tree=o.solve()
            for row in rows:
                for ai,v in enumerate(row['values']):
                    value=direct_value(tree,tree.policy,row['actor'],row['own_type'],ai)
                    assert np.allclose([value[row['actor']],value.sum()-value[row['actor']]],
                                       [v['own'],v['others']],atol=1e-9,rtol=0)
        root_reports.append(dict(source=s['id'],original_order=list(range(n)),
            renamed_default_order=list(range(n)),renamed_aligned_order=aligned._tree.audit_order,
            differences_reproduced=True,aligned_order_restores_root_values_and_actions=True,
            native_values_verified=True,certificates=[o.solve().certificate for o in (original,renamed,aligned)]))
        for t in tasks:
            if t['source']!=s['id']:continue
            history=[rename_action(a,mapping) for a in t['input']['history']]
            events=[dict(action=a,kind='setup' if i<len(prefix) else 'partner') for i,a in enumerate(history)]
            report=dict(id=t['id'],source=t['source'],split=t['split'],old_gold=t['gold']['judgments'][0])
            try:
                o=BeliefOracle.replay(raw,events,max_nodes=3000,seconds=5)
                q=t['input']['queries'][0]
                gold=judgment(observer_belief(o,mapping[q['player']],q['goal']))
                report.update(status='label_changed' if gold!=judgment(report['old_gold']) else 'label_same',renamed_gold=gold)
            except ValueError as exc:
                report.update(status='incompatible_history' if 'incompatible with every candidate' in str(exc) else 'failed',detail=str(exc))
            except Exception as exc:
                report.update(status='failed',error=type(exc).__name__,detail=str(exc))
            task_reports.append(report)
        print(json.dumps(dict(completed=s['id'])),flush=True)
    summary=dict(actual_LM=False,training_ready=False,root_reproductions=len(root_reports),
        checkpoint_statuses=dict(Counter(r['status'] for r in task_reports)),
        by_split={s:dict(Counter(r['status'] for r in task_reports if r['split']==s)) for s in ('train','validation','test')},
        finding='Player sweep order selects different stable contingent policies; transporting the original order restores all four root results.',
        limitation='Only four detected roots and their 26 existing tasks, not a full-history/all-permutation audit. Restoring order diagnoses the cause; it is not a socially justified policy-selection fix.',
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(inspect.getsourcefile(RandomTieWindow)),sources_path,tasks_path)})
    out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (out/'root_reproductions.json').write_text(json.dumps(root_reports,ensure_ascii=False,indent=2)+'\n')
    (out/'checkpoint_renaming.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in task_reports))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,default=Path('new/local_data/social_runs/social_semantics_audit_v1'))
    p.add_argument('--sources',type=Path,default=Path('new/local_data/social_runs/b_weighted_v4_reviewed/sources.jsonl'))
    p.add_argument('--tasks',type=Path,default=Path('new/local_data/social_runs/b_behavior_curriculum_v2/tasks.jsonl'))
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.audit,a.sources,a.tasks,a.out)
