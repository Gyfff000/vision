"""Windows preview selecting the USB camera by its DirectShow name."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / "camera_deps"))


def select_camera(names, target):
    matches = [i for i, name in enumerate(names) if name.casefold() == target.casefold()]
    if len(matches) != 1:
        raise RuntimeError("Expected one camera named %r; found %d. Available: %s" %
                           (target, len(matches), ", ".join(names) or "none"))
    return matches[0]


class CameraControls:
    def __init__(self, names, current):
        self.names, self.current = names, current
        self.pending = None
        self.width = 640

    def mouse(self, event, x, y, flags, userdata):
        # OpenCV EVENT_LBUTTONDOWN=1; only the top-row buttons select cameras.
        if event == 1 and 0 <= y < 44 and 0 <= x < self.width:
            self.pending = min(len(self.names)-1, x * len(self.names) // self.width)

    def key(self, key):
        if key in (ord("c"), ord("C"), 9):
            self.pending = (self.current+1) % len(self.names)
        elif ord("0") <= key <= ord("9") and key-ord("0") < len(self.names):
            self.pending = key-ord("0")
        elif key in (ord("r"), ord("R")):
            self.pending = self.current


def open_camera(cv2, index):
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    try:
        if not capture.isOpened():
            raise RuntimeError("Cannot open camera. Close Windows Camera/meeting apps; press R to retry.")
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        capture.set(cv2.CAP_PROP_FPS, 30)
        return capture
    except Exception:
        capture.release()
        raise


def run_preview(cv2, names, index, check_only=False):
    import numpy as np
    controls = CameraControls(names, index)
    window = "Camera Preview - click a camera above the picture"
    capture = None
    last_image = None
    window_ready = False
    window_started = time.monotonic()
    total = frames = 0
    fps = 0.0
    last_frame = last_report = time.monotonic()
    status = "Opening camera..."
    try:
        if not check_only:
            cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
            window_ready = True
            cv2.setMouseCallback(window, controls.mouse)
            print("[CONTROLS] Click camera buttons, or focus the picture and press C/Tab/0/1. ESC/Q closes.", flush=True)
        controls.pending = index
        while True:
            if controls.pending is not None:
                index = controls.pending
                controls.current, controls.pending = index, None
                if capture is not None:
                    capture.release()
                    capture = None
                last_image = None
                total = frames = 0
                fps = 0.0
                last_frame = last_report = time.monotonic()
                print("[SELECTED] %s (DirectShow index %d)" % (names[index], index), flush=True)
                try:
                    capture = open_camera(cv2, index)
                    status = "Waiting for image..."
                except RuntimeError as exc:
                    if check_only:
                        raise
                    status = str(exc)
                    print("[CAMERA_ERROR]", status, flush=True)
            now = time.monotonic()
            if capture is not None:
                ok, frame = capture.read()
                now = time.monotonic()
                if ok and frame is not None and frame.size:
                    last_image = frame
                    last_frame = now
                    total += 1
                    frames += 1
                    status = "Live image"
                    if total == 1:
                        print("[FRAME_OK] %s %dx%d" % (names[index], frame.shape[1], frame.shape[0]), flush=True)
                    if check_only and total >= 3:
                        print("[CHECK_OK] Three live frames received from " + names[index], flush=True)
                        return 0
                elif now-last_frame >= (10 if total == 0 else 5):
                    message = "No image. Check cable/permissions; close other camera apps; press R to retry."
                    if check_only:
                        raise RuntimeError(message)
                    print("[CAMERA_ERROR]", message, flush=True)
                    status, last_image = message, None
                    capture.release()
                    capture = None
                else:
                    status = "Waiting for a new image..."
            if check_only:
                continue
            if now-last_report >= 1:
                fps = frames/(now-last_report)
                frames = 0
                last_report = now
            # Keep the selector visible even when a camera is busy or disconnected.
            picture = last_image if last_image is not None else np.zeros((480,640,3), dtype=np.uint8)
            if picture.shape[1] != 640:
                picture = cv2.resize(picture, (640, max(1, round(picture.shape[0]*640/picture.shape[1]))))
            canvas = cv2.copyMakeBorder(picture, 108, 0, 0, 0, cv2.BORDER_CONSTANT, value=(30,30,30))
            controls.width = canvas.shape[1]
            for camera_index, name in enumerate(names):
                x1, x2 = camera_index*controls.width//len(names), (camera_index+1)*controls.width//len(names)
                color = (45,115,45) if camera_index == controls.current else (75,75,75)
                cv2.rectangle(canvas, (x1+2,2), (x2-2,42), color, -1)
                cv2.putText(canvas, "%d: %s" % (camera_index,name), (x1+9,29), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
            cv2.putText(canvas, "%s | FPS %.1f" % (names[index],fps), (10,65), cv2.FONT_HERSHEY_SIMPLEX, .55, (0,255,0), 1)
            cv2.putText(canvas, "C/Tab: switch | 0/1: select | R: retry | Esc/Q: close", (10,92), cv2.FONT_HERSHEY_SIMPLEX, .5, (255,255,255), 1)
            if status != "Live image":
                # Split long diagnostic text to fit the preview without hiding controls.
                for line in range(0, len(status), 72):
                    cv2.putText(canvas, status[line:line+72], (10,145+25*(line//72)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0,200,255), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(10) & 255
            if key in (27, ord("q"), ord("Q")):
                print("[CLOSED] Preview closed by keyboard.", flush=True)
                break
            controls.key(key)
            if time.monotonic()-window_started > .5 and cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                print("[CLOSED] Preview window closed.", flush=True)
                break
    finally:
        if capture is not None:
            capture.release()
        if window_ready:
            cv2.destroyAllWindows()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-name", default="FHD Camera")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    print("[BUILD] PC_CAMERA_SWITCH_20261017", flush=True)
    import cv2
    from pygrabber.dshow_graph import FilterGraph

    graph = FilterGraph()
    names = graph.get_input_devices()
    for index, name in enumerate(names):
        print("[DEVICE] %d: %s" % (index, name), flush=True)
    if args.list:
        return 0
    index = select_camera(names, args.camera_name)
    # Enumeration and capture use the same DirectShow backend. Never guess index 0.
    return run_preview(cv2, names, index, args.check_only)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print("[ERROR] " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
