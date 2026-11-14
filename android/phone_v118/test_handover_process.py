"""Real local IPC/process/lock test, with a fixture GET-only exchange."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import phone_button_upgrade as u
import phone_handover as h
import phone_service


class Processes(unittest.TestCase):
    def test_serial_worker_exits_before_next_owner_can_take_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'host-v16';old.mkdir();(root/'host-v17').mkdir()
            (root/'runtime-q2x').mkdir()
            script=old/'phone_host.py'
            source=Path(__file__).resolve().parent
            script.write_text('''import sys,os,time,queue,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, SOURCE)
import phone_handover as h
import phone_service as service
from test_handover import fixtures, ReadAPI
root=Path(sys.argv[1])
j,s,a=fixtures()
e=SimpleNamespace(journal=SimpleNamespace(data=j),api=ReadAPI(s,a),commands=queue.Queue(),
 events=queue.Queue(),risk_queue=queue.Queue(),queued_risks=set(),entry_cancel=threading.Event(),
 stop_event=threading.Event(),command_wake=threading.Event(),enabled=True,preview=False,
 user_paused=False,run_requested=True,resume_pending=False,invalidate=Mock(),log=Mock(),handle=Mock())
e.send=lambda action,**kw:e.commands.put((action,kw))
e.journal.save=lambda:h.save_json(root/'runtime-q2x/bot_state.json',e.journal.data)
h.start_watchdog=lambda *a:None  # Recovery watcher is covered separately.
with service.lock(root,'phone_host.lock'):
 e.journal.save()
 h.save_json(root/'before.json',j)
 adapter=h.install(e,root)
 h.save_json(root/'phone_service_status.json',dict(host_pid=os.getpid(),host_process_running=True))
 deadline=time.monotonic()+12
 while not e.stop_event.is_set() and time.monotonic()<deadline:
  adapter.poll()
  while not e.commands.empty():
   action,kw=e.commands.get();e.handle(action,kw)
  time.sleep(.01)
 if not e.stop_event.is_set():raise SystemExit(2)
 h.save_json(root/'reads.json',e.api.calls)
'''.replace('SOURCE',repr(str(source))))
            p=subprocess.Popen([sys.executable,'-B',str(script),str(root)],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not (root/'phone_service_status.json').exists() and time.monotonic()<deadline:
                    if p.poll() is not None:self.fail(p.stderr.read().decode())
                    time.sleep(.01)
                self.assertTrue(phone_service.running(root,'phone_host.lock'))
                ack=u.request_handover(root,old,root/'host-v17')
                self.assertEqual(ack['phase'],'released')
                out,err=p.communicate(timeout=5)
                self.assertEqual(p.returncode,0,err.decode())
                self.assertEqual(h.load(root/'before.json'),h.load(u.journal_path(root)))
                self.assertEqual(h.load(root/'reads.json'),['GET snapshot','GET algos']*2)
                self.assertFalse(phone_service.running(root,'phone_host.lock'))
                with phone_service.lock(root,'phone_host.lock'):pass
                self.assertFalse((root/h.REQUEST).exists())
            finally:
                if p.poll() is None:
                    # Test fixture only; production code never escalates kills.
                    p.terminate();p.wait(timeout=5)


if __name__=='__main__':unittest.main()
