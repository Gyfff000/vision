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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-name", default="FHD Camera")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    import cv2
    from pygrabber.dshow_graph import FilterGraph

    graph = FilterGraph()
    names = graph.get_input_devices()
    for index, name in enumerate(names):
        print("[DEVICE] %d: %s" % (index, name), flush=True)
    if args.list:
        return 0
    index = select_camera(names, args.camera_name)
    print("[SELECTED] %s (DirectShow index %d)" % (names[index], index), flush=True)
    # Enumeration and capture use the same DirectShow backend. Never guess index 0.
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    window = "USB Camera - " + names[index] + " (ESC/Q to close)"
    shown = False
    try:
        if not capture.isOpened():
            raise RuntimeError("Cannot open the selected USB camera. Close Windows Camera/meeting apps and retry.")
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        capture.set(cv2.CAP_PROP_FPS, 30)
        deadline = time.monotonic() + 10
        total = frames = 0
        fps = 0.0
        last_frame = last_report = time.monotonic()
        while True:
            ok, frame = capture.read()
            now = time.monotonic()
            if not ok or frame is None or frame.size == 0:
                if (total == 0 and now >= deadline) or (total > 0 and now-last_frame >= 5):
                    raise RuntimeError("No new USB video frames. Check the cable, permissions and other apps using the camera.")
                if shown and cv2.waitKey(10) & 255 in (27, ord("q")):
                    break
                time.sleep(.02)
                continue
            last_frame = now
            total += 1
            frames += 1
            if total == 1:
                print("[FRAME_OK] %s %dx%d" % (names[index], frame.shape[1], frame.shape[0]), flush=True)
            if args.check_only:
                if total >= 3:
                    print("[CHECK_OK] Three live frames received from " + names[index], flush=True)
                    return 0
                continue
            if now-last_report >= 1:
                fps = frames/(now-last_report)
                frames = 0
                last_report = now
            cv2.putText(frame, "%s | FPS %.1f" % (names[index], fps), (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (0,255,0), 2)
            cv2.imshow(window, frame)
            shown = True
            key = cv2.waitKey(1) & 255
            if key in (27, ord("q")) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        capture.release()
        if shown:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print("[ERROR] " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
