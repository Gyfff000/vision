"""Exercise preview switching without requiring camera hardware or GUI focus."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("pc_preview", Path(__file__).resolve().parents[1]/"tools/usb_camera_preview_pc.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class PreviewTests(unittest.TestCase):
    def fake_cv(self, actions, fail=None):
        events = []
        class Capture:
            def __init__(self, index): self.index=index; events.append(("open",index))
            def isOpened(self): return self.index != fail
            def set(self,*a): return True
            def read(self): return True,np.zeros((480,640,3),np.uint8)
            def release(self): events.append(("release",self.index))
        class CV:
            def __init__(self): self.actions=list(actions); self.callback=None
            def __getattr__(self,name): return getattr(cv2,name)
            def VideoCapture(self,index,backend): return Capture(index)
            def namedWindow(self,*a): pass
            def setMouseCallback(self,window,callback): self.callback=callback
            def imshow(self,window,frame): events.append(("display",frame.shape))
            def waitKey(self,*a):
                action=self.actions.pop(0) if self.actions else ord("q")
                if action == "click_builtin": self.callback(1,500,20,0,None);return -1
                return action
            def getWindowProperty(self,*a): return 1
            def destroyAllWindows(self): events.append(("closed",))
        return CV(),events

    def test_default_selection_follows_name_when_indices_change(self):
        self.assertEqual(app.select_camera(["FHD Camera","Integrated Webcam"],"FHD Camera"),0)
        self.assertEqual(app.select_camera(["Integrated Webcam","FHD Camera"],"FHD Camera"),1)
        with self.assertRaises(RuntimeError): app.select_camera(["Integrated Webcam"],"FHD Camera")

    def test_c_key_switch_releases_previous_capture_before_opening_next(self):
        fake,events=self.fake_cv([ord("c"),ord("q")])
        with contextlib.redirect_stdout(io.StringIO()): app.run_preview(fake,["FHD Camera","Integrated Webcam"],0)
        life=[event for event in events if event[0] in ("open","release")]
        self.assertEqual(life,[("open",0),("release",0),("open",1),("release",1)])
        self.assertEqual(events[-1],("closed",))

    def test_clicking_device_button_switches_without_keyboard_input(self):
        fake,events=self.fake_cv(["click_builtin",ord("q")])
        with contextlib.redirect_stdout(io.StringIO()): app.run_preview(fake,["FHD Camera","Integrated Webcam"],0)
        self.assertIn(("open",1),events)

    def test_failed_camera_keeps_controls_and_allows_switch_back(self):
        fake,events=self.fake_cv([ord("c"),ord("c"),ord("q")],fail=1)
        with contextlib.redirect_stdout(io.StringIO()): app.run_preview(fake,["FHD Camera","Integrated Webcam"],0)
        self.assertEqual([event for event in events if event[0]=="open"],[("open",0),("open",1),("open",0)])
        self.assertEqual(sum(event[0]=="display" for event in events),3)

    def test_mjpeg_survives_driver_format_reset_during_resolution_fps_settings(self):
        # Model the measured DirectShow behavior: changing FPS resets format to YUY2.
        class Capture:
            codec = None
            def isOpened(self): return True
            def set(self, prop, value):
                self.codec = value if prop == cv2.CAP_PROP_FOURCC else cv2.VideoWriter_fourcc(*"YUY2")
                return True
            def release(self): pass
        class CV:
            def __getattr__(self,name): return getattr(cv2,name)
            def VideoCapture(self,*args): return Capture()
        capture = app.open_camera(CV(), 0)
        self.assertEqual(capture.codec, cv2.VideoWriter_fourcc(*"MJPG"))


if __name__=="__main__": unittest.main()
