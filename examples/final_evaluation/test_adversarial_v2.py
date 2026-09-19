import unittest,tempfile,random,json
from pathlib import Path
from training.social_mixed.core import Episode
from examples.final_evaluation.adversarial_suite import load
from examples.final_evaluation.adversarial_runtime import play,scripted,SEED

class V2(unittest.TestCase):
    def test_shared_q0_requests_and_scores(self):
        _,rows=load();reset=rows[0];traces=[];scores=[]
        with tempfile.TemporaryDirectory() as tmp:
            for seat in range(3):
                root=Path(tmp)/str(seat);root.mkdir()
                shadow=Episode(reset,reset['id'],0,SEED);rng=random.Random(77);seen=[]
                def generate(route,request):
                    self.assertEqual(request,shadow.request());seen.append(request)
                    response=scripted(shadow,rng);shadow.accept(response);return response
                scores.append(play(reset,seat,0,{'q0':{},'focal':{}},root,generate,seat==0))
                traces.append(seen)
        self.assertEqual(traces[0],traces[1]);self.assertEqual(traces[1],traces[2])
        self.assertEqual(len(scores[0]),3)
        for seat in (1,2):self.assertEqual(scores[0][seat]['focal_utility'],scores[seat][0]['focal_utility'])
    def test_witnesses_replay(self):
        from examples.final_evaluation.adversarial_suite import DEFAULT
        from training.social_mixed import policy_prompt
        _,rows=load();proof=json.loads((DEFAULT/'witnesses.json').read_text())
        count=0
        for r in rows:
            for seat,paths in enumerate(proof[r['id']]['per_seat']):
                self.assertNotEqual(paths[0]['utility'],paths[1]['utility'])
                for path in paths:
                    ep=Episode(r,r['id'],0,SEED)
                    for action in path['actions']:
                        native=next(a for a in ep.rules.actions(ep.node) if a.to_dict()==action)
                        ep.node=ep.rules.step(ep.node,native,realized_world=ep.world)
                    self.assertTrue(ep.node.state.is_terminal)
                    self.assertAlmostEqual(ep.rules.terminal_payoffs(ep.node,ep.world)[seat],path['utility']);count+=1
        self.assertEqual(count,96)
if __name__=='__main__':unittest.main()
