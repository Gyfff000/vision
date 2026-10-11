# K230 adaptation of the vision pipeline described and implemented in:
# https://github.com/liaojingwu20041031/GX-Intelligent-Logistics-Silver
# Source revision and adaptation differences are recorded in docs/gx-k230-port.md.
# Fresh MicroPython implementation: no desktop cv2, no motion commands.
import os
import sys
import time
import gc

MODE = "COLOR"                 # COLOR, RING, ARUCO, QR, HSV_SAMPLE, SELF_TEST
QR_CAMERA = "ONBOARD"          # ONBOARD now; USB after UVC hardware validation
UART_ENABLE = True
UART_ID = 3                    # Yahboom 12-pin header: UART3
UART_TX_PIN = 32                # GPIO32: physical header position 5 (TX)
UART_RX_PIN = 33                # GPIO33: physical header position 3 (RX)
UART_BAUD = 115200              # 8 data bits, no parity, 1 stop bit
WIDTH, HEIGHT = 640, 480
PROCESS_SCALE = 0.5             # 320x240 processing; output coordinates stay 640x480
DETECT_ROI = None # Search inside work area, in full 640x480 coordinates
EDGE_MARGIN = 3                # Reject blobs clipped at processing ROI boundary
ACTIVE_COLOR_IDS = (1, 2, 3, 4, 5, 6)
SAMPLE_COLOR_ID = 1
PRINT_INTERVAL_MS = 500
MIN_PIXELS = 125                # At processing resolution, not full resolution
MAX_AREA_FRACTION = 0.45
MIN_DENSITY = 0.25
MIN_ASPECT, MAX_ASPECT = 0.25, 4.0
MORPH_RADIUS = 1                # 3x3 square open then close; original used 5x5 ellipse
STABLE_FRAMES = 4
STABLE_DISTANCE_PX = 12
MARKER_ID = 0
MARKER_MIN_AREA = 300
PLANE_H = None                 # Optional 9-value image->plane homography, mm
PLANE_ROI = None               # Required calibrated domain: (x, y, width, height)
CALIBRATIONS = {"GRASP": (None, None), "PLACE": (None, None), "STACK": (None, None)}
REFERENCE_PIXEL = (320, 240)    # Pixel offset reference; set to actual gripper axis
RING_SLOT_ROIS = {}            # e.g. {1: (x,y,w,h), 2: (...), 3: (...)} AFTER mapping
RING_THRESHOLD = 3500
RING_MIN_RADIUS, RING_MAX_RADIUS = 8, 90  # At 320x240 processing resolution

COLOR_NAMES = {1: "RED", 2: "YELLOW", 3: "BLUE", 4: "GREEN",
               5: "BLACK", 6: "LIGHT_BLUE"}
DRAW_COLORS = {1: (255, 40, 40), 2: (255, 255, 0), 3: (80, 100, 255),
               4: (0, 255, 0), 5: (255, 255, 255), 6: (0, 255, 255)}
# HSV uses OpenCV units: H 0..179, S/V 0..255. Each tuple contains paired limits.
# Starting values only. These are NOT conversions of the old LAB thresholds.
# Red wraparound and broad RGB hue segmentation follow the reference pipeline.
# Yellow/black/light-blue and the S split between blue/light-blue are extensions.
HSV_RANGES = {
    1: ((0, 10, 100, 255, 100, 255), (170, 179, 100, 255, 100, 255)),
    2: ((15, 34, 100, 255, 80, 255),),
    3: ((100, 130, 100, 255, 100, 255),),
    4: ((35, 85, 100, 255, 100, 255),),
    5: ((0, 179, 0, 255, 0, 65),),
    6: ((80, 135, 50, 149, 100, 255),),
}

# Generated from OpenCV DICT_4X4_50; filled by the build step below.
ARUCO_4X4_50 = (46386, 3994, 13101, 39238, 21662, 31181, 40494, 50418, 65242,
                53078, 63889, 4519, 3767, 10767, 9393, 9790, 18021, 26112, 27742,
                30383, 34443, 45099, 52437, 56706, 65095, 38001, 44260, 42324,
                8483, 13423, 17429, 22450, 40655, 61643, 2222, 2345, 6261, 1279,
                3574, 7258, 5912, 10792, 12940, 14514, 9448, 12011, 11583, 19300,
                20526, 20499)


