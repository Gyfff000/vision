import ast
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"K230_competition"
sys.path.insert(0,str(ROOT))
import config
import workflow
import vision_core as core
import vision_app as app

TASK="156+123+516+231"
def ready():
    w=workflow.Workflow(15)
    for _ in range(3): w.observe(TASK,core.crc16)
    return w

class WorkflowTests(unittest.TestCase):
    def test_invalid_tasks_and_interruption_do_not_lock(self):
        for raw in (None,"Good","111+123+111+123","156+113+516+231","156+123+513+231","156+123+516+230"):
            w=workflow.Workflow(); self.assertFalse(w.observe(raw,core.crc16)); self.assertEqual(w.state,"SCAN")
        w=workflow.Workflow(); w.observe(TASK,core.crc16); w.observe(TASK,core.crc16)
        w.observe(None,core.crc16); self.assertFalse(w.observe(TASK,core.crc16))

    def test_full_plan_and_same_color_stack(self):
        w=ready(); self.assertEqual(w.state,"WAIT_ACK")
        self.assertEqual([s['slot'] for s in w.plan[-3:]],[2,1,3])
        with self.assertRaises(ValueError):w.acknowledge(w.token+1)
        w.acknowledge(w.token); self.assertEqual(w.mode(),"COLOR")
        for step in range(24):
            with self.assertRaises(ValueError):w.confirm_step(w.token,step+1)
            w.confirm_step(w.token,step)
            w.confirm_step(w.token,step)
            self.assertEqual(w.step,step+1)
        self.assertEqual(w.state,"RETURN_HOME")
        self.assertEqual((w.grabs,w.places),(12,12))
        w.complete_home(w.token);self.assertEqual(w.state,"COMPLETE")

    def test_no_color_before_ack_and_stale_task_after_reset(self):
        w=ready(); packets,locate=app.command(w,1,"COLOR",[],1)
        self.assertFalse(locate); self.assertIn(b"NOT_RUNNING",packets[0])
        self.assertIn(b"BAD_ARGS",app.command(w,1,"TASK_ACK",["abc*"],1)[0][0])
        token=w.token; w.reset()
        for _ in range(3):w.observe(TASK,core.crc16)
        self.assertNotEqual(token,w.token)
        self.assertIn(b"TASK_MISMATCH",app.command(w,2,"TASK_ACK",[str(token)],2)[0][0])

    def test_ack_retry_and_pause_do_not_advance(self):
        w=ready(); token=str(w.token)
        app.command(w,1,"TASK_ACK",[token],1); app.command(w,2,"TASK_ACK",[token],2)
        self.assertEqual(w.step,0)
        app.command(w,3,"STOP",[],3)
        self.assertIn(b"STEP_MISMATCH",app.command(w,4,"STEP",[token,"0"],4)[0][0])
        app.command(w,5,"RESUME",[],5); self.assertEqual(w.state,"RUN")

    def test_phase_command_cannot_select_wrong_mode_or_plane(self):
        w=ready(); w.acknowledge(w.token)
        self.assertIn(b"WRONG_MODE",app.command(w,1,"RING",[],1)[0][0])
        self.assertIn(b"BAD_PROFILE",app.command(w,1,"COLOR",["STACK"],1)[0][0])
        self.assertTrue(app.command(w,1,"COLOR",["RAW"],1)[1])

