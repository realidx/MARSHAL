"""Exercise new probe collection and summaries without any HTTP/model calls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from training.social_mixed import distribution_probe as module
from training.social_mixed.distribution_sampling import select
from training.social_mixed.core import load_data
from training.social_mixed.test_core import generated

class DistributionProbeTests(unittest.TestCase):
 def test_validation_sampler_handles_retained_p4(self):
  rows=select(load_data()['bp_validation'],0,42,validation=True)
  self.assertEqual({t['kernel'] for t in rows},{'B1','B2','B3','P1','P2','P3','P4'})
 def test_real_stage_summaries_without_network(self):
  m,bp,sp=module.load()
  def fake(url,name,request):
   names=[t['function']['name'] for t in request['tools']]
   return generated('PASS' if 'PASS' in names else 'REJECT' if 'REJECT' in names else names[0],{})
  for stage in ('bp','sp'):
   with tempfile.TemporaryDirectory() as d:
    out=Path(d)/stage
    argv=['probe','--stage',stage,'--learner-url','http://unused','--opponent-url','http://unused','--output',str(out)]
    with patch.object(module,'load',return_value=(m,[bp[0],next(t for t in bp if t['split']=='validation')],sp[:2])),patch.object(sys,'argv',argv),patch.object(module.probe,'load'),patch.object(module.selfplay_probe,'load'),patch.object(module.probe,'complete',side_effect=fake),patch.object(module.selfplay_probe,'complete',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
     module.main()
    self.assertTrue((out/'COMPLETE.json').is_file())
    if stage=='bp':
     summary=json.loads((out/'stratified_summary.json').read_text());self.assertEqual(len(summary),2)
     self.assertEqual(len((out/'bp.jsonl').read_text().splitlines()),16)
    else:
     self.assertFalse((out/'bp.jsonl').exists())
     self.assertEqual(json.loads((out/'summary.json').read_text())['terminal'],8)
if __name__=='__main__':unittest.main()
