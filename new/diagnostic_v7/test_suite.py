import json
import unittest
from copy import deepcopy
from new.diagnostic_v7.experiment import load,p_request,run_case,summarize,action_score
from new.diagnostic_v7.build import qualify
from training.b_sft.social_named_probe import Names,present,action_call


def completion(name,args,finish='stop'):
    return dict(raw_message=dict(content='Regression answer.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason=finish)

def gold_b(c):
    i=c['task']['input'];q=i['queries'][0];n=Names(i,0)
    return completion('SUBMIT_BELIEFS',dict(judgments=[dict(player=n.players[q['player']],goal=n.goals[q['goal']],**c['gold_judgment'])]))

def action(c,idx):
    name,args=action_call(present(c['task'],0)['legal_actions'][idx])
    return completion(name,args)

class SuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.manifest,cls.cases=load()
    def test_inventory_and_clean_prompts(self):
        self.assertEqual(len(self.cases),32)
        self.assertEqual(len({c['source_parent'] for c in self.cases}),32)
        from collections import Counter
        self.assertEqual(Counter(c['intervention_qualification']['role'] for c in self.cases),{'repair_sensitive':16,'action_control':16})
        for c in self.cases:
            qual=c['intervention_qualification']
            if qual['role']=='repair_sensitive':
                self.assertTrue(qual['gold_disjoint_alternatives'])
                gold=set(c['certificate']['acceptable_action_indices'])
                for v in qual['gold_disjoint_alternatives']:
                    self.assertTrue(gold.isdisjoint(qual['world_reward_sets'][v]))
        labels={c['gold_judgment']['favored'] for c in self.cases}
        self.assertEqual(labels,{'want','neutral','avoid','undetermined'})
        for c in self.cases:
            self.assertFalse(c['task']['input']['imposed_setup'])
            for request in c['requests'].values():
                self.assertNotIn('preset',json.dumps(request).lower())
                self.assertNotIn('imposed',json.dumps(request).lower())
            text=c['requests']['P_clean']['messages'][1]['content']
            for word in ('EVENTS','INITIAL STATE','private observation','Observed player choice','joint_distribution'):
                self.assertNotIn(word,text)
            changed=p_request(c,{'possible_preferences':['want'],'favored':'want'})
            original=p_request(c,c['gold_judgment'])
            self.assertEqual(changed['tools'],original['tools'])
            self.assertEqual(changed['messages'][0],original['messages'][0])
            def strip(r):
                a,b=r['messages'][1]['content'].split('\nSUPPLIED PARTNER JUDGMENT',1)
                return a+'\nRESPONSE INSTRUCTIONS'+b.split('\nRESPONSE INSTRUCTIONS',1)[1]
            self.assertEqual(strip(changed),text)
    def test_recertify_and_native_scores(self):
        for c in self.cases:
            rebuilt=qualify(c)
            self.assertEqual(rebuilt['certificate'],c['certificate'])
            for idx in range(len(c['task']['input']['legal_actions'])):
                s=action_score(c,action(c,idx))
                self.assertEqual(s['status'],'ok')
                self.assertEqual(s['correct'],idx in c['certificate']['acceptable_action_indices'])
    def test_complete_oracle_run_and_failures(self):
        rows=[]
        for c in self.cases:
            actor=c['task']['input']['observer']
            idx=max(range(len(c['task']['teacher']['action_values'])),key=lambda k:c['task']['teacher']['action_values'][k][actor])
            def call(condition,request):return gold_b(c) if condition=='B' else action(c,idx)
            row=run_case(c,call);rows.append(row)
            self.assertTrue(row['B']['correct']);self.assertEqual(row['repair_gain'],0)
            for key in ('O','P_gold','P_model'):self.assertEqual(row[key]['regret'],0)
        s=summarize(rows,32)
        self.assertEqual(s['panels']['all']['B']['correct'],32)
        c=self.cases[0];calls=[]
        def truncated(condition,request):
            calls.append(condition)
            return dict(raw_message={'content':'unfinished'},finish_reason='length')
        r=run_case(c,truncated)
        self.assertEqual(calls,['B','O','P_gold'])
        self.assertEqual(r['P_model']['status'],'blocked_by_truncated')
        self.assertIsNone(r['repair_gain'])
        self.assertFalse(r['B']['correct'])
        self.assertEqual(action_score(c,{'status':'infrastructure_failure'})['status'],'infrastructure_failure')

class RunnerTests(unittest.TestCase):
    def test_full_mock_service_run(self):
        import hashlib,tempfile,sys
        from pathlib import Path
        from unittest.mock import patch
        from new.diagnostic_v7 import experiment
        _,cases=experiment.load();lookup={}
        for c in cases:
            for condition in ('B','O','paired_P'):
                seed=int(hashlib.sha256(f'42:{c["id"]}:0:{condition}'.encode()).hexdigest()[:8],16)
                lookup[seed]=(c,condition)
        class Reply:
            def __init__(self,payload):self.text=json.dumps(payload)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return self.text
        def service(req,timeout):
            body=json.loads(req.data);c,condition=lookup[body['seed']]
            a=c['task']['input']['observer']
            idx=max(range(len(c['task']['teacher']['action_values'])),key=lambda k:c['task']['teacher']['action_values'][k][a])
            comp=gold_b(c) if condition=='B' else action(c,idx)
            return Reply(dict(choices=[dict(message=comp['raw_message'],finish_reason='stop')],usage={}))
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/'result'
            args=['diagnose','--base-url','http://mock/v1','--model','mock','--checkpoint-hash','test-only','--output',str(out)]
            with patch.object(sys,'argv',args),patch.object(experiment,'urlopen',side_effect=service),patch('builtins.print'):
                experiment.main()
            self.assertTrue((out/'COMPLETE.json').exists())
            calls=[json.loads(l) for l in (out/'calls.jsonl').read_text().splitlines()]
            self.assertEqual(len(calls),128)
            from collections import defaultdict
            paired=defaultdict(dict)
            for r in calls:
                if r['condition'].startswith('P_'):paired[r['case_id']][r['condition']]=r['request']
            for pair in paired.values():self.assertEqual(pair['P_gold'],pair['P_model'])
            summary=json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['panels']['repair_sensitive']['paired']['n'],16)

if __name__=='__main__':unittest.main()
