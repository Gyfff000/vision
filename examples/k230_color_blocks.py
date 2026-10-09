# Run on the K230 with CanMV, not desktop Python.
# Onboard camera -> RGB565 -> LAB blobs -> LCD + terminal pixel coordinates.
import time
import os
import gc
import sys

# 1. Run SAMPLE with a known color filling the small center square.
# 2. Paste one printed THRESHOLDS[id] assignment below the dictionary.
# 3. Set MODE to DETECT and run again. Start with just one color.
MODE = "SAMPLE"                 # "SAMPLE" or "DETECT"
SAMPLE_COLOR_ID = 1              # 1 red, 2 yellow, 3 blue, 4 green, 5 black, 6 light blue
THRESHOLDS = {
    1: None, 2: None, 3: None, 4: None, 5: None, 6: None,
}
# Paste sampled assignments HERE, for example: THRESHOLDS[1] = (six numbers)
# None disables a color. No universal thresholds are assumed.

WIDTH = 640
HEIGHT = 480
SAMPLE_ROI = (300, 220, 40, 40)
DETECT_ROI = (20, 60, 600, 400)   # x, y, width, height in the original image
MIN_PIXELS = 150                # Initial tuning settings, not contest rules
MIN_AREA = 200
MAX_AREA_FRACTION = 0.50         # Reject very large background regions
OVERLAP_FRACTION = 0.40         # Shared bounding-box area / smaller box area
PRINT_INTERVAL_MS = 250
SAMPLE_INTERVAL_MS = 1000
LAB_PADDING = (5, 8, 8)
COLOR_NAMES = {1: "RED", 2: "YELLOW", 3: "BLUE", 4: "GREEN",
               5: "BLACK", 6: "LIGHT_BLUE"}
DRAW_COLORS = {1: (255, 40, 40), 2: (255, 255, 0), 3: (80, 100, 255),
               4: (0, 255, 0), 5: (255, 255, 255), 6: (0, 255, 255)}


def enabled_colors(thresholds):
    """Keep contest IDs independent of which colors have been sampled."""
    ids = []
    values = []
    for color_id in sorted(thresholds):
        if color_id not in COLOR_NAMES:
            raise ValueError("Color IDs must be 1..6")
        value = thresholds[color_id]
        if value is None:
            continue
        if len(value) != 6:
            raise ValueError("Each LAB threshold needs six integers")
        for offset, lower, upper in ((0, 0, 100), (2, -128, 127), (4, -128, 127)):
            lo, hi = value[offset], value[offset + 1]
            if not isinstance(lo, int) or not isinstance(hi, int) or not lower <= lo <= hi <= upper:
                raise ValueError("Invalid LAB threshold for color %d" % color_id)
        ids.append(color_id)
        values.append(tuple(value))
    return ids, values


def sampled_threshold(histogram):
    """Suggest a threshold from the central 80% of a known-color patch."""
    low = histogram.get_percentile(0.10)
    high = histogram.get_percentile(0.90)
    lows = (low.l_value(), low.a_value(), low.b_value())
    highs = (high.l_value(), high.a_value(), high.b_value())
    limits = ((0, 100), (-128, 127), (-128, 127))
    result = []
    for i in range(3):
        result.append(max(limits[i][0], lows[i] - LAB_PADDING[i]))
        result.append(min(limits[i][1], highs[i] + LAB_PADDING[i]))
    return tuple(result)


def box_overlap(first, second):
    x1, y1, w1, h1 = first
    x2, y2, w2, h2 = second
    shared_w = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
    shared_h = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
    return shared_w * shared_h / max(1, min(w1 * h1, w2 * h2))


def detect_blocks(img, ids, values):
    """Detect before drawing; overlapping different labels are ambiguous."""
    if not values:
        return []
    blobs = img.find_blobs(values, roi=DETECT_ROI, x_stride=2, y_stride=1,
                           pixels_threshold=MIN_PIXELS, area_threshold=MIN_AREA,
                           merge=False)
    records = []
    max_area = DETECT_ROI[2] * DETECT_ROI[3] * MAX_AREA_FRACTION
    for blob in blobs:
        rect = blob.rect()
        area = rect[2] * rect[3]
        if blob.pixels() < MIN_PIXELS or area < MIN_AREA or area > max_area:
            continue
        matches = [ids[i] for i in range(len(ids)) if blob.code() & (1 << i)]
        if not matches:
            continue
        color_id = matches[0] if len(matches) == 1 else 0
        records.append({"id": color_id, "rect": rect, "cx": blob.cx(),
                        "cy": blob.cy(), "pixels": blob.pixels(),
                        "valid": color_id != 0})
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            first, second = records[i], records[j]
            if first["id"] != second["id"] and box_overlap(first["rect"], second["rect"]) >= OVERLAP_FRACTION:
                first["valid"] = False
                second["valid"] = False
    return records


