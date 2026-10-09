"""Desktop checks for filtering and labeling, not camera/firmware validation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "blocks", Path(__file__).resolve().parents[1] / "examples/k230_color_blocks.py")
blocks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blocks)


class Blob:
    def __init__(self, rect, code, pixels=600):
        self._rect, self._code, self._pixels = rect, code, pixels

    def rect(self): return self._rect
    def code(self): return self._code
    def pixels(self): return self._pixels
    def cx(self): return self._rect[0] + self._rect[2] // 2
    def cy(self): return self._rect[1] + self._rect[3] // 2


class Image:
    def __init__(self, blobs):
        self.blobs = blobs
        self.calls = 0

    def find_blobs(self, thresholds, **kwargs):
        self.calls += 1
        self.thresholds, self.kwargs = thresholds, kwargs
        return self.blobs


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.threshold = (20, 80, -30, 30, -30, 30)
        self.ids, self.values = blocks.enabled_colors(
            {1: None, 3: self.threshold, 6: self.threshold})

    def test_disabled_colors_do_not_shift_contest_ids(self):
        img = Image([Blob((80, 90, 30, 30), 1), Blob((250, 90, 30, 30), 2)])
        records = blocks.detect_blocks(img, self.ids, self.values)
        self.assertEqual([r["id"] for r in records], [3, 6])
        self.assertTrue(all(r["valid"] for r in records))
        self.assertEqual((records[0]["cx"], records[0]["cy"]), (95, 105))
        self.assertFalse(img.kwargs["merge"])
        self.assertEqual(img.thresholds, self.values)

    def test_overlap_rejects_both_labels_including_containment(self):
        img = Image([Blob((80, 90, 40, 40), 1), Blob((85, 95, 30, 30), 2)])
        self.assertEqual([r["valid"] for r in blocks.detect_blocks(img, self.ids, self.values)],
                         [False, False])

    def test_multibit_result_is_not_a_valid_single_color(self):
        records = blocks.detect_blocks(Image([Blob((80, 90, 30, 30), 3)]), self.ids, self.values)
        self.assertEqual(records[0]["id"], 0)
        self.assertFalse(records[0]["valid"])

    def test_noise_and_large_background_do_not_become_targets(self):
        img = Image([Blob((80, 90, 30, 30), 1, pixels=100),
                     Blob((80, 90, 5, 5), 1), Blob((20, 60, 600, 400), 1, pixels=200000)])
        self.assertEqual(blocks.detect_blocks(img, self.ids, self.values), [])

    def test_absence_does_not_reuse_previous_frame(self):
        img = Image([Blob((80, 90, 30, 30), 1)])
        self.assertEqual(len(blocks.detect_blocks(img, self.ids, self.values)), 1)
        img.blobs = []
        self.assertEqual(blocks.detect_blocks(img, self.ids, self.values), [])

    def test_no_config_never_calls_unrestricted_detector(self):
        img = Image([])
        self.assertEqual(blocks.detect_blocks(img, [], []), [])
        self.assertEqual(img.calls, 0)

    def test_invalid_thresholds_fail_explicitly(self):
        for value in ((80, 20, -30, 30, -30, 30), (0, 101, 0, 1, 0, 1),
                      (0, 100, -129, 1, 0, 1), (0, 100, 0, 1, 0),
                      (0, 100, 0.5, 1, 0, 1)):
            with self.assertRaises(ValueError):
                blocks.enabled_colors({1: value})

    def test_sampling_clamps_to_lab_limits(self):
        class Percentile:
            def __init__(self, values): self.values = values
            def l_value(self): return self.values[0]
            def a_value(self): return self.values[1]
            def b_value(self): return self.values[2]

        class Histogram:
            def get_percentile(self, percentile):
                return Percentile((2, -125, -126) if percentile < 0.5 else (99, 126, 125))

        self.assertEqual(blocks.sampled_threshold(Histogram()), (0, 100, -128, 127, -128, 127))


if __name__ == "__main__":
    unittest.main()
