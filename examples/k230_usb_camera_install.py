# Run this file ONCE in CanMV IDE, then disconnect and power-cycle.
# Saves files to SD card; never burns/replaces firmware. Preserves prior files.
import os

PAYLOAD = '# Run temporarily in CanMV IDE on K230; no writes to the SD card or main.py.\n# USB camera -> MJPEG -> RGB565 -> Yahboom LCD + IDE. No onboard camera/AI/UART.\n# API reference: https://www.kendryte.com/k230_canmv/en/v1.6/api/mpp/media_uvc.html\nimport os\nimport sys\nimport time\nimport gc\n\nWIDTH, HEIGHT = 640, 480\nCAMERA_FPS = 30\nIDE_PREVIEW = True\nPROBE_TIMEOUT_MS = 10000\nFRAME_TIMEOUT_MS = 5000\nKEEP_ERROR_SCREEN = True       # Retain diagnostics on LCD during standalone tests.\n\n\ndef main():\n    uvc = display = manager = None\n    display_ready = media_ready = uvc_ready = False\n    try:\n        print("[USB_TEST] USB_CAMERA_PREVIEW_20261112_DIAG2")\n        print("[USB_BOARD]", os.uname())\n        from media.display import Display\n        from media.media import MediaManager\n        import image\n        display, manager = Display, MediaManager\n        display.init(display.ST7701, width=WIDTH, height=HEIGHT, to_ide=IDE_PREVIEW)\n        display_ready = True\n        manager.init()\n        media_ready = True\n        try:\n            from media.uvc import UVC\n        except ImportError as exc:\n            print("[USB_UNSUPPORTED] Firmware has no media.uvc; camera health is unknown.")\n            print(exc)\n            raise OSError("USB_UNSUPPORTED: firmware has no media.uvc")\n        uvc = UVC\n        status = image.Image(WIDTH, HEIGHT, image.RGB565)\n        status.draw_rectangle((0, 0, WIDTH, HEIGHT), color=(0,0,0), fill=True)\n        status.draw_string_advanced(10, 30, 24, "USB CAMERA TEST", color=(255,255,255))\n        status.draw_string_advanced(10, 80, 22, "Waiting for USB camera...", color=(255,255,0))\n        display.show_image(status)\n        del status\n\n        stamp = time.ticks_ms()\n        print("[USB_WAIT] Detecting camera for up to 10 seconds...")\n        while True:\n            os.exitpoint()\n            connected, info = uvc.probe()\n            if connected:\n                print("[USB_FOUND]", info)\n                break\n            if time.ticks_diff(time.ticks_ms(), stamp) >= PROBE_TIMEOUT_MS:\n                raise OSError("USB_NOT_FOUND: check Host support, power and data cable")\n            time.sleep_ms(100)\n\n        if hasattr(uvc, "list_video_mode"):\n            for mode in uvc.list_video_mode():\n                print("[USB_SUPPORTED_MODE]", mode)\n        fmt = getattr(uvc, "FOURCC_MJPEG", getattr(uvc, "FORMAT_MJPEG", None))\n        if fmt is None:\n            raise OSError("USB_API_UNSUPPORTED: no MJPEG format constant")\n        requested = uvc.video_mode(WIDTH, HEIGHT, fmt, CAMERA_FPS)\n        uvc_ready = True  # Also clean up partial device initialization on failure.\n        ok, actual = uvc.select_video_mode(requested)\n        print("[USB_MODE] success=%s actual=%s" % (ok, actual))\n        if not ok:\n            raise OSError("USB_MODE_FAILED: try CAMERA_FPS=15 or a supported mode")\n        # Explicitly disable hardware NV12 decoding: MJPEG can then use to_rgb565().\n        if not uvc.start(cvt=False):\n            raise OSError("USB_START_FAILED")\n\n        frames = 0\n        total = 0\n        fps = 0.0\n        last_report = last_frame = last_gc = time.ticks_ms()\n        while True:\n            os.exitpoint()\n            raw = uvc.snapshot(timeout_ms=1000)\n            if raw is not None:\n                frame = raw.to_rgb565()\n                if frame.width() > WIDTH or frame.height() > HEIGHT:\n                    raise OSError("USB_FRAME_TOO_LARGE: choose a smaller supported mode")\n                frame.draw_string_advanced(0, 0, 22, "USB FPS %.1f" % fps, color=(255,255,0))\n                display.show_image(frame)\n                frames += 1\n                total += 1\n                last_frame = time.ticks_ms()\n                if total == 1:\n                    print("[USB_FRAME_OK] Live USB image received: %dx%d" % (frame.width(),frame.height()))\n                del frame\n            del raw\n            now = time.ticks_ms()\n            if time.ticks_diff(now, last_frame) >= FRAME_TIMEOUT_MS:\n                raise OSError("USB_FRAME_TIMEOUT: device detected but no new images")\n            elapsed = time.ticks_diff(now, last_report)\n            if elapsed >= 1000:\n                fps = frames * 1000 / elapsed\n                print("[USB_FPS] %.1f total_frames=%d" % (fps,total))\n                frames = 0\n                last_report = now\n            if time.ticks_diff(now, last_gc) >= 1000:\n                gc.collect()\n                last_gc = now\n    except KeyboardInterrupt:\n        print("[USB_STOP] Stopped by user")\n    except Exception as exc:\n        if "IDE interrupt" in str(exc):\n            print("[USB_STOP] IDE stopped the program")\n            return\n        print("[USB_ERROR]", exc)\n        print("[USB_NOTE] Failure here alone does not prove a faulty camera.")\n        sys.print_exception(exc)\n        if display_ready:\n            try:\n                status = image.Image(WIDTH, HEIGHT, image.RGB565)\n                status.draw_rectangle((0, 0, WIDTH, HEIGHT), color=(0,0,0), fill=True)\n                status.draw_string_advanced(10, 20, 26, "USB CAMERA ERROR", color=(255,80,80))\n                reason = str(exc)\n                status.draw_string_advanced(10, 85, 30, reason.split(":")[0][:30], color=(255,255,255))\n                for start in range(0, min(len(reason), 135), 45):\n                    status.draw_string_advanced(10, 160+30*(start//45), 20, reason[start:start+45], color=(255,255,0))\n                status.draw_string_advanced(10, 290, 20, "Please photograph this full screen", color=(255,255,255))\n                status.draw_string_advanced(10, 340, 18, "USB PREVIEW DIAG2", color=(0,255,0))\n                display.show_image(status)\n                while KEEP_ERROR_SCREEN:\n                    os.exitpoint()\n                    time.sleep_ms(50)\n            except (Exception, KeyboardInterrupt):\n                pass\n    finally:\n        if uvc_ready:\n            try: uvc.stop()\n            except Exception as exc: print("[USB_CLEANUP]", exc)\n        if display_ready:\n            try: display.deinit()\n            except Exception as exc: print("[USB_CLEANUP]", exc)\n        time.sleep_ms(100)\n        if media_ready:\n            try: manager.deinit()\n            except Exception as exc: print("[USB_CLEANUP]", exc)\n        print("[USB_TEST_DONE]")\n\n\nif __name__ == "__main__":\n    main()\n'
LAUNCHER = '# K230 USB camera preview autostart. Original startup is in /sdcard/vision_backup/.\nimport sys\nimport time\ntime.sleep_ms(3000)\nif "/sdcard" not in sys.path:\n    sys.path.insert(0, "/sdcard")\nimport usb_camera_preview\nusb_camera_preview.main()\n'

