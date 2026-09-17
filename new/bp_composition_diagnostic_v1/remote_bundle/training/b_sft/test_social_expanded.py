import io
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from contextlib import redirect_stdout

from training.b_sft.social_three_arm import expanded_cases,NativeEpisode,partner,Scripted,run,ARMS


def audit_coverage():
    rows=[]
    for case in expanded_cases():
        counts=[];nodes=0
        for world in case['worlds']:
            replay=NativeEpisode(case['raw'],[])
            for i,action in enumerate(case['prefix']):
                if i>=case['setup_length'] and replay.rules.actor(replay.node)!=case['raw']['ego']:
                    assert partner(replay,world,Random(0))==action
                replay.step(action)
            def walk(history,decisions):
                nonlocal nodes
                env=NativeEpisode(case['raw'],history);nodes+=1
                if env.node.state.is_terminal:
                    counts.append(decisions);return
                actor=env.rules.actor(env.node)
                if actor==case['raw']['ego']:
                    actions=env.visible()['legal_actions'];decisions+=1
                else:
                    # Independent qualitative implementation of the public rule.
                    pending=env.node.pending is not None
                    desired=({'response':'ACCEPT'} if pending else dict(action='OFFER',partner_id=case['raw']['ego'],proposer_action=[1],partner_action=[1]))
                    fallback={'response':'REJECT'} if pending else {'action':'PASS'}
                    expected=fallback
                    legal=env.rules.actions(env.node)
                    selected=next((a for a in legal if a.to_dict()==desired),None)
                    if selected:
                        before=env.node.state.goal_satisfaction()
                        child=env.rules._apply(env.node,selected)
                        if child.pending is not None:
                            accept=next(a for a in env.rules.actions(child) if a.to_dict()=={'response':'ACCEPT'})
                            child=env.rules._apply(child,accept)
                        delta=[p for p,old,new in zip(world[actor],before,child.state.goal_satisfaction()) if new and not old]
                        if 1 in delta and -1 not in delta:expected=desired
                    actual=partner(env,world,Random(0));assert actual==expected,(case['id'],history,actual,expected)
                    actions=[actual]
                for action in actions:walk(history+[action],decisions)
            walk(case['prefix'],0)
        rows.append(dict(case=case['id'],kind=case['kind'],worlds=len(case['worlds']),
                         traversed_nodes=nodes,terminal_paths=len(counts),
                         min_learner_decisions=min(counts),max_learner_decisions=max(counts)))
    return rows


class ExpandedTests(unittest.TestCase):
    def test_qualitative_rule_and_multiple_decisions_on_every_path(self):
        rows=audit_coverage()
        self.assertEqual(len(rows),7)
        for row in rows:
            if row['kind']=='multi_decision':self.assertGreaterEqual(row['min_learner_decisions'],2)
            else:self.assertEqual(row['max_learner_decisions'],1)

    def test_equal_budgets_and_future_native_decisions(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            out=Path(tmp)/'run';summary=run(out,Scripted(),pack_name='expanded')
            for arm in ARMS:
                self.assertEqual(summary[arm]['rollout_slots'],48)
                self.assertEqual(summary[arm]['terminal_episodes'],48)
                self.assertEqual(summary[arm]['multi_decision_episodes'],8)
                self.assertGreaterEqual(summary[arm]['future_decision_count'],8)
                calls=[json.loads(l) for l in (out/f'{arm}_calls.jsonl').read_text().splitlines()]
                self.assertTrue(any(c['phase']=='response' for c in calls))
                self.assertTrue(any(c['history_length']>4 for c in calls))

if __name__=='__main__':unittest.main()
