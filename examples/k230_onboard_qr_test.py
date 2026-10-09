# Run this file in CanMV IDE on the K230, not desktop Python.
# Initial validation: onboard camera -> QR decode -> LCD + IDE preview/terminal.
# Camera setup follows the CanMV QR example and Yahboom Sensor() examples.
import time
import os
import gc
import sys

WIDTH = 640
HEIGHT = 480
DECODE_ENABLED = True  # Set False to check only the live camera image.
CONFIRM_FRAMES = 3     # Test setting; not a competition rule.


def is_valid_task(payload):
    """Validate the preliminary contest's two batches and slot permutations."""
    groups = payload.split("+")
    if len(groups) != 4 or any(len(group) != 3 for group in groups):
        return False
    first, slots1, second, slots2 = groups
    if any(ch not in "123456" for ch in first + second):
        return False
    if len(set(first)) != 3 or set(first) != set(second):
        return False
    return sorted(slots1) == ["1", "2", "3"] and sorted(slots2) == ["1", "2", "3"]


def main():
    from media.sensor import Sensor
    from media.display import Display
    from media.media import MediaManager

    sensor = None
    display_ready = False
    media_ready = False
    try:
        print("[START] onboard QR test; decode =", DECODE_ENABLED)
        print("[BOARD]", os.uname())
        sensor = Sensor()
        sensor.reset()
        sensor.set_framesize(width=WIDTH, height=HEIGHT)
        sensor.set_pixformat(Sensor.GRAYSCALE)
        sensor.set_hmirror(False)
        sensor.set_vflip(False)

        # Yahboom K230 LCD configuration; mirror the same image to the IDE.
        Display.init(Display.ST7701, width=WIDTH, height=HEIGHT, to_ide=True)
        display_ready = True
        MediaManager.init()
        media_ready = True
        sensor.run()
        time.sleep_ms(1000)

        previous = None
        streak = 0
        announced = False
        frames = 0
        last_status = time.ticks_ms()

        while True:
            os.exitpoint()
            img = sensor.snapshot()
            codes = img.find_qrcodes() if DECODE_ENABLED else []
            for code in codes:
                img.draw_rectangle(code.rect(), color=255, thickness=2)

            # Only confirm one unambiguous code, in consecutive frames.
            payload = codes[0].payload() if len(codes) == 1 else None
            if payload is None:
                previous = None
                streak = 0
                announced = False
            else:
                if payload != previous:
                    print("[QR]", payload)
                    print("[TASK_VALID]", is_valid_task(payload))
                    previous = payload
                    streak = 0
                    announced = False
                streak += 1
                if is_valid_task(payload) and streak >= CONFIRM_FRAMES and not announced:
                    print("[TASK_OK]", payload)
                    announced = True

            Display.show_image(img)
            frames += 1
            now = time.ticks_ms()
            elapsed = time.ticks_diff(now, last_status)
            if elapsed >= 1000:
                print("[STATUS] fps=%.1f codes=%d streak=%d" %
                      (frames * 1000 / elapsed, len(codes), streak))
                frames = 0
                last_status = now
            gc.collect()
    except KeyboardInterrupt:
        print("[STOP] user stopped")
    except Exception as exc:
        sys.print_exception(exc)
    finally:
        # Release each resource even if another cleanup step fails.
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
