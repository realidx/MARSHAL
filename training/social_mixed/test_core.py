from collections import Counter, defaultdict
from copy import deepcopy
import json
import random
import unittest

from training.social_mixed.core import Episode, Collector, assign_advantages, centered, load_data, sp_prompt


def generated(name, args, finish='stop'):
    return dict(prompt_ids=[1,2],response_ids=[3,4],behavior_log_probs=[-.5,-.3],
                completion=dict(finish_reason=finish,raw_message=dict(content='brief',tool_calls=[
                    dict(function=dict(name=name,arguments=json.dumps(args)))])))


def legal_response(episode, rng):
    obs=episode.observation()
    visible=sp_prompt.visible(obs)
    chosen=rng.choice(visible['legal_actions'])
    name,args=sp_prompt.action_call(chosen)
    return generated(name,args)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=load_data()

    def test_all_real_resets_reach_terminal_and_independent_utility(self):
        for split in ('train','validation'):
            for reset in self.data[f'selfplay_{split}']:
                episode=Episode(reset,'group',0,42)
                rng=random.Random(42)
                while episode.status=='running':episode.accept(legal_response(episode,rng))
                self.assertEqual(episode.status,'terminal')
                self.assertIsNotNone(episode.terminal)
                self.assertTrue(all(r['valid'] for r in episode.calls))

    def test_retry_does_not_change_state_or_erase_cost(self):
        episode=Episode(self.data['selfplay_train'][0],'g',0,42)
        initial=deepcopy(episode.observation())
        actor=episode.rules.actor(episode.node)
        episode.accept(generated('PASS',{},'length'))
        self.assertEqual(episode.observation(),initial)
        self.assertEqual(episode.penalties[actor],-.1)
        self.assertEqual(len(episode.request()['messages']),3)
        episode.accept(generated('PASS',{}))
        self.assertEqual(episode.penalties[actor],-.1)
        self.assertEqual(episode.attempt,0)

    def test_failed_episode_never_fabricates_utility(self):
        episode=Episode(self.data['selfplay_train'][0],'g',0,42)
        episode.accept(generated('NOT_A_TOOL',{}))
        episode.accept(generated('NOT_A_TOOL',{}))
        self.assertEqual(episode.status,'invalid_action')
        self.assertTrue(all(u['utility'] is None for u in episode.units()))

    def test_investigation_answer_private_and_consumes_opportunity(self):
        episode=Episode(self.data['selfplay_train'][0],'g',0,42)
        obs=episode.observation();actor=obs['player']
        actions=sp_prompt.visible(obs)['legal_actions']
        query=next(a for a in actions if a.get('action')=='INVESTIGATE')
        name,args=sp_prompt.action_call(query)
        episode.accept(generated(name,args))
        self.assertEqual(episode.node.state.turn_index,1)
        for p in range(episode.rules.spec.n_players):
            seen=episode.rules.observation(episode.node,p,episode.world[p])
            self.assertEqual(bool(seen['private_results']),p==actor)

    def test_grouping_is_by_episode_player_not_decision_count(self):
        units=[];rows=[]
        for p in range(2):
            for replica in range(4):
                uid=f'p{p}r{replica}'
                units.append(dict(group=f'p{p}',unit=uid,replica=replica,kind='selfplay',utility=replica*(-1 if p else 1),protocol=0))
                rows.extend(dict(unit=uid,kind='selfplay') for _ in range(replica+1))
        assign_advantages(rows,units,'selfplay')
        first={r['unit']:r['advantage'] for r in rows}
        self.assertAlmostEqual(first['p0r0'],-first['p1r0'])
        self.assertEqual(len({r['advantage'] for r in rows if r['unit']=='p0r3'}),1)
        mass=defaultdict(float)
        for row in rows:mass[row['unit']]+=row['loss_weight']
        self.assertAlmostEqual(min(mass.values()),max(mass.values()))

    def test_incomplete_group_uses_only_recorded_protocol(self):
        units=[dict(group='g',unit=str(i),replica=i,kind='selfplay',utility=None if i==0 else 100*i,protocol=-.2 if i==0 else 0) for i in range(4)]
        rows=[dict(unit=str(i),kind='selfplay') for i in range(4)]
        metrics=assign_advantages(rows,units,'selfplay')
        expected=centered([-.2,0,0,0])
        self.assertEqual([r['advantage'] for r in rows],expected)
        self.assertEqual(metrics['selfplay/outcome_incomplete_groups'],1)
        self.assertIsNone(units[0]['utility'])

    def test_mixture_mass_independent_of_episode_length(self):
        units=[];rows=[]
        for kind,length in [('B',1),('P',1),('selfplay',7)]:
            for i in range(4):
                uid=f'{kind}{i}'
                units.append(dict(group=kind,unit=uid,replica=i,kind=kind,utility=i%2,protocol=0))
                rows.extend(dict(kind=kind,unit=uid) for _ in range(length+i))
        assign_advantages(rows,units,'mixed')
        mass=defaultdict(float)
        for r in rows:mass[r['kind']]+=r['loss_weight']/len(rows)
        for kind,w in [('B',.25),('P',.25),('selfplay',.5)]:self.assertAlmostEqual(mass[kind],w)

    def test_zero_variance_groups_have_zero_task_signal(self):
        self.assertEqual(centered([0,0,0,0]),[0,0,0,0])
        self.assertEqual(centered([1,1,1,1]),[0,0,0,0])

    def test_collector_runs_both_arms_without_teacher_to_generator(self):
        requests_seen=[]
        def fake(requests):
            outputs=[]
            for req in requests:
                self.assertFalse({'teacher','raw','realized_world','gold'}.intersection(req))
                requests_seen.append(req)
                names=[t['function']['name'] for t in req['tools']]
                name='PASS' if 'PASS' in names else 'REJECT' if 'REJECT' in names else 'SUBMIT_BELIEFS'
                outputs.append(generated(name,{}))
            return outputs
        for arm in ('mixed','selfplay'):
            rows,units,games,metrics=Collector(self.data,fake).collect(0,arm,token_target=1)
            self.assertEqual(len(games),32)
            self.assertEqual(metrics['terminal_games'],32)
            kinds=set(r['kind'] for r in rows)
            self.assertEqual(kinds,{'selfplay'} if arm=='selfplay' else {'B','P','selfplay'})
            json.dumps(dict(rows=rows,units=units,games=games,metrics=metrics))
            again=Collector(self.data,fake).collect(0,arm,token_target=1)
            self.assertEqual(rows,again[0])


if __name__=='__main__':unittest.main()
