import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


app = module("examples/k230_usb_camera_test.py", "usb_test")
installer = module("examples/k230_usb_camera_install.py", "usb_install")


class PreviewTests(unittest.TestCase):
    def run_board(self, case, modern=False):
        events = []
        class Clock:
            now = 0
            @classmethod
            def ticks_ms(cls): return cls.now
            @staticmethod
            def ticks_diff(a,b): return a-b
            @classmethod
            def sleep_ms(cls,n): cls.now += n
        class Frame:
            def width(self): return 640
            def height(self): return 480
            def to_rgb565(self): return self
            def draw_string_advanced(self,*a,**kw): events.append(("text",a[3]))
        class UVC:
            @staticmethod
            def probe(): return case != "absent", "USB Camera"
            @staticmethod
            def video_mode(*a): return a
            @staticmethod
            def select_video_mode(mode): events.append(("mode",mode));return case != "mode_failed",mode
            @staticmethod
            def start(**kw): events.append(("start",kw));return case != "start_failed"
            @staticmethod
            def snapshot(**kw): return None if case == "no_frames" else Frame()
            @staticmethod
            def stop(): events.append(("stop",))
        setattr(UVC, "FOURCC_MJPEG" if modern else "FORMAT_MJPEG", 1)
        class Display:
            ST7701 = 1
            @staticmethod
            def init(*a,**kw): events.append(("display_init",kw))
            @staticmethod
            def show_image(frame): events.append(("show",))
            @staticmethod
            def deinit(): events.append(("display_deinit",))
        modules = {}
        for name, attr, value in (("media.display","Display",Display),
                                  ("media.media","MediaManager",types.SimpleNamespace(init=lambda:None,deinit=lambda:events.append(("media_deinit",)))),
                                  ("media.uvc","UVC",UVC)):
            entry = types.ModuleType(name);setattr(entry,attr,value);modules[name]=entry
        parent = types.ModuleType("media");parent.__path__=[];modules["media"]=parent
        if case == "unsupported": modules["media.uvc"] = None
        image = types.ModuleType("image");image.RGB565=1;image.Image=lambda *a,**kw:Frame();modules["image"]=image
        def exitpoint():
            Clock.now += 100
            if (case == "success" and Clock.now > 1500) or Clock.now > 12000:
                raise KeyboardInterrupt()
        output = io.StringIO()
        with patch.dict(sys.modules,modules),patch.object(app,"time",Clock), \
             patch.object(app.os,"uname",lambda:"k230",create=True), \
             patch.object(app.os,"exitpoint",exitpoint,create=True), \
             patch.object(app.sys,"print_exception",lambda exc:None,create=True), \
             contextlib.redirect_stdout(output):
            app.main()
        self.assertIn(("display_deinit",),events)
        self.assertIn(("media_deinit",),events)
        return output.getvalue(),events

    def test_old_and_new_uvc_api_show_frames_and_release_stream(self):
        for modern in (False,True):
            with self.subTest(modern=modern):
                output,events=self.run_board("success",modern)
                self.assertIn("[USB_FRAME_OK]",output)
                self.assertIn("[USB_FPS]",output)
                self.assertIn(("start",{"cvt":False}),events)
                self.assertIn(("stop",),events)

    def test_no_host_or_camera_retains_error_on_lcd(self):
        output,events=self.run_board("absent")
        self.assertIn("USB_NOT_FOUND",output)
        self.assertIn(("text","USB CAMERA ERROR"),events)
        self.assertNotIn(("stop",),events)

    def test_missing_firmware_module_is_visible_on_lcd(self):
        output,events=self.run_board("unsupported")
        self.assertIn("USB_UNSUPPORTED",output)
        self.assertIn(("text","USB CAMERA ERROR"),events)

    def test_stream_failures_clean_up_and_do_not_report_frames(self):
        for case,reason in (("mode_failed","USB_MODE_FAILED"),("start_failed","USB_START_FAILED"),("no_frames","USB_FRAME_TIMEOUT")):
            with self.subTest(case=case):
                output,events=self.run_board(case)
                self.assertIn(reason,output)
                self.assertNotIn("[USB_FRAME_OK]",output)
                self.assertIn(("stop",),events)

    def test_installer_matches_payload_and_preserves_competition_startup(self):
        source=(ROOT/"examples/k230_usb_camera_test.py").read_text(encoding="utf-8")
        self.assertEqual(installer.PAYLOAD,source)
        compile(installer.PAYLOAD,"preview_payload","exec")
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as name:
            root=Path(name)
            (root/"main.py").write_text("# existing competition startup",encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(root.as_posix());installer.install(root.as_posix())
            self.assertEqual((root/"vision_backup/main.py.001.bak").read_text(),"# existing competition startup")
            self.assertEqual((root/"usb_camera_preview.py").read_text(encoding="utf-8"),source)
            self.assertEqual((root/"main.py").read_text(encoding="utf-8"),installer.LAUNCHER)
            self.assertIn("import usb_camera_preview",installer.LAUNCHER)


if __name__ == "__main__": unittest.main()