def rgb_to_hsv(rgb, np):
    """Vectorized RGB -> OpenCV-style HSV; works with ulab and desktop NumPy."""
    dtype = getattr(np, "float", float)
    r = np.array(rgb[:, :, 0], dtype=dtype)
    g = np.array(rgb[:, :, 1], dtype=dtype)
    b = np.array(rgb[:, :, 2], dtype=dtype)
    v = np.maximum(np.maximum(r, g), b)
    low = np.minimum(np.minimum(r, g), b)
    delta = v - low
    denominator = np.maximum(delta, 1)
    h = np.where(v == r, (g - b) * 30 / denominator,
                 np.where(v == g, (b - r) * 30 / denominator + 60,
                          (r - g) * 30 / denominator + 120))
    h = np.where(h < 0, h + 180, h)
    h = np.where(delta == 0, 0, h)
    s = delta * 255 / np.maximum(v, 1)
    return h, s, v


def color_mask(h, s, v, ranges, np):
    mask = np.zeros(h.shape, dtype=np.uint8)
    for lo_h, hi_h, lo_s, hi_s, lo_v, hi_v in ranges:
        part = (h >= lo_h) * (h <= hi_h) * (s >= lo_s) * (s <= hi_s) * (v >= lo_v) * (v <= hi_v)
        mask = np.array(np.where(part, 255, mask), dtype=np.uint8)
    return mask


def classify_position(cx, cy):
    """Reference's left-up/right-up/down zones, scaled to the output image."""
    x, y = cx - WIDTH / 2, cy - HEIGHT / 2
    if -320 <= x <= -50 and -240 <= y <= 50:
        return 0
    if 50 <= x <= 320 and -240 <= y <= 50:
        return 1
    if -150 <= x <= 150 and 50 <= y <= 240:
        return 2
    # Outside configured zones stays unknown; do not invent a position.
    return -1


def overlap_ratio(a, b):
    x1, y1, w1, h1 = a
    x2, y2, w2, h2 = b
    shared = max(0, min(x1 + w1, x2 + w2) - max(x1, x2)) * max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
    return shared / max(1, min(w1 * h1, w2 * h2))


class StableTracker:
    """Bound displacement over a whole confirmation window, not adjacent frames."""
    def __init__(self):
        self.history = {}

    def update(self, records):
        current = {}
        for record in records:
            key = record["id"]
            if not record["valid"]:
                record["stable"] = False
                continue
            old = self.history.get(key, [])
            points = (old + [(record["cx"], record["cy"])])[-STABLE_FRAMES:]
            if any(abs(x - record["cx"]) > STABLE_DISTANCE_PX or
                   abs(y - record["cy"]) > STABLE_DISTANCE_PX for x, y in points):
                points = [(record["cx"], record["cy"])]
            current[key] = points
            record["stable"] = len(points) >= STABLE_FRAMES
        self.history = current


def detect_colors(frame, np, image):
    roi = DETECT_ROI or (0, 0, frame.width(), frame.height())
    small = frame.copy(roi=roi, x_scale=PROCESS_SCALE, y_scale=PROCESS_SCALE)
    rgb = small.to_rgb888()
    h, s, v = rgb_to_hsv(rgb.to_numpy_ref(), np)
    records = []
    pw, ph = small.width(), small.height()
    sx, sy = roi[2] / pw, roi[3] / ph
    for color_id in ACTIVE_COLOR_IDS:
        data = color_mask(h, s, v, HSV_RANGES[color_id], np)
        mask = image.Image(pw, ph, image.GRAYSCALE, alloc=image.ALLOC_REF, data=data)
        mask.open(MORPH_RADIUS)
        mask.close(MORPH_RADIUS)
        blobs = mask.find_blobs([(128, 255)], x_stride=1, y_stride=1,
                                pixels_threshold=MIN_PIXELS, area_threshold=MIN_PIXELS,
                                merge=False)
        candidates = []
        for blob in blobs:
            x, y, w, height = blob.rect()
            area = w * height
            if x < EDGE_MARGIN or y < EDGE_MARGIN or x+w > pw-EDGE_MARGIN or y+height > ph-EDGE_MARGIN:
                continue
            aspect = w / max(1, height)
            if area > pw * ph * MAX_AREA_FRACTION or blob.pixels() / max(1, area) < MIN_DENSITY:
                continue
            if not MIN_ASPECT <= aspect <= MAX_ASPECT:
                continue
            candidates.append(blob)
        if not candidates:
            continue
        # Largest connected region per color (reference: largest external contour).
        blob = max(candidates, key=lambda item: item.pixels())
        x, y, w, height = blob.rect()
        cx, cy = int(round(blob.cx() * sx))+roi[0], int(round(blob.cy() * sy))+roi[1]
        records.append({"id": color_id, "cx": cx, "cy": cy,
                        "rect": (int(x * sx)+roi[0], int(y * sy)+roi[1], int(w * sx), int(height * sy)),
                        "pixels": int(blob.pixels() * sx * sy), "pos": classify_position(cx, cy),
                        "valid": True, "stable": False})
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if overlap_ratio(records[i]["rect"], records[j]["rect"]) >= 0.5:
                records[i]["valid"] = False
                records[j]["valid"] = False
    return records


