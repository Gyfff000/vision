"""Fast six-color deployment: algorithm regression and board-loop scheduling."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_gx_vision as existing

spec = importlib.util.spec_from_file_location("six_color_fast", ROOT / "deploy/yahboom_six_color/k230_silver_rgb.py")
fast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fast)


class AlgorithmTests(existing.AlgorithmTests):
    def setUp(self):
        self.module_patch = patch.object(existing, "gx", fast)
        self.module_patch.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.module_patch.stop()


class RuntimeTests(unittest.TestCase):
    def run_loop(self, mode="COLOR", requests=False, max_age=600):
        class Clock:
            now = 0
            @classmethod
            def ticks_ms(cls): return cls.now
            @staticmethod
            def ticks_diff(a, b): return a-b
            @classmethod
            def sleep_ms(cls, n): cls.now += n

        calls, gc_calls, drawn, shown, packets, qr_calls = [], [], [], [], [], []
        class Code:
            def payload(self): return "Good"
            def rect(self): return (0, 0, 100, 100)

        class Frame:
            def __init__(self, number): self.number, self.painted = number, False
            def draw_string_advanced(self, *a, **k): self.painted = True
            def draw_rectangle(self, *a, **k): drawn.append((self.number, Clock.now)); self.painted = True
            def draw_cross(self, *a, **k): self.painted = True
            def find_qrcodes(self):
                assert not self.painted
                qr_calls.append(Clock.now)
                return [Code()]

        class Camera:
            count = 0
            def __init__(self, *a): pass
            def snapshot(self, mode): self.count += 1; return Frame(self.count)
            def stop(self): pass

        class UART:
            def write(self, data): packets.append(data); return len(data)
        class Link:
            uart = UART()
            sent = False
            def poll(self):
                # Second frame is still within DETECT_PERIOD_MS of the first.
                if requests and not self.sent and Clock.now >= 40:
                    self.sent = True
                    return [(7, "COLOR", [])]
                return []
            def send(self, seq, kind, *args): packets.append(fast.wire_frame(seq, kind, *args))
            def close(self): pass

        class Display:
            ST7701 = 1
            options = {}
            @classmethod
            def init(cls, *a, **k): cls.options = k
            @staticmethod
            def show_image(frame): shown.append(frame.number)
            @staticmethod
            def deinit(): pass

        sensor = types.ModuleType("media.sensor"); sensor.Sensor = object
        display = types.ModuleType("media.display"); display.Display = Display
        manager = types.ModuleType("media.media")
        manager.MediaManager = types.SimpleNamespace(init=lambda: None, deinit=lambda: None)
        image = types.ModuleType("image"); image.RGB565 = 1
        image.Image = lambda *a, **k: Frame(-1)
        ulab = types.ModuleType("ulab"); ulab.numpy = object()
        modules = {"media.sensor": sensor, "media.display": display, "media.media": manager,
                   "image": image, "ulab": ulab}
        def detect(frame, *unused):
            assert not frame.painted
            calls.append((frame.number, Clock.now))
            Clock.now += 20
            if requests and len(calls) > 1: return []
            return [dict(id=1, cx=320, cy=240, rect=(300,220,40,40), pixels=1600,
                         pos=-1, valid=True, stable=False)]
        def exitpoint():
            Clock.now += 10
            if Clock.now > 1250: raise KeyboardInterrupt()

        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.object(fast, "time", Clock), \
             patch.object(fast.os, "exitpoint", exitpoint, create=True), \
             patch.object(fast.os, "uname", lambda: "k230", create=True), \
             patch.object(fast, "CameraMux", Camera), patch.object(fast, "VisionLink", Link), \
             patch.object(fast, "MODE", mode), patch.object(fast, "MAX_RESULT_AGE_MS", max_age), \
             patch.object(fast, "detect_colors", detect), \
             patch.object(fast.gc, "collect", lambda: gc_calls.append(Clock.now)), \
             contextlib.redirect_stdout(output):
            fast.main()
        self.assertNotIn("FRAME_ERROR", output.getvalue())
        return calls, shown, Display.options, gc_calls, drawn, packets, qr_calls, output.getvalue()

    def test_display_and_gc_are_independent_of_detection(self):
        calls, shown, options, gc_calls, *_ = self.run_loop()
        self.assertGreater(len(shown), 5 * len(calls))
        self.assertFalse(options["to_ide"])
        self.assertEqual(len(gc_calls), 1)

    def test_uart_forces_new_detection_and_does_not_return_cached_target(self):
        calls, shown, options, gc_calls, drawn, packets, *_ = self.run_loop(requests=True)
        self.assertEqual([number for number, stamp in calls[:2]], [1, 2])
        self.assertLess(calls[1][1] - calls[0][1], fast.DETECT_PERIOD_MS)
        decoded = fast.FrameParser().feed(b"".join(packets))
        self.assertEqual([(s,k) for s,k,f in decoded], [(7,"NO_TARGET"),(7,"DONE")])
        self.assertTrue(all(number == 1 for number, stamp in drawn))

    def test_cached_boxes_expire_between_detections(self):
        calls, shown, options, gc_calls, drawn, *_ = self.run_loop(max_age=15)
        self.assertLess(len(drawn), len(shown))
        for number, stamp in drawn:
            measurement = max(start + 20 for frame_id, start in calls if frame_id <= number)
            self.assertLessEqual(stamp - measurement, 15)

    def test_qr_confirmation_counts_real_decodes_only(self):
        calls, shown, options, gc_calls, drawn, packets, qr_calls, output = self.run_loop(mode="QR")
        self.assertLess(len(qr_calls), len(shown))
        self.assertGreaterEqual(len(qr_calls), 3)
        self.assertTrue(all(b-a >= fast.QR_SCAN_PERIOD_MS for a,b in zip(qr_calls,qr_calls[1:])))
        self.assertEqual(output.splitlines().count("Good"), 1)


if __name__ == "__main__":
    unittest.main()
