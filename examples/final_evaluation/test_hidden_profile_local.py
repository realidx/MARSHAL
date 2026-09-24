import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from examples.final_evaluation.hidden_profile_local import config,prepare,execute

class HiddenProfileTests(unittest.TestCase):
    def test_only_model_transport_changed(self):
        original,current=config('q0','http://localhost:8000/v1')
        for key in original:
            if key!='agents':self.assertEqual(original[key],current[key])
        for a,b in zip(original['agents'],current['agents']):
            self.assertEqual(a['id'],b['id']);self.assertEqual(a['role'],b['role'])
            self.assertEqual(a['model']['temperature'],b['model']['temperature'])
            self.assertEqual(b['model']['name'],'openai/q0')
        self.assertEqual(current['task']['phase_rules']['correct_answer'],'Candidate C')

    def test_prepare_native_schema_and_repetitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run'
            jobs=prepare(path,'q0','http://localhost:8000/v1',2)
            self.assertEqual(len(jobs),2)
            self.assertFalse((path/'COMPLETE').exists())
            manifest=json.loads((path/'manifest.json').read_text())
            self.assertTrue(manifest['repetitions_are_not_independent_task_instances'])
            for job in jobs:
                self.assertEqual({d['path'] for d in job['changes']},{'agents','logging.output_dir'})
            with patch.dict('os.environ',{'COLLABSIM_MODEL_TEMPERATURE':'1'}):
                with self.assertRaises(ValueError):execute(path,jobs)

if __name__=='__main__':unittest.main()