def rotate_bits(bits):
    return [bits[(3 - x) * 4 + y] for y in range(4) for x in range(4)]


def decode_aruco_cells(cells):
    """Decode a perspective-sampled 6x6 grid with a black one-cell border."""
    if len(cells) != 36:
        return None
    border = [cells[y * 6 + x] for y in range(6) for x in range(6)
              if y in (0, 5) or x in (0, 5)]
    if sum(border) != 0:
        return None
    bits = [cells[(y + 1) * 6 + x + 1] for y in range(4) for x in range(4)]
    matches = []
    for rotation in range(4):
        code = 0
        for bit in bits:
            code = (code << 1) | bit
        for marker_id, expected in enumerate(ARUCO_4X4_50):
            distance = bin(code ^ expected).count("1")
            if distance <= 1:
                matches.append((distance, marker_id, rotation))
        bits = rotate_bits(bits)
    matches.sort()
    if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0]):
        return None
    return matches[0][1], matches[0][2], matches[0][0]


def quad_point(corners, u, v):
    """Project a unit-square point into a general convex quadrilateral."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = corners
    dx1, dx2, dx3 = x1 - x2, x3 - x2, x0 - x1 + x2 - x3
    dy1, dy2, dy3 = y1 - y2, y3 - y2, y0 - y1 + y2 - y3
    determinant = dx1 * dy2 - dx2 * dy1
    if abs(determinant) < 1e-8:
        return None
    g = (dx3 * dy2 - dx2 * dy3) / determinant
    h = (dx1 * dy3 - dx3 * dy1) / determinant
    denominator = g * u + h * v + 1
    if abs(denominator) < 1e-8:
        return None
    return ((x0 + (x1 - x0 + g * x1) * u + (x3 - x0 + h * x3) * v) / denominator,
            (y0 + (y1 - y0 + g * y1) * u + (y3 - y0 + h * y3) * v) / denominator)


def detect_marker(frame):
    # No AprilTag substitution: this matcher uses the actual ArUco 4x4_50 dictionary.
    gray = frame.copy(x_scale=PROCESS_SCALE, y_scale=PROCESS_SCALE).to_grayscale()
    rects = sorted(gray.find_rects(threshold=10000), key=lambda r: r.w() * r.h(), reverse=True)
    for rectangle in rects[:12]:
        if rectangle.w() * rectangle.h() < MARKER_MIN_AREA:
            continue
        corners = rectangle.corners()
        values = []
        for y in range(6):
            for x in range(6):
                samples = []
                for du, dv in ((0, 0), (-0.15, 0), (0.15, 0), (0, -0.15), (0, 0.15)):
                    point = quad_point(corners, (x + 0.5 + du) / 6, (y + 0.5 + dv) / 6)
                    if point is None:
                        samples = []
                        break
                    px, py = int(round(point[0])), int(round(point[1]))
                    if not 0 <= px < gray.width() or not 0 <= py < gray.height():
                        samples = []
                        break
                    samples.append(gray.get_pixel(px, py))
                if len(samples) == 5:
                    samples.sort()
                    values.append(samples[2])
        if len(values) != 36:
            continue
        low, high = min(values), max(values)
        if high - low < 45:
            continue
        decoded = decode_aruco_cells([int(value > (low + high) / 2) for value in values])
        if decoded is None or decoded[0] != MARKER_ID:
            continue
        center = quad_point(corners, 0.5, 0.5)
        sx, sy = frame.width() / gray.width(), frame.height() / gray.height()
        cx, cy = center[0] * sx, center[1] * sy
        dx, dy = cx - WIDTH / 2, cy - HEIGHT / 2
        calibrated_xy = plane_point(cx, cy)
        return {"id": decoded[0], "cx": cx, "cy": cy, "dx_px": dx, "dy_px": dy,
                "x_mm": calibrated_xy[0] if calibrated_xy else None,
                "y_mm": calibrated_xy[1] if calibrated_xy else None,
                "calibrated": calibrated_xy is not None,
                "corners": [(int(x * sx), int(y * sy)) for x, y in corners]}
    return None


def valid_task(payload):
    groups = payload.split("+")
    if len(groups) != 4 or any(len(part) != 3 for part in groups):
        return False
    first, slots1, second, slots2 = groups
    return (all(ch in "123456" for ch in first + second) and
            len(set(first)) == 3 and set(first) == set(second) and
            sorted(slots1) == ["1", "2", "3"] and sorted(slots2) == ["1", "2", "3"])


def legacy_color_frames(records):
    """Reference ASCII codec for comparison; production UART uses V1 frames."""
    mapping = (1, 4, 3)  # Contest RED/GREEN/BLUE -> old color IDs 0/1/2
    positions = []
    for contest_id in mapping:
        found = [r for r in records if r["id"] == contest_id and r["valid"] and r["stable"] and r["pos"] >= 0]
        if len(found) != 1:
            return None
        positions.append(found[0]["pos"])
    if len(set(positions)) != 3:
        return None
    # Explicitly require all three objects and three different zones.
    return "E%d%d%d" % tuple(positions)


def point_in_roi(x, y, roi):
    return roi is not None and roi[0] <= x < roi[0] + roi[2] and roi[1] <= y < roi[1] + roi[3]


def plane_point(cx, cy):
    # Never extrapolate outside the calibrated work plane.
    if PLANE_H is None or len(PLANE_H) != 9 or not point_in_roi(cx, cy, PLANE_ROI):
        return None
    a, b, c, d, e, f, g, h, i = PLANE_H
    divisor = g * cx + h * cy + i
    if abs(divisor) < 1e-8:
        return None
    return ((a * cx + b * cy + c) / divisor, (d * cx + e * cy + f) / divisor)


def detect_rings(frame):
    gray = frame.copy(x_scale=PROCESS_SCALE, y_scale=PROCESS_SCALE).to_grayscale()
    circles = sorted(gray.find_circles(threshold=RING_THRESHOLD, x_margin=10, y_margin=10,
                     r_margin=10, r_min=RING_MIN_RADIUS, r_max=RING_MAX_RADIUS, r_step=2),
                     key=lambda circle: circle.magnitude(), reverse=True)
    sx, sy = frame.width() / gray.width(), frame.height() / gray.height()
    records = []
    for circle in circles:
        cx, cy = int(round(circle.x() * sx)), int(round(circle.y() * sy))
        # Concentric score rings describe one station, not several stations.
        if any(abs(cx - r["cx"]) < 20 and abs(cy - r["cy"]) < 20 for r in records):
            continue
        slots = [slot for slot, roi in RING_SLOT_ROIS.items() if point_in_roi(cx, cy, roi)]
        slot = slots[0] if len(slots) == 1 else 0
        radius = int(round(circle.r() * sx))
        records.append({"id": slot, "slot": slot, "cx": cx, "cy": cy,
                        "rect": (cx-radius, cy-radius, 2*radius, 2*radius),
                        "radius": radius, "pixels": 0, "pos": -1,
                        "valid": True, "stable": False})
        if len(records) >= 3:
            break
    # Multiple detected centers within one configured station is ambiguous.
    for r in records:
        if r["slot"] and sum(other["slot"] == r["slot"] for other in records) > 1:
            r["valid"] = False
    return records


def crc16(data):
    value = 0xFFFF
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 0xFFFF if value & 0x8000 else (value << 1) & 0xFFFF
    return value


def wire_frame(seq, kind, *fields):
    body = ",".join(["V1", str(seq), kind] + [str(value) for value in fields])
    data = body.encode("ascii")
    if not 0 <= seq <= 65535 or any(ch in body for ch in "$*\r\n") or len(data) > 240:
        raise ValueError("Invalid protocol frame")
    return b"$" + data + ("*%04X\r\n" % crc16(data)).encode("ascii")


class FrameParser:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data):
        frames = []
        for byte in data:
            if byte == 36:  # '$' always resynchronizes.
                self.buffer = bytearray(b"$")
            elif self.buffer:
                if byte == 10:
                    raw = bytes(self.buffer[1:]).rstrip(b"\r")
                    self.buffer = bytearray()
                    try:
                        body, checksum = raw.rsplit(b"*", 1)
                        if len(checksum) != 4 or crc16(body) != int(checksum, 16):
                            raise ValueError("CRC")
                        fields = body.decode("ascii").split(",")
                        if len(fields) < 3 or fields[0] != "V1" or not fields[1].isdigit():
                            raise ValueError("Header")
                        seq = int(fields[1])
                        if seq > 65535:
                            raise ValueError("Sequence")
                        frames.append((seq, fields[2], fields[3:]))
                    except (ValueError, UnicodeError):
                        self.errors += 1
                elif len(self.buffer) < 248 and (byte == 13 or 32 <= byte <= 126):
                    self.buffer.append(byte)
                else:
                    self.buffer = bytearray()
                    self.errors += 1
        return frames


class VisionLink:
    def __init__(self):
        self.uart = None
        self.parser = FrameParser()
        if UART_ENABLE:
            if UART_ID not in (1, 2, 3, 4) or not isinstance(UART_TX_PIN, int) or not isinstance(UART_RX_PIN, int):
                raise ValueError("Set exposed UART_ID/TX/RX before enabling UART")
            if UART_TX_PIN == UART_RX_PIN:
                raise ValueError("TX and RX must differ")
            from machine import UART, FPIOA
            fpioa = FPIOA()
            fpioa.set_function(UART_TX_PIN, getattr(fpioa, "UART%d_TXD" % UART_ID))
            fpioa.set_function(UART_RX_PIN, getattr(fpioa, "UART%d_RXD" % UART_ID))
            self.uart = UART(getattr(UART, "UART%d" % UART_ID), baudrate=UART_BAUD,
                             bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)

    def poll(self):
        if self.uart is None or not self.uart.any():
            return []
        return self.parser.feed(self.uart.read(256) or b"")

    def send(self, seq, kind, *fields):
        data = wire_frame(seq, kind, *fields)
        if self.uart is not None:
            sent = 0
            while sent < len(data):
                count = self.uart.write(data[sent:])
                if not count:
                    raise OSError("UART write timeout")
                sent += count
        return data

    def close(self):
        if self.uart is not None:
            self.uart.deinit()


def hex_payload(payload):
    data = payload.encode("utf-8")
    if len(data) > 64:
        return None
    return "".join("%02X" % byte for byte in data)


def result_frames(seq, mode, records, marker, payload, qr_streak, now_ms):
    """Fresh measurements only. DONE count is the number of data records."""
    frames = []
    if mode in ("COLOR", "RING"):
        for r in records:
            xy = plane_point(r["cx"], r["cy"])
            frames.append(wire_frame(seq, "BLOCK" if mode == "COLOR" else "RING",
                          r["id"], r["cx"], r["cy"], r["cx"]-REFERENCE_PIXEL[0], r["cy"]-REFERENCE_PIXEL[1],
                          r["pixels"], r.get("slot", 0), int(r["valid"]), int(r["stable"]), int(xy is not None),
                          "%.3f" % xy[0] if xy else "NA", "%.3f" % xy[1] if xy else "NA"))
        if not any(r["valid"] for r in records):
            frames.append(wire_frame(seq, "NO_TARGET"))
    elif mode == "ARUCO":
        if marker:
            xy = plane_point(marker["cx"], marker["cy"])
            frames.append(wire_frame(seq, "ARUCO", marker["id"], int(round(marker["cx"])), int(round(marker["cy"])),
                          int(round(marker["cx"]-REFERENCE_PIXEL[0])), int(round(marker["cy"]-REFERENCE_PIXEL[1])),
                          0, 0, 1, 0, int(xy is not None), "%.3f" % xy[0] if xy else "NA", "%.3f" % xy[1] if xy else "NA"))
        else:
            frames.append(wire_frame(seq, "NO_MARKER"))
    elif mode == "QR":
        encoded = hex_payload(payload) if payload is not None else None
        if encoded is not None:
            frames.append(wire_frame(seq, "QR", int(valid_task(payload)), int(qr_streak >= 3), encoded))
        elif payload is not None:
            frames.append(wire_frame(seq, "ERROR", "QR_TOO_LONG"))
        else:
            frames.append(wire_frame(seq, "NO_QR"))
    count = sum(1 for frame in frames if frame.split(b",")[2] in (b"BLOCK", b"RING", b"ARUCO", b"QR"))
    frames.append(wire_frame(seq, "DONE", count, now_ms & 0xFFFFFFFF))
    return frames


class CameraMux:
    """Sequential onboard / USB acquisition. No unverified concurrent DMA."""
    def __init__(self, sensor_class):
        self.sensor_class = sensor_class
        self.sensor = None
        self.uvc = None
        self.source = None
        self.prepare_onboard()

    def prepare_onboard(self):
        if self.sensor is None:
            self.sensor = self.sensor_class()
            self.sensor.reset()
            self.sensor.set_framesize(width=WIDTH, height=HEIGHT)
            self.sensor.set_pixformat(self.sensor_class.RGB565)
            self.sensor.set_hmirror(False)
            self.sensor.set_vflip(False)

    def snapshot(self, mode):
        target = "USB" if mode == "QR" and QR_CAMERA == "USB" else "ONBOARD"
        if target != self.source:
            self.stop()
            if target == "USB":
                from media.uvc import UVC
                self.uvc = UVC
                connected, info = UVC.probe()
                if not connected:
                    raise OSError("USB_CAMERA_ABSENT")
                fourcc = getattr(UVC, "FOURCC_MJPEG", getattr(UVC, "FORMAT_MJPEG", None))
                if fourcc is None:
                    raise OSError("USB_API_UNSUPPORTED")
                ok, actual = UVC.select_video_mode(UVC.video_mode(WIDTH, HEIGHT, fourcc, 30))
                if not ok or not UVC.start(cvt=False):
                    raise OSError("USB_MODE_FAILED")
                print("[GX_USB]", info, actual)
            else:
                self.prepare_onboard()
                self.sensor.run()
            self.source = target
            time.sleep_ms(1500)
        frame = self.uvc.snapshot(timeout_ms=1000) if target == "USB" else self.sensor.snapshot()
        if frame is None:
            raise OSError("CAMERA_TIMEOUT")
        if target == "USB":
            frame = frame.to_rgb565()
        if frame.width() != WIDTH or frame.height() != HEIGHT:
            raise OSError("CAMERA_SIZE_MISMATCH")
        return frame

    def stop(self):
        if self.uvc is not None:
            self.uvc.stop()
            self.uvc = None
        if self.sensor is not None and self.source == "ONBOARD":
            self.sensor.stop()
        self.source = None


def self_test(np, image):
    global DETECT_ROI
    previous_roi = DETECT_ROI
    DETECT_ROI = (0, 0, WIDTH, HEIGHT)
    # Exercises actual board RGB565, ulab and morphology without camera or wiring.
    frame = image.Image(WIDTH, HEIGHT, image.RGB565)
    frame.draw_rectangle((0, 0, WIDTH, HEIGHT), color=(255,255,255), fill=True)
    patches = ((1,(240,20,20)), (2,(240,230,20)), (3,(20,20,220)),
               (4,(20,210,20)), (5,(20,20,20)), (6,(120,190,220)))
    for index, (color_id, rgb) in enumerate(patches):
        frame.draw_rectangle((30+index*100,180,60,60),color=rgb,fill=True)
    try:
        records = detect_colors(frame, np, image)
    finally:
        DETECT_ROI = previous_roi
    assert sorted(r["id"] for r in records if r["valid"]) == [1,2,3,4,5,6], records
    print("[GX_SELF_TEST] six HSV colors + morphology PASS")
    assert crc16(b"123456789") == 0x29B1
    assert FrameParser().feed(wire_frame(7,"COLOR")) == [(7,"COLOR",[])]
    assert valid_task("156+123+516+231") and not valid_task("Good")
    assert decode_aruco_cells([0]*36) is None
    print("[GX_SELF_TEST] CRC + request + QR validation PASS")


def main():
    global PLANE_H, PLANE_ROI
    import image
    from ulab import numpy as np
    if MODE == "SELF_TEST":
        self_test(np, image)
        return
    from media.sensor import Sensor
    from media.display import Display
    from media.media import MediaManager
    camera = link = None
    display_ready = media_ready = False
    try:
        if MODE not in ("COLOR", "RING", "ARUCO", "QR", "HSV_SAMPLE", "IDLE") or QR_CAMERA not in ("ONBOARD", "USB"):
            raise ValueError("Unknown MODE")
        print("[GX_START] mode=%s board=%s" % (MODE, os.uname()))
        print("[GX_BUILD] SIX_COLOR_UART3_V2 colors=%s" % (ACTIVE_COLOR_IDS,))
        print("[GX_INFO] six-color HSV seeds; UART=%d; QR_CAMERA=%s" % (UART_ENABLE, QR_CAMERA))
        link = VisionLink()
        camera = CameraMux(Sensor)
        Display.init(Display.ST7701, width=WIDTH, height=HEIGHT, to_ide=True)
        display_ready = True
        MediaManager.init()
        media_ready = True
        runtime_mode = MODE
        default_plane = (PLANE_H, PLANE_ROI)
        active_profile = "DEFAULT"
        tracker = StableTracker()
        last_print = time.ticks_ms()
        frames = 0
        qr_previous = None
        qr_streak = 0
        previous_good = False
        while True:
            os.exitpoint()
            pending = None
            for seq, command, args in link.poll():
                if args and not (len(args) == 1 and command in ("COLOR", "RING", "ARUCO") and args[0] in CALIBRATIONS):
                    link.send(seq, "ERROR", "BAD_ARGS")
                    link.send(seq, "DONE", 0, time.ticks_ms())
                elif command == "PING":
                    link.send(seq, "PONG", "K230", "1", runtime_mode)
                    link.send(seq, "DONE", 0, time.ticks_ms())
                elif command in ("COLOR", "RING", "ARUCO", "QR", "STOP"):
                    if pending is not None:
                        link.send(seq, "ERROR", "BUSY")
                        link.send(seq, "DONE", 0, time.ticks_ms())
                        continue
                    new_mode = "IDLE" if command == "STOP" else command
                    profile = args[0] if args else "DEFAULT"
                    if new_mode != runtime_mode or profile != active_profile:
                        tracker = StableTracker()
                        qr_streak, qr_previous, previous_good = 0, None, False
                    PLANE_H, PLANE_ROI = CALIBRATIONS[profile] if args else default_plane
                    active_profile = profile
                    runtime_mode = new_mode
                    pending = seq
                else:
                    link.send(seq, "ERROR", "BAD_COMMAND")
                    link.send(seq, "DONE", 0, time.ticks_ms())
            if runtime_mode == "IDLE":
                camera.stop()
                if pending is not None:
                    link.send(pending, "STOPPED")
                    link.send(pending, "DONE", 0, time.ticks_ms())
                time.sleep_ms(20)
                continue
            now = time.ticks_ms()
            report = time.ticks_diff(now, last_print) >= PRINT_INTERVAL_MS
            records, marker, codes = [], None, []
            payload = None
            sample_text = None
            try:
                frame = camera.snapshot(runtime_mode)
                if runtime_mode == "COLOR":
                    records = detect_colors(frame, np, image)
                    tracker.update(records)
                elif runtime_mode == "RING":
                    records = detect_rings(frame)
                    # Only mapped stations have persistent identities for tracking.
                    tracker.update([r for r in records if r["slot"] != 0])
                elif runtime_mode == "ARUCO":
                    marker = detect_marker(frame)
                elif runtime_mode == "QR":
                    codes = frame.find_qrcodes()
                    payload = codes[0].payload() if len(codes) == 1 else None
                    qr_streak = qr_streak + 1 if payload is not None and payload == qr_previous else 1 if payload else 0
                    qr_previous = payload
                    if payload == "Good" and qr_streak >= 3 and not previous_good:
                        print("Good")
                    previous_good = payload == "Good" and qr_streak >= 3
                    if report and payload:
                        print("[GX_QR] payload=%s valid=%d confirmed=%d" %
                              (payload, valid_task(payload), qr_streak >= 3))
                else:
                    rgb = frame.copy(roi=(300, 220, 40, 40)).to_rgb888()
                    h, s, v = rgb_to_hsv(rgb.to_numpy_ref(), np)
                    # Unwrap red hue around zero before taking the median.
                    if SAMPLE_COLOR_ID == 1:
                        h = np.where(h > 90, h - 180, h)
                    hue = float(np.median(h)) % 180
                    sample_text = "HSV %.0f %.0f %.0f" % (hue, np.median(s), np.median(v))
                    if report:
                        print("[GX_HSV_SAMPLE] known_id=%d %s" % (SAMPLE_COLOR_ID, sample_text))
                if pending is not None:
                    for data in result_frames(pending, runtime_mode, records, marker, payload, qr_streak, time.ticks_ms()):
                        # Reuse transport for already encoded transaction frames.
                        if link.uart is not None:
                            sent = 0
                            while sent < len(data):
                                count = link.uart.write(data[sent:])
                                if not count:
                                    raise OSError("UART write timeout")
                                sent += count
            except Exception as exc:
                # CanMV may raise a plain Exception to stop a script.
                if "IDE interrupt" in str(exc):
                    raise
                tracker = StableTracker()
                qr_previous, qr_streak = None, 0
                print("[GX_FRAME_ERROR]", runtime_mode, exc)
                if pending is not None:
                    link.send(pending, "ERROR", "VISION_FAILED")
                    link.send(pending, "DONE", 0, time.ticks_ms())
                frame = image.Image(WIDTH, HEIGHT, image.RGB565)
                frame.draw_string_advanced(0, 50, 24, "VISION ERROR: %s" % str(exc)[:60], color=(255, 80, 80))
                Display.show_image(frame)
                time.sleep_ms(500)
                continue
            # All measurements above; drawing below cannot contaminate masks.
            if runtime_mode == "COLOR" and DETECT_ROI:
                frame.draw_rectangle(DETECT_ROI, color=(180,180,180), thickness=1)
            for record in records:
                color = DRAW_COLORS[record["id"]] if runtime_mode == "COLOR" else (0,255,0)
                frame.draw_rectangle(record["rect"], color=color, thickness=2)
                frame.draw_cross(record["cx"], record["cy"], color=color, thickness=2)
                label = (COLOR_NAMES[record["id"]] if runtime_mode == "COLOR" else "RING slot=%d" % record["slot"]) if record["valid"] else "AMBIGUOUS"
                frame.draw_string_advanced(record["rect"][0], max(30, record["rect"][1] - 22), 20, label, color=color)
                if report:
                    print("[GX_BLOCK] id=%d name=%s cx=%d cy=%d dx=%d dy=%d pos=%d pixels=%d valid=%d stable=%d" %
                          (record["id"], label, record["cx"], record["cy"],
                           record["cx"] - WIDTH // 2, record["cy"] - HEIGHT // 2, record["pos"],
                           record["pixels"], record["valid"], record["stable"]))
            if marker:
                corners = marker["corners"]
                for i in range(4):
                    frame.draw_line(corners[i][0], corners[i][1], corners[(i + 1) % 4][0],
                                    corners[(i + 1) % 4][1], color=(0, 255, 0), thickness=2)
                frame.draw_cross(int(marker["cx"]), int(marker["cy"]), color=(0, 255, 0), thickness=2)
                if report:
                    print("[GX_ARUCO]", marker)
            for code in codes:
                frame.draw_rectangle(code.rect(), color=(0, 255, 0), thickness=2)
            if runtime_mode == "HSV_SAMPLE":
                frame.draw_rectangle((300, 220, 40, 40), color=(255, 255, 255), thickness=2)
            frame.draw_string_advanced(0, 0, 24, "GX %s %s" % (runtime_mode, sample_text or ""), color=(255, 255, 255))
            Display.show_image(frame)
            frames += 1
            if report:
                elapsed = time.ticks_diff(time.ticks_ms(), last_print)
                if runtime_mode in ("COLOR", "RING") and not records:
                    print("[GX_NO_TARGET] count=0")
                if runtime_mode == "ARUCO" and marker is None:
                    print("[GX_NO_MARKER] id=%d" % MARKER_ID)
                print("[GX_STATUS] mode=%s fps=%.2f" % (runtime_mode, frames * 1000 / max(1, elapsed)))
                last_print = time.ticks_ms()
                frames = 0
            gc.collect()
    except KeyboardInterrupt:
        print("[GX_STOP]")
    except Exception as exc:
        sys.print_exception(exc)
    finally:
        if link is not None:
            try:
                link.close()
            except Exception as exc:
                print("[GX_CLEANUP] uart", exc)
        if camera is not None:
            try:
                camera.stop()
            except Exception as exc:
                print("[GX_CLEANUP] sensor", exc)
        if display_ready:
            try:
                Display.deinit()
            except Exception as exc:
                print("[GX_CLEANUP] display", exc)
        time.sleep_ms(100)
        if media_ready:
            try:
                MediaManager.deinit()
            except Exception as exc:
                print("[GX_CLEANUP] media", exc)


if __name__ == "__main__":
    main()
