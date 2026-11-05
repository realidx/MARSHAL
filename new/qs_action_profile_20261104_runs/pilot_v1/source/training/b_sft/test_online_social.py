from copy import deepcopy
import unittest

from training.b_sft.online_social import OnlineSocial, run_episode, VERSION
from training.b_sft.social_cases import bundle_fixture
from training.b_sft.social_cases_expand import information_fixture, probe_action
from training.b_sft.social_holdout import topology_id, RECIPES, fixture
from training.b_sft.shared_teacher import native


class OnlineSocialTests(unittest.TestCase):
    def setUp(self): self.raw, self.prefix = information_fixture()

    def test_all_legal_learner_actions_preserve_support_and_finish(self):
        base = OnlineSocial(self.raw, self.prefix); base.ensure_teacher()
        for action in base.game.rules.actions(base.node):
            for world in base.game.worlds:
                env = base.fork(); env.step(action, kind='learner')
                self.assertEqual(env.worlds, base.worlds); self.assertIsNone(env.position)
                env.finish_reference(world)
                self.assertTrue(env.terminal); self.assertIsNone(env.invalid_reason)

    def test_new_partner_evidence_updates_after_off_policy_action(self):
        env = OnlineSocial(self.raw, self.prefix)
        env.step(probe_action(), kind='learner')
        world = env.game.worlds[-1]
        action = env.reference_action(world[env.actor]); env.step(action, kind='partner')
        self.assertEqual(len(env.worlds), 1)
        self.assertTrue(all(x['answer']['possible_preferences'] == ['avoid'] for x in env.belief_table()))
        replayed = OnlineSocial.replay_events(self.raw, env.events, protocol=VERSION)
        self.assertEqual(replayed.worlds, env.worlds)
        self.assertEqual(replayed.node.state.public_state(), env.node.state.public_state())

    def test_legacy_history_cannot_be_silently_treated_as_public_setup(self):
        bad = dict(self.raw, history=[{'action': 'PASS'}])
        with self.assertRaises(ValueError): OnlineSocial(bad)
        with self.assertRaises(ValueError): OnlineSocial.replay_events(self.raw, [], protocol='old')

    def test_unexpected_legal_partner_action_disables_inference_without_reset(self):
        raw, prefix = bundle_fixture(); env = OnlineSocial(raw, prefix)
        env.ensure_teacher(); previous = env.worlds
        env.step({'response': 'ACCEPT'}, kind='partner')
        self.assertEqual(env.worlds, previous)
        self.assertIsNone(env.belief_table()); self.assertIn('incompatible', env.invalid_reason)
        self.assertEqual(env.history[-1], {'response': 'ACCEPT'})
        env.finish_reference(env.game.worlds[0]); self.assertTrue(env.terminal)

    def test_illegal_action_is_atomic(self):
        env = OnlineSocial(self.raw, self.prefix); before = deepcopy(env.history)
        with self.assertRaises(ValueError): env.step({'response': 'ACCEPT'}, kind='learner')
        self.assertEqual(env.history, before); self.assertEqual(env.worlds, env.game.worlds)

    def test_teacher_budget_failure_finishes_but_never_scores_fake_gold(self):
        env = OnlineSocial(self.raw, self.prefix, max_nodes=1)
        self.assertFalse(env.ensure_teacher()); self.assertIsNone(env.belief_table())
        score = env.score_b([dict(**q, possible_preferences=['avoid'], favored='avoid') for q in env.context()['queries']])
        self.assertFalse(score['mask']); self.assertIsNone(score['score']); self.assertTrue(score['format_valid'])
        env.finish_reference(env.game.worlds[0]); self.assertTrue(env.terminal)
        self.assertIsNotNone(env.invalid_reason)

    def test_p_reference_budget_and_scope(self):
        env = OnlineSocial(self.raw, self.prefix)
        unavailable = env.p_reference_values(max_rollouts=1)
        self.assertFalse(unavailable['mask']); self.assertIsNone(unavailable['values'])
        values = env.p_reference_values(max_rollouts=40, seconds=5)
        self.assertTrue(values['mask']); self.assertIn('NOT an on-policy advantage', values['scope'])
        self.assertEqual(next(r['value'] for r in values['values'] if r['action'] == probe_action()), 1.5)

    def test_terminal_own_values_survive_unavailable_b(self):
        prefix=[dict(action='PASS') for _ in range(5)]
        prefix.append(dict(action='OFFER',partner_id=0,proposer_action=[1],partner_action=[1,0]))
        last=OnlineSocial(self.raw,prefix)
        clean=last.p_reference_values();last.fragile=True
        result=last.p_reference_values()
        self.assertTrue(result['mask']);self.assertFalse(result['others_mask'])
        self.assertEqual(result['basis'],'direct_terminal')
        self.assertEqual([x['value'] for x in result['values']],[x['value'] for x in clean['values']])
        self.assertTrue(all(x['others_value'] is None for x in result['values']))

    def test_wrong_b_is_not_repaired_or_allowed_to_change_gold(self):
        wrong = [dict(player=1, goal=0, possible_preferences=['avoid'], favored='avoid')]
        observed = []
        def p(ctx):
            observed.append(ctx['model_beliefs']); return ctx['legal_actions'][-1]
        env = OnlineSocial(self.raw, self.prefix)
        e = run_episode(self.raw, self.prefix, env.game.worlds[0], lambda ctx: wrong, p)
        self.assertTrue(all(x == wrong for x in observed)); self.assertTrue(e['usable_for_training'])
        self.assertLess(e['records'][0]['B_score']['score'], 0)
        self.assertFalse(e['actual_LM'])

    def test_topology_ignores_goal_ids_players_and_timing(self):
        raw, _ = fixture(RECIPES[0]); changed = deepcopy(raw); g = changed['game']; n = g['n_players']
        for goal in g['goals']:
            for a in goal['required_actions']:
                a['player_id'] = n-1-a['player_id']; a['action_id'] = 1-a['action_id']
        g['goals'].reverse(); g['round_robin'].reverse(); g['menu_enabled'] = True
        self.assertEqual(topology_id(raw), topology_id(changed))


if __name__ == '__main__': unittest.main()
