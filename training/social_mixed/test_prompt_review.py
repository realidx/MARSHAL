"""Regression checks for reviewed request routing, privacy and P4 coverage."""
import copy
import json
import unittest
from pathlib import Path
from training.social_mixed.current_train_probe import load_bp,PACK
from training.b_sft.social_named_probe import request,present
from training.b_sft.review_prompt import chronology
from training.b_sft.social_bp_training import reward,native_completion
from training.social_mixed.core import Episode
ROOT=Path(__file__).resolve().parents[2]
class PromptReviewTests(unittest.TestCase):
 def test_reviewed_requests_and_p4_closed_links(self):
  m,rows,_=load_bp();self.assertEqual(len(rows),69)
  p4=[t for t in rows if t['probe_kernel']=='P4'];self.assertEqual(len(p4),16)
  self.assertEqual(sum(bool(t.get('probe_diagnostic_only')) for t in p4),1)
  ids={t['id'] for t in p4}
  for link in json.loads((PACK/'p4_links.json').read_text()):self.assertTrue({link['parent'],*link['children']}<=ids)
 def test_all_candidate_requests_keep_gold_outside_prompt(self):
  rows=map(json.loads,(ROOT/'examples/social_bp/p4_information_core_v1/bp_candidate_tasks.jsonl').read_text().splitlines())
  for t in rows:
   for variant in (0,1):
    r=request(t,'action_tools',variant);self.assertIn('GOAL REQUIREMENTS BY PLAYER',r['messages'][1]['content'])
    changed=copy.deepcopy(t);changed['teacher']={'secret':'DO_NOT_DISCLOSE'};changed['kernel']='DO_NOT_DISCLOSE'
    self.assertEqual(r,request(changed,'action_tools',variant))
 def test_plain_language_in_actual_requests(self):
  _,rows,_=load_bp()
  for t in rows:
   r=request(t,'action_tools',t.get('name_variant',0));text=' '.join(m['content'] for m in r['messages'])
   for term in ('expected final score','score ties','uniformly at random','not a state snapshot','HOW PREFERENCES ARE DRAWN','Do not take a game action','A true revealed value','top support is tied','Compare the observed voluntary behavior'):
    self.assertNotIn(term,text)
   modes={g['binary'] for g in t['input']['game']['goals']}
   if modes=={False}:self.assertNotIn('BINARY',text)
   if modes=={True}:self.assertNotIn('LINEAR',text)
   if t['task']=='B':self.assertEqual([x['function']['name'] for x in r['tools']],['SUBMIT_BELIEFS'])
 def test_accept_and_reject_states_are_separate(self):
  _,rows,_=load_bp()
  for t in rows:
   v=present(t,t.get('name_variant',0));text='\n'.join(chronology(v))
   if any(e.get('action')=='OFFER' for e in v['history']):self.assertIn('BEFORE this offer',text)
   if any('response' in e for e in v['history']):self.assertIn('AFTER this response',text)
   self.assertEqual(reward(t,native_completion(t))['reward'],1)
 def test_selfplay_private_world_does_not_leak(self):
  resets=map(json.loads,(ROOT/'examples/social_mixed/selfplay_audit_v2/probe_resets.jsonl').read_text().splitlines())
  for r in resets:
   ep=Episode(r,r['id'],0,42);actor=ep.rules.actor(ep.node);req=ep.request()
   alternatives=[w for w in ep.rules.worlds if w[actor]==ep.world[actor] and w!=ep.world]
   if alternatives:
    ep.world=alternatives[0];self.assertEqual(ep.request(),req)
   text=req['messages'][1]['content'];self.assertIn('Their choices are not guaranteed to be optimal',text)
   self.assertNotIn('HOW OTHER PLAYERS CHOOSE',text)
   self.assertIn('Briefly explain',text);self.assertIn('PREFERENCE CONDITIONS',text)
if __name__=='__main__':unittest.main()
