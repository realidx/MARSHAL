from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from training.b_sft.assemble_dataset import assemble,validate


class AssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.out=Path(cls.temp.name)/'bundle'
        cls.summary=assemble([], [Path(__file__).parent/'fixtures/evidence_switch_regression.json'],cls.out)
        def rows(name):return [json.loads(l) for l in (cls.out/name).read_text().splitlines()]
        cls.r=rows('decisions.jsonl');cls.g=rows('gold.jsonl');cls.l=rows('links.jsonl');cls.games=rows('games.jsonl')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_complete_schema_and_true_episode(self):
        validate(self.r,self.g,self.l,self.games)
        self.assertEqual(self.summary['structures'],1)
        self.assertEqual(self.summary['links'],{'contrast':1})
        self.assertEqual(self.summary['episodes'],{'terminal':1})
        self.assertFalse(self.summary['training_ready'])
        self.assertEqual({r['split'] for r in self.r},{'development'})

    def test_contrast_cannot_be_temporal(self):
        links=deepcopy(self.l);links[0]['kind']='temporal'
        with self.assertRaisesRegex(ValueError,'Temporal'):validate(self.r,self.g,links,self.games)

    def test_query_leakage_and_optimality_validation(self):
        for kind in ('query','leak','opt'):
            records=deepcopy(self.r);gold=deepcopy(self.g)
            if kind=='query':records[0]['input']['queries']=[]
            elif kind=='leak':records[0]['input']['q']=[]
            else:gold[0]['P']['optimal_actions']=[]
            with self.assertRaises(ValueError):validate(records,gold,self.l,self.games)

    def test_preserve_output(self):
        with self.assertRaisesRegex(ValueError,'Output exists'):assemble([],[],self.out)


if __name__=='__main__':unittest.main()
