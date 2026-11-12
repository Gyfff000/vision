# Run temporarily in CanMV IDE on K230; no writes to the SD card or main.py.
# USB camera -> MJPEG -> RGB565 -> Yahboom LCD + IDE. No onboard camera/AI/UART.
# API reference: https://www.kendryte.com/k230_canmv/en/v1.6/api/mpp/media_uvc.html
import os
import sys
import time
import gc

WIDTH, HEIGHT = 640, 480
CAMERA_FPS = 30
IDE_PREVIEW = True
PROBE_TIMEOUT_MS = 10000
FRAME_TIMEOUT_MS = 5000
KEEP_ERROR_SCREEN = True       # Retain diagnostics on LCD during standalone tests.


def main():
    uvc = display = manager = None
    display_ready = media_ready = uvc_ready = False
    try:
        print("[USB_TEST] USB_CAMERA_PREVIEW_20261112_DIAG2")
        print("[USB_BOARD]", os.uname())
        from media.display import Display
        from media.media import MediaManager
        import image
        display, manager = Display, MediaManager
        display.init(display.ST7701, width=WIDTH, height=HEIGHT, to_ide=IDE_PREVIEW)
        display_ready = True
        manager.init()
        media_ready = True
        try:
            from media.uvc import UVC
        except ImportError as exc:
            print("[USB_UNSUPPORTED] Firmware has no media.uvc; camera health is unknown.")
            print(exc)
            raise OSError("USB_UNSUPPORTED: firmware has no media.uvc")
        uvc = UVC
        status = image.Image(WIDTH, HEIGHT, image.RGB565)
        status.draw_rectangle((0, 0, WIDTH, HEIGHT), color=(0,0,0), fill=True)
        status.draw_string_advanced(10, 30, 24, "USB CAMERA TEST", color=(255,255,255))
        status.draw_string_advanced(10, 80, 22, "Waiting for USB camera...", color=(255,255,0))
        display.show_image(status)
        del status

        stamp = time.ticks_ms()
        print("[USB_WAIT] Detecting camera for up to 10 seconds...")
        while True:
            os.exitpoint()
            connected, info = uvc.probe()
            if connected:
                print("[USB_FOUND]", info)
                break
            if time.ticks_diff(time.ticks_ms(), stamp) >= PROBE_TIMEOUT_MS:
                raise OSError("USB_NOT_FOUND: check Host support, power and data cable")
            time.sleep_ms(100)

        if hasattr(uvc, "list_video_mode"):
            for mode in uvc.list_video_mode():
                print("[USB_SUPPORTED_MODE]", mode)
        fmt = getattr(uvc, "FOURCC_MJPEG", getattr(uvc, "FORMAT_MJPEG", None))
        if fmt is None:
            raise OSError("USB_API_UNSUPPORTED: no MJPEG format constant")
        requested = uvc.video_mode(WIDTH, HEIGHT, fmt, CAMERA_FPS)
        uvc_ready = True  # Also clean up partial device initialization on failure.
        ok, actual = uvc.select_video_mode(requested)
        print("[USB_MODE] success=%s actual=%s" % (ok, actual))
        if not ok:
            raise OSError("USB_MODE_FAILED: try CAMERA_FPS=15 or a supported mode")
        # Explicitly disable hardware NV12 decoding: MJPEG can then use to_rgb565().
        if not uvc.start(cvt=False):
            raise OSError("USB_START_FAILED")

        frames = 0
        total = 0
        fps = 0.0
        last_report = last_frame = last_gc = time.ticks_ms()
        while True:
            os.exitpoint()
            raw = uvc.snapshot(timeout_ms=1000)
            if raw is not None:
                frame = raw.to_rgb565()
                if frame.width() > WIDTH or frame.height() > HEIGHT:
                    raise OSError("USB_FRAME_TOO_LARGE: choose a smaller supported mode")
                frame.draw_string_advanced(0, 0, 22, "USB FPS %.1f" % fps, color=(255,255,0))
                display.show_image(frame)
                frames += 1
                total += 1
                last_frame = time.ticks_ms()
                if total == 1:
                    print("[USB_FRAME_OK] Live USB image received: %dx%d" % (frame.width(),frame.height()))
                del frame
            del raw
            now = time.ticks_ms()
            if time.ticks_diff(now, last_frame) >= FRAME_TIMEOUT_MS:
                raise OSError("USB_FRAME_TIMEOUT: device detected but no new images")
            elapsed = time.ticks_diff(now, last_report)
            if elapsed >= 1000:
                fps = frames * 1000 / elapsed
                print("[USB_FPS] %.1f total_frames=%d" % (fps,total))
                frames = 0
                last_report = now
            if time.ticks_diff(now, last_gc) >= 1000:
                gc.collect()
                last_gc = now
    except KeyboardInterrupt:
        print("[USB_STOP] Stopped by user")
    except Exception as exc:
        if "IDE interrupt" in str(exc):
            print("[USB_STOP] IDE stopped the program")
            return
        print("[USB_ERROR]", exc)
        print("[USB_NOTE] Failure here alone does not prove a faulty camera.")
        sys.print_exception(exc)
        if display_ready:
            try:
                status = image.Image(WIDTH, HEIGHT, image.RGB565)
                status.draw_rectangle((0, 0, WIDTH, HEIGHT), color=(0,0,0), fill=True)
                status.draw_string_advanced(10, 20, 26, "USB CAMERA ERROR", color=(255,80,80))
                reason = str(exc)
                status.draw_string_advanced(10, 85, 30, reason.split(":")[0][:30], color=(255,255,255))
                for start in range(0, min(len(reason), 135), 45):
                    status.draw_string_advanced(10, 160+30*(start//45), 20, reason[start:start+45], color=(255,255,0))
                status.draw_string_advanced(10, 290, 20, "Please photograph this full screen", color=(255,255,255))
                status.draw_string_advanced(10, 340, 18, "USB PREVIEW DIAG2", color=(0,255,0))
                display.show_image(status)
                while KEEP_ERROR_SCREEN:
                    os.exitpoint()
                    time.sleep_ms(50)
            except (Exception, KeyboardInterrupt):
                pass
    finally:
        if uvc_ready:
            try: uvc.stop()
            except Exception as exc: print("[USB_CLEANUP]", exc)
        if display_ready:
            try: display.deinit()
            except Exception as exc: print("[USB_CLEANUP]", exc)
        time.sleep_ms(100)
        if media_ready:
            try: manager.deinit()
            except Exception as exc: print("[USB_CLEANUP]", exc)
        print("[USB_TEST_DONE]")


if __name__ == "__main__":
    main()
