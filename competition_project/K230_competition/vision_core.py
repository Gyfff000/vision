# K230 port of GX silver HSV pipeline; see docs/移植说明.md.
import os
import sys
import time
from config import *

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
    """记录每种目标最近几帧的位置，用于判断物料是否已经稳定。"""
    def __init__(self):
        self.history = {}  # {目标ID: [(cx, cy), ...]}，最多保留STABLE_FRAMES个中心点。

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


def detect_colors(frame, np, image, color_ids=None):
    roi = DETECT_ROI or (0, 0, frame.width(), frame.height())
    small = frame.copy(roi=roi, x_scale=PROCESS_SCALE, y_scale=PROCESS_SCALE)
    rgb = small.to_rgb888()
    h, s, v = rgb_to_hsv(rgb.to_numpy_ref(), np)
    records = []
    pw, ph = small.width(), small.height()
    sx, sy = roi[2] / pw, roi[3] / ph
    for color_id in (color_ids or ACTIVE_COLOR_IDS):
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
    gray = frame.copy(x_scale=RING_SCALE, y_scale=RING_SCALE).to_grayscale()
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
    """接收并校验STM32发来的V1 ASCII请求帧。"""
    def __init__(self):
        self.buffer = bytearray()  # 从字符'$'开始收集的当前串口帧。
        self.errors = 0            # CRC、字符范围或帧格式错误的累计次数。

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
    """K230与STM32之间的UART3通信接口。"""
    def __init__(self):
        self.uart = None             # UART_ENABLE为真时保存实际UART3对象。
        self.parser = FrameParser()  # 将UART字节流解析成(seq, command, args)。
        if UART_ENABLE:
            if UART_ID not in (1, 2, 3, 4) or not isinstance(UART_TX_PIN, int) or not isinstance(UART_RX_PIN, int):
                raise ValueError("Set exposed UART_ID/TX/RX before enabling UART")
            if UART_TX_PIN == UART_RX_PIN:
                raise ValueError("TX and RX must differ")
            from machine import UART, FPIOA
            fpioa = FPIOA()
            fpioa.set_function(UART_TX_PIN, getattr(fpioa, "UART%d_TXD" % UART_ID), ie=0, oe=1)
            fpioa.set_function(UART_RX_PIN, getattr(fpioa, "UART%d_RXD" % UART_ID), ie=1, oe=0)
            self.uart = UART(getattr(UART, "UART%d" % UART_ID), baudrate=UART_BAUD,
                             bits=UART.EIGHTBITS, parity=UART.PARITY_NONE, stop=UART.STOPBITS_ONE)
            print("[GX_UART] UART%d TX=GPIO%d RX=GPIO%d BAUD=%d" % (UART_ID, UART_TX_PIN, UART_RX_PIN, UART_BAUD))

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
    elif mode == "QR":
        encoded = hex_payload(payload) if payload is not None else None
        if encoded is not None:
            frames.append(wire_frame(seq, "QR", int(task_valid(payload)), int(qr_streak >= 3), encoded))
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
        self.sensor_class = sensor_class  # K230自带摄像头的Sensor类。
        self.sensor = None                # 已创建的自带摄像头对象。
        self.uvc = None                   # 外接USB扫码摄像头的UVC接口对象。
        self.source = None                # 当前启用的图像源：ONBOARD、USB或None。
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


def task_valid(raw):
    from workflow import parse_task
    try:
        parse_task(raw)
        return True
    except ValueError:
        return False
