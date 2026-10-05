import threading,unittest,json,tempfile,shutil,io
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout
from training.strategic_slices.test_terminal_d import TerminalDTests
from training.strategic_slices.terminal_d import run_refill,TerminalRollout,mock_generate,run_evaluation,make_protocol
from training.strategic_slices.common import write_json,digest,file_hash
class Tests(unittest.TestCase):
 def test_refill_does_not_wait_for_slowest(self):
  release=threading.Event();started=threading.Event();errors=[]
  class Job:
   def __init__(self,n):self.n=n;self.status='running'
   def request(self,cfg):return self.n
   def accept(self,ans,req):self.status='terminal'
  def generate(reqs):
   n=reqs[0]
   if n==0:
    if not release.wait(5):raise RuntimeError('slow request never released')
   if n==2:started.set()
   return [n]
  def runner():
   try:run_refill([Job(i) for i in range(4)],{'workers':2},generate)
   except Exception as e:errors.append(e)
  t=threading.Thread(target=runner);t.start()
  try:self.assertTrue(started.wait(3),'third request must start while first is blocked')
  finally:release.set();t.join(6)
  self.assertFalse(t.is_alive());self.assertFalse(errors)
 def test_trajectory_semantics_and_resume(self):
  TerminalDTests.setUpClass();tree=TerminalDTests.tree;rows=TerminalDTests.rows;cfg=dict(TerminalDTests.cfg,workers=16);cfg.pop('scheduler',None)
  oldjobs=[TerminalRollout(tree,r,i,42) for r in rows for i in range(2)]
  newjobs=[TerminalRollout(tree,r,i,42) for r in rows for i in range(2)]
  for j in oldjobs:
   while j.status=='running':req=j.request(cfg);j.accept(mock_generate([req])[0],req)
  run_refill(newjobs,dict(cfg,workers=32),mock_generate)
  self.assertEqual([j.record() for j in oldjobs],[j.record() for j in newjobs])
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);write_json(root/'manifest.json',{'fixture':True});data=SimpleNamespace(root=root,parents={'fixture':{'players':2}},candidates=rows,reference=lambda _:tree);out=root/'out';identity={'mock':True,'model':None}
   with redirect_stdout(io.StringIO()):run_evaluation(data,cfg,out,mock_generate,identity)
   old=json.loads((out/'protocol.json').read_text());cfg2=dict(cfg,workers=32,scheduler='completion-refill-v1');new=make_protocol(data,cfg2,identity,['fixture'])
   parent=out/'parents/fixture.json';before=parent.read_bytes()
   shutil.copytree(out/'source',out/'legacy_source')
   write_json(out/'EXECUTION_MIGRATION.json',{'old_protocol':old,'old_protocol_sha256':digest(old),'new_protocol_sha256':digest(new),'inherited_parents':{'fixture.json':file_hash(parent)}});write_json(out/'protocol.json',new)
   def forbidden(reqs):raise AssertionError('Inherited complete parent called generator')
   with redirect_stdout(io.StringIO()):summary=run_evaluation(data,cfg2,out,forbidden,identity,resume=True)
   self.assertEqual(before,parent.read_bytes());self.assertEqual(summary['parents'],1)
   with self.assertRaisesRegex(ValueError,'Resume protocol'):
    run_evaluation(data,dict(cfg2,max_tokens=1024),out,forbidden,identity,resume=True)
if __name__=='__main__':unittest.main(verbosity=2)
