"""Pre-attempt flag errors share the native output deadline."""
import os,subprocess,unittest
class FlagStderrDeadline(unittest.TestCase):
 def test_flag_error_on_full_stderr_terminates_within_remote_budget(self):
  binary=os.environ.get('MEMCUE_BIN')
  if not binary:self.skipTest('native binary required')
  env=dict(os.environ,MEMCUE_POSTGRES_DSN='postgres://127.0.0.1:1/synthetic?sslmode=disable',MEMCUE_DREAM_BACKGROUND='0')
  r,w=os.pipe();os.set_blocking(w,False)
  try:
   while True:os.write(w,b'x'*4096)
  except BlockingIOError:pass
  os.set_blocking(w,True);completed=True
  child=subprocess.Popen([binary,'correct','-not-a-supported-flag'],env=env,stdout=subprocess.DEVNULL,stderr=w)
  try:
   try:child.wait(timeout=5.3)
   except subprocess.TimeoutExpired:completed=False;child.kill();child.wait(timeout=2)
  finally:os.close(r);os.close(w)
  self.assertTrue(completed,'flag diagnostic blocked outside aggregate deadline')
  self.assertNotEqual(child.returncode,0)
if __name__=='__main__':unittest.main()
