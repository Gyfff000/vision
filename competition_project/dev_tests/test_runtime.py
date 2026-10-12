import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'K230_competition'))
import vision_app as app
import vision_core as core

class RuntimeTests(unittest.TestCase):
    def test_board_loop_scan_ack_then_fresh_color_with_display_enabled(self):
        self.run_board_loop(ack_after=1300)

    def test_board_loop_color_preview_and_task_retries_without_stm32(self):
        self.run_board_loop(ack_after=None)

    def run_board_loop(self,ack_after):
        task='156+123+516+231'
        class Clock:
            now=0
            @classmethod
            def ticks_ms(cls):return cls.now
            @staticmethod
            def ticks_diff(a,b):return a-b
            @staticmethod
            def ticks_add(a,b):return a+b
            @classmethod
            def sleep_ms(cls,n):cls.now+=n
        class Frame:
            def find_qrcodes(self):return [Code()]
            def draw_string_advanced(self,*a,**k):pass
            def draw_rectangle(self,*a,**k):pass
            def draw_cross(self,*a,**k):pass
        class Code:
            def payload(self):return task
            def rect(self):return (100,100,100,100)
        class Camera:
            modes=[]
            def __init__(self,*a):pass
            def snapshot(self,mode):self.modes.append(mode);return Frame()
            def stop(self):pass
        class Link:
            uart=None
            token=None
            acked=False
            located=False
            rejected=False
            events=[]
            def poll(self):
                if self.token is not None and not self.rejected:
                    self.rejected=True;return [(10,'LOCATE',[])]
                if self.token is not None and not self.acked and ack_after is not None and Clock.now>=ack_after:
                    self.acked=True;return [(11,'TASK_ACK',[str(self.token)])]
                if self.acked and not self.located:
                    self.located=True;return [(12,'LOCATE',[])]
                return []
            def send(self,seq,kind,*args):
                self.events.append((Clock.now,kind))
                if kind=='TASK':self.token=args[0]
            def close(self):pass
        class Display:
            ST7701=1
            options={}
            frames=0
            @classmethod
            def init(cls,*a,**k):cls.options=k
            @classmethod
            def show_image(cls,frame):cls.frames+=1
            @staticmethod
            def deinit():pass
        media=types.ModuleType('media');media.__path__=[]
        sensor=types.ModuleType('media.sensor');sensor.Sensor=object
        display=types.ModuleType('media.display');display.Display=Display
        manager=types.ModuleType('media.media');manager.MediaManager=type('M',(),{'init':staticmethod(lambda:None),'deinit':staticmethod(lambda:None)})
        image=types.ModuleType('image');image.RGB565=1;image.Image=lambda *a,**k:Frame()
        ulab=types.ModuleType('ulab');ulab.numpy=object()
        modules={'media':media,'media.sensor':sensor,'media.display':display,'media.media':manager,'image':image,'ulab':ulab}
        calls=[];packets=[]
        def exitpoint():
            Clock.now+=40
            if Clock.now>2400:raise KeyboardInterrupt()
        def locate(frame,work,*unused):
            calls.append((work.state,work.step))
            return [{'id':1,'cx':320,'cy':240,'rect':(300,220,40,40),'pixels':500,'valid':True,'stable':False}]
        with patch.dict(sys.modules,modules),patch.object(app,'time',Clock),patch.object(app.os,'exitpoint',exitpoint,create=True),\
             patch.object(core,'VisionLink',Link),patch.object(core,'CameraMux',Camera),\
             patch.object(app,'fresh_records',locate),patch.object(app,'write_packet',lambda link,p:packets.append(p)):
            app.main()
        self.assertIn('QR',Camera.modes);self.assertIn('COLOR',Camera.modes)
        self.assertEqual(Camera.modes[-1],'COLOR')
        self.assertGreater(Display.frames,len(calls))
        self.assertEqual(Display.options['to_ide'],False)
        self.assertTrue(any(state=='WAIT_ACK' for state,step in calls))
        frames=core.FrameParser().feed(b''.join(packets))
        self.assertTrue(any(s==10 and k=='ERROR' and f==['NOT_RUNNING'] for s,k,f in frames))
        if ack_after is not None:
            self.assertTrue(any(s==11 and k=='ACK' for s,k,f in frames))
            self.assertEqual(sum(s==12 and k=='BLOCK' for s,k,f in frames),1)
            self.assertTrue(any(state=='RUN' for state,step in calls))
        else:
            self.assertTrue(all(state=='WAIT_ACK' and step==0 for state,step in calls))
            self.assertGreaterEqual(sum(kind=='TASK' for now,kind in Link.events),2)
            self.assertFalse(any(k=='BLOCK' for s,k,f in frames))

if __name__=='__main__':unittest.main()
