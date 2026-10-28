"""Check information boundaries and timing in the readable model input."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from training.b_sft import social_named_probe as named, social_prompt as prompt
from training.b_sft.prepare_named_bridge_probe import qualitative_tasks, acquisition_tasks


class ReadablePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tasks = [json.loads(x) for x in Path(
            'new/local_data/social_runs/bp_no_catalogue_probe_v4/tasks.jsonl').read_text().splitlines()]
        tasks += list(qualitative_tasks()) + list(acquisition_tasks())
        cls.tasks = {t['source']: t for t in tasks}

    def test_private_truth_and_supplied_certainty_are_current_known_facts(self):
        for source in ('private_result_avoid', 'qualitative_avoid_certain_0'):
            v = named.present(self.tasks[source])
            facts = prompt.preference_facts(v)
            match = [f for f in facts if (f['player'], f['goal']) == ('Blair', 'Orchard')]
            self.assertEqual(len(match), 1)
            self.assertEqual(match[0]['preference'], 'avoid')
            self.assertNotIn('public to everyone', match[0]['sources'])
            self.assertIn('known in your supplied current belief', match[0]['sources'])
            if source == 'private_result_avoid':
                self.assertIn('true investigation answer delivered privately to you', match[0]['sources'])
            rendered = prompt.render(v, 'P', self.tasks[source]['skill'])
            self.assertIn('Preferences you have not determined: none.', rendered)
            if source == 'private_result_avoid':
                self.assertIn('Your investigation revealed that Blair wants to avoid Orchard. The answer was shown only to you.', rendered)
            else:
                self.assertIn('You know that Blair wants to avoid Orchard.', rendered)
        v['your_private_investigation_answers'] = {'Blair': {'Orchard': 'want'}}
        with self.assertRaises(ValueError):
            prompt.preference_facts(v)

    def test_renaming_preserves_private_answer_owner_and_target(self):
        t = self.tasks['private_result_avoid']
        for variant in (0, 1):
            v = named.present(t, variant)
            names = named.Names(t['input'], variant)
            self.assertEqual(v['you'], names.players[t['input']['player']])
            for fact in t['input']['private_results']:
                expected = (names.players[fact['player']], names.goals[fact['goal']], fact['preference'])
                matches = [(f['player'], f['goal'], f['preference']) for f in prompt.preference_facts(v)
                           if 'true investigation answer delivered privately to you' in f['sources']]
                self.assertIn(expected, matches)

    def test_history_distinguishes_proposal_from_acceptance_and_rejection(self):
        for response in ('accept', 'reject'):
            v = named.present(self.tasks['one_response_' + response])
            text = prompt.render_history(v)
            self.assertIn('Starting event provided by the task: Alex proposes to Blair', text)
            self.assertIn('This proposal alone binds nothing.', text)
            self.assertIn('Blair chose to ' + response, text)
            if response == 'accept':
                self.assertIn('New binding commitments: Alex: Cedar; Blair: Cedar.', text)
            else:
                self.assertIn('No proposed additions become binding.', text)

    def test_other_players_query_has_no_private_answer_in_public_history(self):
        v = named.present(self.tasks['three_player_4_maintain'])
        self.assertEqual(v['your_private_investigation_answers'], {})
        text = prompt.render_history(v)
        self.assertIn('The answer is delivered privately to', text)
        self.assertNotIn('preference: want', text)
        self.assertNotIn('preference: avoid', text)
        self.assertNotIn('preference: neutral', text)

    def test_investigation_root_and_deadline_show_correct_future_opportunities(self):
        for source, count in [('investigate_acquisition_root', 1), ('acquisition_same_game_last_turn', 0)]:
            t = self.tasks[source]
            for variant in (0, 1):
                req = named.request(t, 'action_tools', variant)
                self.assertIn(f'Your proposal opportunities AFTER the current opportunity: {count}.',
                              req['messages'][-1]['content'])
                self.assertIn('INVESTIGATE', [x['function']['name'] for x in req['tools']])

    def test_available_additions_exclude_existing_and_forbidden_commitments(self):
        v = named.present(self.tasks['complete_own_gain'])
        v['binding_commitments']['Alex'] = ['Cedar']
        v['forbidden_commitments'] = {'Alex': ['Maple'], 'Blair': []}
        text = prompt.render(v, 'P', 'planning')
        additions = text.split('Commitment options still available to add (not yet binding):')[1].split('Forbidden commitments:')[0]
        self.assertIn('- Alex: none.', additions)
        self.assertIn('- Blair: Cedar.', additions)

    def test_teacher_labels_and_internal_task_names_cannot_affect_requests(self):
        for t in self.tasks.values():
            original = named.request(t, 'action_tools')
            changed = deepcopy(t)
            changed['teacher'] = {'do_not_disclose': 'SECRET_TEACHER_MARKER'}
            changed['source'] = 'SECRET_SOURCE_MARKER'
            changed['skill'] = 'SECRET_SKILL_MARKER'
            self.assertEqual(original, named.request(changed, 'action_tools'))
            text = json.dumps(original)
            for forbidden in ('action_id', 'type_catalogues', 'policy_sha256', 'action_values',
                              'audit_envelopes', 'per_world_payoffs', 'last_turn_do_not_investigate',
                              'Task: B', 'Task: P', 'imposed', 'voluntary', 'Source:',
                              'Alex.Cedar', 'Blair.Cedar', 'numerical confidence', 'checkpoint',
                              'already-known or irrelevant', 'synchronous best-response',
                              'uniform initialization', 'small teaching game'):
                self.assertNotIn(forbidden, text)

    def test_goals_keep_every_owner_under_both_name_mappings(self):
        for t in self.tasks.values():
            for variant in (0, 1):
                v = named.present(t, variant)
                text = prompt.render(v, t['task'], t['skill'])
                for goal, condition in v['goals'].items():
                    line = next(s for s in text.splitlines() if s.startswith(f'- {goal} requires '))
                    for requirement in condition['ALL_OF']:
                        owner, commitment = requirement.split('.')
                        self.assertIn(f'{owner} to commit to {commitment}', line)

    def test_unreviewed_policy_or_prior_cannot_be_silently_overwritten(self):
        with self.assertRaises(ValueError):
            prompt.partner_rules('Partners always accept.')
        with self.assertRaises(ValueError):
            prompt.generation_rules('All unknown preferences are want.')
        with self.assertRaises(ValueError):
            prompt.belief_description('A new kind of joint constraint.')


if __name__ == '__main__':
    unittest.main()
