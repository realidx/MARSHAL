"""Native action equivalence, information isolation, and September interface."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from .named_prompt import request,calls_for,VERSION,canonical,check_independent_preferences
from .common import decode,request as versioned_request
from examples.strategic_slices.export_terminal_prompt_preview import rebuild


class NamedPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=Path(__file__).resolve().parents[2]/'examples/strategic_slices/versions/terminal_v7_named_20261017/input_fixtures.json'
        cls.cases=json.loads(p.read_text())
    def test_all_actions_roundtrip_and_no_silent_legacy_acceptance(self):
        for case in self.cases:
            rules,node,world=rebuild(case['raw'],case['visible']);mapping=calls_for(rules,node)
            for i,(name,args) in enumerate(mapping):
                output=dict(completion=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))])))
                self.assertEqual(decode(output,rules.actions(node),mapping),(i,'ok'))
                output['completion']['raw_message']['tool_calls'][0]['function']=dict(name='act',arguments='{"action_index":0}')
                self.assertEqual(decode(output,rules.actions(node),mapping)[1],'invalid_action')
    def test_existing_commitments_are_not_repeated_as_new_additions(self):
        case=next(c for c in self.cases if c['label']=='terminal_existing_commitments')
        rules,node,_=rebuild(case['raw'],case['visible']);name,args=calls_for(rules,node)[1]
        self.assertEqual(name,'OFFER');self.assertEqual(args['self_commitments'],[])
        self.assertEqual(args['partner_commitments'],['Cedar'])
    def test_hidden_world_does_not_change_prompt_with_same_own_information(self):
        case=self.cases[0];rules,node,world=rebuild(case['raw'],case['visible']);actor=rules.actor(node)
        others=[w for w in rules.worlds if w[actor]==world[actor]]
        self.assertGreater(len(others),1)
        expected=request(rules,node,world,42,remaining_decisions=2)
        for w in others:self.assertEqual(request(rules,node,w,42,remaining_decisions=2),expected)
    def test_output_contract_and_current_scientific_objective(self):
        for case in self.cases:
            rules,node,world=rebuild(case['raw'],case['visible']);req=request(rules,node,world,42,remaining_decisions=2)
            text=req['messages'][1]['content']
            self.assertIn('GOAL REQUIREMENTS BY PLAYER',text);self.assertIn('EVENTS IN ORDER',text)
            self.assertIn('You will choose at most 2 more decisions',text)
            self.assertIn('Briefly explain',text.split('RESPONSE INSTRUCTIONS')[-1])
            self.assertNotIn('action_index',json.dumps(req));self.assertNotIn('0.1 goal',text)
            self.assertNotIn('choose whichever helps',text)
            for hidden in ('root_Q','world_index','oracle_step'):self.assertNotIn(hidden,json.dumps(req))
            if case['visible']['pending_offer']:self.assertIn('must accept or reject',text)
            self.assertEqual(req,versioned_request(rules,node,world,42,remaining_decisions=2,prompt_version=VERSION))
    def test_preference_facts_preserved_without_provenance(self):
        from .named_prompt import visible
        from training.social_mixed.frozen.bp_display import preference_facts
        for case in self.cases:
            rules,node,world=rebuild(case['raw'],case['visible'])
            _,v,_=visible(rules,node,world[rules.actor(node)])
            expected={(f['player'],f['goal'],f['preference']) for f in preference_facts(v)}
            text=request(rules,node,world,42)['messages'][1]['content']
            area=text.split('PUBLIC PREFERENCES\n',1)[1].split('BACKGROUND PREFERENCE DISTRIBUTION',1)[0]
            actual={tuple(c.strip() for c in line.strip('|').split('|')) for line in area.splitlines()
                if line.startswith('|') and line.strip('|').split('|')[-1].strip() in ('want','neutral','avoid')}
            self.assertEqual(actual,expected)
            for label in ('Who knows','your own preference','true investigation answer',
                    'The answer was delivered only to','PUBLIC PREFERENCE SUPPORT','certified','DECISION OBJECTIVE'):
                self.assertNotIn(label,text)
    def test_both_scoring_definitions_are_in_game_rules(self):
        case=self.cases[0];rules,node,world=rebuild(case['raw'],case['visible'])
        text=request(rules,node,world,42)['messages'][1]['content']
        rules_text=text.split('GAME RULES',1)[1].split('GOAL REQUIREMENTS BY PLAYER',1)[0]
        self.assertIn('BINARY goal, completion is 1',rules_text)
        self.assertIn('LINEAR goal, completion is the fraction',rules_text)
        self.assertIn('1 of 2 required commitments gives completion 0.5',rules_text)
    def test_correlated_catalogues_cannot_get_independent_wording(self):
        from types import SimpleNamespace
        rules=SimpleNamespace(catalogues={0:((-1,-1),(0,0),(1,1))})
        with self.assertRaisesRegex(ValueError,'joint restrictions'):check_independent_preferences(rules)
    def test_v7_full_previews_still_reproduce_exactly(self):
        from .named_prompt import V7
        folder=Path(__file__).resolve().parents[2]/'examples/strategic_slices/versions/terminal_v7_named_20261017'
        for case in self.cases:
            expected=json.loads((folder/(case['label']+'.json')).read_text())
            rules,node,world=rebuild(case['raw'],case['visible'])
            req=versioned_request(rules,node,world,expected['seed'],prompt_version=V7,
                remaining_decisions=case['visible']['evaluation_window']['remaining_controlled_decisions'])
            req.update({k:expected[k] for k in ('max_tokens','top_p','top_k','repetition_penalty','tool_choice','parallel_tool_calls')})
            self.assertEqual(req,expected)
    def test_reject_duplicate_commitments_extra_arguments_and_multiple_calls(self):
        case=self.cases[0];rules,node,_=rebuild(case['raw'],case['visible']);mapping=calls_for(rules,node)
        name,args=next(c for c in mapping if c[0]=='OFFER');args=dict(args,unexpected=True)
        output=dict(completion=dict(raw_message=dict(tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))])))
        self.assertEqual(decode(output,rules.actions(node),mapping)[1],'invalid_action')
        with self.assertRaises(ValueError):canonical('OFFER',dict(self_commitments=['Cedar','Cedar']))
        output['completion']['raw_message']['tool_calls']*=2
        self.assertEqual(decode(output,rules.actions(node),mapping)[1],'invalid_action')


if __name__=='__main__':unittest.main()