class InstallerTests(unittest.TestCase):
    def test_complete_release_then_switch_and_repeat(self):
        spec=importlib.util.spec_from_file_location("flow_installer",ROOT/"install.py")
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            root=Path(temp);(root/'main.py').write_text('# factory')
            m.install(root.as_posix()); launch=(root/'main.py').read_text()
            self.assertIn('flow_001',launch)
            self.assertEqual((root/'vision_backup/main.py.flow_001.bak').read_text(),'# factory')
            for name in m.FILES:
                source=(root/'vision_releases/flow_001'/name).read_text(encoding='utf-8')
                compile(source,name,'exec')
            m.QR_CAMERA='USB';m.install(root.as_posix())
            self.assertIn('flow_002',(root/'main.py').read_text())
            self.assertTrue((root/'vision_releases/flow_001/vision_app.py').exists())
            ns={};exec((root/'vision_releases/flow_002/config.py').read_text(encoding='utf-8'),ns)
            self.assertEqual(ns['QR_CAMERA'],'USB')

    def test_failed_release_write_keeps_original_startup(self):
        spec=importlib.util.spec_from_file_location("fail_installer",ROOT/'install.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        real=m.checked_write
        def fail(path,source):
            if path.endswith('workflow.py'):raise OSError('simulated full SD')
            return real(path,source)
        m.checked_write=fail
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            root=Path(temp);(root/'main.py').write_text('# factory')
            with self.assertRaises(OSError):m.install(root.as_posix())
            self.assertEqual((root/'main.py').read_text(),'# factory')

class CrossLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=ROOT.parent,prefix='flow-test-')
        cls.exe=Path(cls.temp.name)/'controller.exe'
        gcc=shutil.which('gcc') or 'D:/w64devkit/w64devkit/bin/gcc.exe'
        subprocess.run([gcc,'-std=c99','-Wall','-Wextra','-Werror','-I',str(ROOT/'stm32'),
                        str(ROOT/'stm32/vision_client.c'),str(ROOT/'stm32/competition_controller.c'),
                        str(Path(__file__).parent/'controller_harness.c'),'-o',str(cls.exe)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.proc=subprocess.Popen([str(self.exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        self.addCleanup(self.close_process)
        self.now=0
        seq,kind,args=self.request(self.exchange('B 0'))
        self.assertEqual(kind,'RESET')
        self.rx(core.wire_frame(seq,'ACK','RESET')+core.wire_frame(seq,'DONE',0,0))
        self.tick()
    def close_process(self):
        if self.proc.poll() is None:self.proc.terminate()
        self.proc.wait(timeout=5)
        self.proc.stdin.close();self.proc.stdout.close()
    def exchange(self,line):
        self.proc.stdin.write(line+'\n');self.proc.stdin.flush();out=[]
        while True:
            raw=self.proc.stdout.readline()
            if raw=='':raise RuntimeError('harness exited')
            value=raw.strip()
            if value=='END':return out
            if not value:continue
            out.append(value)
    def rx(self,packet):return self.exchange('R '+packet.hex())
    def tick(self,delta=10):
        self.now+=delta;return self.exchange('T '+str(self.now))
    def request(self,out):
        tx=next(s[3:] for s in out if s.startswith('TX '))
        return core.FrameParser().feed((tx+'\n').encode())[0]
    def test_full_24_step_controller_with_real_crc_exchange(self):
        w=ready();self.rx(core.wire_frame(0,'TASK',w.token,w.raw))
        out=self.tick();seq,kind,args=self.request(out)
        self.assertEqual(kind,'TASK_ACK')
        packets,_=app.command(w,seq,kind,args,self.now);self.rx(b''.join(packets));self.tick()
        actions=[]
        for step in range(24):
            out=self.tick();seq,kind,args=self.request(out)
            self.assertEqual(kind,w.current()['mode'])
            packets,locate=app.command(w,seq,kind,args,self.now);self.assertTrue(locate)
            s=w.current();record={'id':s['color'] if kind=='COLOR' else s['slot'],'slot':s['slot'],
                'cx':320,'cy':240,'pixels':1000,'valid':True,'stable':True}
            core.PLANE_H=(1,0,0,0,1,0,0,0,1);core.PLANE_ROI=(0,0,640,480)
            self.rx(b''.join(core.result_frames(seq,kind,[record],None,None,0,self.now)))
            out=self.tick();actions.extend(s for s in out if s.startswith('ACTION'))
            out=self.tick();seq,kind,args=self.request(out);self.assertEqual(kind,'STEP')
            packets,_=app.command(w,seq,kind,args,self.now)
            if step==7:  # Actual action already completed; first STEP ACK is lost.
                seq,kind,args=self.request(self.tick(1600))
                self.assertEqual(kind,'STEP')
                packets,_=app.command(w,seq,kind,args,self.now)
            self.rx(b''.join(packets));self.tick()
        out=self.tick();seq,kind,args=self.request(out);self.assertEqual(kind,'HOME_DONE')
        packets,_=app.command(w,seq,kind,args,self.now);self.rx(b''.join(packets))
        out=self.tick();self.assertIn('STATE 7 24',out)
        self.assertEqual(len(actions),24);self.assertEqual(w.state,'COMPLETE')
        self.assertIn('ACTION 22 STACK2 1 1 1',actions)
        core.PLANE_H=core.PLANE_ROI=None
    def test_bad_task_crc_ignored(self):
        w=ready();bad=core.wire_frame(0,'TASK',w.token,w.raw).replace(b'156+',b'256+')
        self.rx(bad);self.assertFalse(any(s.startswith('TX') for s in self.tick()))
    def test_start_button_required_and_clears_prestart_task(self):
        self.exchange('I')
        w=ready();self.rx(core.wire_frame(0,'TASK',w.token,w.raw))
        out=self.tick();self.assertIn('STATE 10 0',out)
        self.assertFalse(any(s.startswith(('ACTION','TX','PREPARE')) for s in out))
        seq,kind,args=self.request(self.exchange('B 100'));self.assertEqual(kind,'RESET')
        self.rx(core.wire_frame(seq,'ACK','RESET')+core.wire_frame(seq,'DONE',0,100))
        self.tick();out=self.tick();self.assertIn('STATE 0 0',out)
    def test_ack_timeout_retries_then_stops(self):
        w=ready();self.rx(core.wire_frame(0,'TASK',w.token,w.raw));self.tick()
        out=[]
        for _ in range(4):out=self.tick(1600)
        self.assertIn('STOP',out);self.assertTrue(any('LINK_TIMEOUT' in s for s in out))
    def test_uncalibrated_coordinates_never_start_motion(self):
        w=ready();self.rx(core.wire_frame(0,'TASK',w.token,w.raw))
        seq,k,a=self.request(self.tick());self.rx(b''.join(app.command(w,seq,k,a,0)[0]));self.tick()
        seq,k,a=self.request(self.tick());core.PLANE_H=core.PLANE_ROI=None
        rec={'id':1,'cx':320,'cy':240,'pixels':1000,'valid':True,'stable':True}
        self.rx(b''.join(core.result_frames(seq,k,[rec],None,None,0,0)))
        self.assertFalse(any(s.startswith('ACTION') for s in self.tick()))

if __name__=='__main__':unittest.main()