def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def safe_replace(root, name, content):
    path = root + "/" + name
    temporary = path + ".vision_tmp"
    data = content.encode("utf-8")
    with open(temporary, "wb") as output:
        output.write(data)
    with open(temporary, "rb") as stored:
        if stored.read() != data:
            raise OSError("VERIFY_FAILED: " + name)
    backup = None
    if exists(path):
        number = 1
        backup = root + "/vision_backup/" + name + ".001.bak"
        while exists(backup):
            number += 1
            backup = root + "/vision_backup/" + name + ".%03d.bak" % number
        os.rename(path, backup)
        print("[INSTALL_BACKUP]", backup)
    try:
        os.rename(temporary, path)
    except Exception:
        if backup is not None and not exists(path):
            os.rename(backup, path)
        raise
    with open(path, "rb") as stored:
        if stored.read() != data:
            raise OSError("VERIFY_FAILED: " + name)

def install(root="/sdcard"):
    if not exists(root):
        raise OSError("SD_CARD_NOT_FOUND")
    folder = root + "/vision_backup"
    if not exists(folder):
        os.mkdir(folder)
    safe_replace(root, "usb_camera_preview.py", PAYLOAD)
    safe_replace(root, "main.py", LAUNCHER)
    if hasattr(os, "sync"):
        os.sync()
    print("[INSTALL_OK]", root + "/usb_camera_preview.py")
    print("[INSTALL_OK]", root + "/main.py")
    print("[INSTALL_NEXT] Disconnect IDE, power off, reconnect power; wait for USB_TEST.")

if __name__ == "__main__":
    if "k230" not in str(os.uname()).lower():
        raise RuntimeError("Run installer on K230 using CanMV IDE, not PC Python")
    install()