def main():
    from media.sensor import Sensor
    from media.display import Display
    from media.media import MediaManager

    sensor = None
    display_ready = False
    media_ready = False
    try:
        if MODE not in ("SAMPLE", "DETECT"):
            raise ValueError("MODE must be SAMPLE or DETECT")
        if SAMPLE_COLOR_ID not in COLOR_NAMES:
            raise ValueError("SAMPLE_COLOR_ID must be 1..6")
        ids, values = enabled_colors(THRESHOLDS)
        if MODE == "DETECT" and not values:
            raise ValueError("Sample one color first; paste THRESHOLDS[id] below the dictionary")
        print("[START] color blocks; mode=", MODE, "enabled_ids=", ids)
        print("[BOARD]", os.uname())
        print("[COORDS] pixels: origin top-left, x right, y down; not robot coordinates")
        sensor = Sensor()
        sensor.reset()
        sensor.set_framesize(width=WIDTH, height=HEIGHT)
        sensor.set_pixformat(Sensor.RGB565)
        sensor.set_hmirror(False)
        sensor.set_vflip(False)
        Display.init(Display.ST7701, width=WIDTH, height=HEIGHT, to_ide=True)
        display_ready = True
        MediaManager.init()
        media_ready = True
        sensor.run()
        time.sleep_ms(1500)
        last_print = time.ticks_ms()
        sample = None
        while True:
            os.exitpoint()
            img = sensor.snapshot()
            now = time.ticks_ms()
            # Finish all measurements before drawing overlays into this image.
            if MODE == "SAMPLE":
                if sample is None or time.ticks_diff(now, last_print) >= SAMPLE_INTERVAL_MS:
                    sample = sampled_threshold(img.get_histogram(roi=SAMPLE_ROI))
                    print("[SAMPLE] known_color=%d name=%s" %
                          (SAMPLE_COLOR_ID, COLOR_NAMES[SAMPLE_COLOR_ID]))
                    print("THRESHOLDS[%d] = %s" % (SAMPLE_COLOR_ID, sample))
                    last_print = now
                img.draw_rectangle(SAMPLE_ROI, color=(255, 255, 255), thickness=2)
                img.draw_string_advanced(0, 0, 24, "SAMPLE %d %s" %
                                         (SAMPLE_COLOR_ID, COLOR_NAMES[SAMPLE_COLOR_ID]),
                                         color=(255, 255, 255))
                img.draw_string_advanced(0, 30, 20, "Fill center square with known color",
                                         color=(255, 255, 255))
            else:
                records = detect_blocks(img, ids, values)
                if time.ticks_diff(now, last_print) >= PRINT_INTERVAL_MS:
                    if not records:
                        print("[NO_TARGET] count=0")
                    for record in records:
                        label = "BLOCK" if record["valid"] else "AMBIGUOUS"
                        print("[%s] id=%d name=%s cx=%d cy=%d pixels=%d valid=%d" %
                              (label, record["id"], COLOR_NAMES.get(record["id"], "UNKNOWN"),
                               record["cx"], record["cy"], record["pixels"], record["valid"]))
                    last_print = now
                img.draw_rectangle(DETECT_ROI, color=(180, 180, 180), thickness=1)
                for record in records:
                    color = DRAW_COLORS.get(record["id"], (255, 128, 0))
                    label = COLOR_NAMES[record["id"]] if record["valid"] else "AMBIGUOUS"
                    img.draw_rectangle(record["rect"], color=color, thickness=2)
                    img.draw_cross(record["cx"], record["cy"], color=color, thickness=2)
                    img.draw_string_advanced(record["rect"][0], max(60, record["rect"][1] - 22),
                                             20, label, color=color)
                img.draw_string_advanced(0, 0, 24, "DETECT count=%d" % len(records),
                                         color=(255, 255, 255))
            Display.show_image(img)
            gc.collect()
    except KeyboardInterrupt:
        print("[STOP] user stopped")
    except Exception as exc:
        sys.print_exception(exc)
    finally:
        if sensor is not None:
            try:
                sensor.stop()
            except Exception as exc:
                print("[CLEANUP] sensor:", exc)
        if display_ready:
            try:
                Display.deinit()
            except Exception as exc:
                print("[CLEANUP] display:", exc)
        time.sleep_ms(100)
        if media_ready:
            try:
                MediaManager.deinit()
            except Exception as exc:
                print("[CLEANUP] media:", exc)


if __name__ == "__main__":
    main()
