"""Scan -> reliable TASK handoff -> 24 confirmed operations, one onboard camera."""
import os
import sys
import time
import gc
import config as cfg
import vision_core as core
from workflow import Workflow, parse_task

def command(work, seq, kind, args, now):
    """Returns (response packets, needs fresh location). Pure and unit tested."""
    def done(count=0):
        return core.wire_frame(seq, "DONE", count, now & 0xFFFFFFFF)
    try:
        if kind == "TASK_ACK" and len(args) == 1:
            work.acknowledge(int(args[0]))
            return [core.wire_frame(seq,"ACK",work.token),done()], False
        if kind == "STEP" and len(args) == 2:
            token, step = int(args[0]), int(args[1])
            work.confirm_step(token,step)
            return [core.wire_frame(seq,"ACK_STEP",token,step),done()], False
        if kind == "HOME_DONE" and len(args) == 1:
            work.complete_home(int(args[0]))
            return [core.wire_frame(seq,"ACK","HOME_DONE"),done()],False
        if kind in ("LOCATE", "COLOR", "RING"):
            if work.state != "RUN":
                raise ValueError("NOT_RUNNING")
            current = work.current()
            if kind != "LOCATE" and kind != current["mode"]:
                raise ValueError("WRONG_MODE")
            if args and args != [current["profile"]]:
                raise ValueError("BAD_PROFILE")
            return [], True
        if args:
            raise ValueError("BAD_ARGS")
        if kind == "PING":
            return [core.wire_frame(seq,"PONG","K230","2",work.mode()),done()], False
        if kind == "STATUS":
            return [core.wire_frame(seq,"CONTEXT",*work.context()),done(1)], False
        if kind == "QR":
            return core.result_frames(seq,"QR",[],None,work.raw,3 if work.raw else 0,now),False
        if kind == "RESET":
            work.reset()
        elif kind == "STOP":
            work.pause()
            return [core.wire_frame(seq,"STOPPED"),done()],False
        elif kind == "RESUME":
            work.resume()
        else:
            raise ValueError("BAD_COMMAND")
        return [core.wire_frame(seq,"ACK",kind),done()],False
    except (ValueError, TypeError, OverflowError) as exc:
        reason=str(exc)
        if reason not in ("TASK_MISMATCH","STEP_MISMATCH","HOME_MISMATCH","NOT_RUNNING",
                          "WRONG_MODE","BAD_PROFILE","BAD_ARGS","BAD_COMMAND"):
            reason="BAD_ARGS"
        return [core.wire_frame(seq,"ERROR",reason),done()],False

def write_packet(link, data):
    if link.uart is not None:
        offset = 0
        while offset < len(data):
            count = link.uart.write(data[offset:])
            if not count:
                raise OSError("UART_WRITE_FAILED")
            offset += count

def fresh_records(frame, work, tracker, np, image):
    current = work.current()
    profile = current["profile"]
    core.PLANE_H, core.PLANE_ROI = cfg.CALIBRATIONS[profile]
    core.DETECT_ROI = cfg.COLOR_ROIS[profile]
    if current["mode"] == "COLOR":
        task_colors = tuple(sorted(set(parse_task(work.raw)[0])))
        records = core.detect_colors(frame,np,image,task_colors)
    else:
        core.RING_SLOT_ROIS = cfg.STATION_ROIS.get(profile,{})
        if set(core.RING_SLOT_ROIS) != {1,2,3}:
            raise ValueError("NO_SLOT_MAP")
        records = core.detect_rings(frame)
    tracker.update(records)
    target = current["color"] if current["mode"] == "COLOR" else current["slot"]
    return [r for r in records if r["id"] == target]

def main():
    import image
    from ulab import numpy as np
    from media.sensor import Sensor
    from media.display import Display
    from media.media import MediaManager
    camera, link = None, None
    display_ready = media_ready = False
    print("[FLOW_BUILD]",cfg.BUILD_ID)
    try:
        if cfg.QR_CAMERA not in ("ONBOARD","USB"):
            raise ValueError("BAD_QR_CAMERA")
        if not 0 < cfg.PROCESS_SCALE <= 1 or cfg.DETECT_PERIOD_MS < 0 or cfg.QR_SCAN_PERIOD_MS < 0:
            raise ValueError("BAD_FRAME_SETTINGS")
        try:
            import urandom
            session = urandom.getrandbits(16)
        except ImportError:
            session = time.ticks_ms() & 65535
        work = Workflow(session)
        # Initialize display before UART, so bad UART configuration is visible.
        Display.init(Display.ST7701,width=cfg.WIDTH,height=cfg.HEIGHT,to_ide=cfg.IDE_PREVIEW)
        display_ready = True
        link = core.VisionLink()
        camera = core.CameraMux(Sensor)
        MediaManager.init()
        media_ready = True
        tracker = core.StableTracker()
        frame = None
        records = []
        last_detect = last_report = last_gc = time.ticks_ms()
        last_task = time.ticks_add(last_detect,-cfg.TASK_RETRY_MS)
        last_key = None
        frames = detections = 0
        detect_ms = capture_ms = display_ms = 0
        fps = detect_fps = 0.0
        last_error = ""
        idle_key = None
        while True:
            os.exitpoint()
            pending = None
            for seq, kind, args in link.poll():
                if pending is not None and kind not in ("PING","STATUS"):
                    replies = [core.wire_frame(seq,"ERROR","BUSY"),core.wire_frame(seq,"DONE",0,time.ticks_ms())]
                    locate = False
                else:
                    replies, locate = command(work,seq,kind,args,time.ticks_ms())
                for packet in replies:
                    write_packet(link,packet)
                if locate:
                    pending = seq
            now = time.ticks_ms()
            if work.state == "WAIT_ACK" and time.ticks_diff(now,last_task) >= cfg.TASK_RETRY_MS:
                link.send(0,"TASK",work.token,work.raw)
                print("[FLOW_TASK] token=%s task=%s waiting=STM32_ACK" % (work.token,work.raw))
                last_task = now
            key = (work.state,work.step)
            if key != last_key:
                tracker = core.StableTracker()
                records = []
                last_key = key
                last_detect = time.ticks_add(now,-cfg.DETECT_PERIOD_MS)
                print("[FLOW_STATE]",work.context())
            mode = work.mode()
            if mode == "IDLE":
                camera.stop()
                if idle_key != key:
                    frame = image.Image(cfg.WIDTH,cfg.HEIGHT,image.RGB565)
                    frame.draw_string_advanced(8,10,26,cfg.BUILD_ID,color=(0,255,0))
                    frame.draw_string_advanced(8,55,32,work.state,color=(255,255,255))
                    frame.draw_string_advanced(8,110,32,work.raw or "WAIT TASK",color=(255,255,0))
                    frame.draw_string_advanced(8,170,24,"GRAB %d  PLACE %d" % (work.grabs,work.places),color=(255,255,255))
                    if work.state == "WAIT_ACK":
                        frame.draw_string_advanced(8,210,20,"STM32 must acknowledge task",color=(255,255,255))
                    Display.show_image(frame)
                    idle_key = key
                time.sleep_ms(10)
            else:
                idle_key = None
                try:
                    stamp = time.ticks_ms()
                    frame = camera.snapshot(mode)
                    capture_ms = time.ticks_diff(time.ticks_ms(),stamp)
                    codes = []
                    if mode == "QR":
                        if time.ticks_diff(now,last_detect) >= cfg.QR_SCAN_PERIOD_MS:
                            stamp = time.ticks_ms()
                            codes = frame.find_qrcodes()
                            payload = codes[0].payload() if len(codes) == 1 else None
                            if work.observe(payload,core.crc16):
                                last_task = time.ticks_add(time.ticks_ms(),-cfg.TASK_RETRY_MS)
                            detect_ms = time.ticks_diff(time.ticks_ms(),stamp)
                            last_detect = time.ticks_ms()
                            detections += 1
                    elif pending is not None or time.ticks_diff(now,last_detect) >= cfg.DETECT_PERIOD_MS:
                        stamp = time.ticks_ms()
                        records = fresh_records(frame,work,tracker,np,image)
                        detect_ms = time.ticks_diff(time.ticks_ms(),stamp)
                        last_detect = time.ticks_ms()
                        detections += 1
                        last_error = ""
                        if pending is not None:
                            for packet in core.result_frames(pending,mode,records,None,None,0,last_detect):
                                write_packet(link,packet)
                    # Cached boxes are display-only; serial results always use a fresh frame.
                    stamp = time.ticks_ms()
                    if mode != "QR" and time.ticks_diff(stamp,last_detect) <= cfg.MAX_RESULT_AGE_MS:
                        for r in records:
                            color = cfg.DRAW_COLORS.get(r["id"],(0,255,0)) if mode == "COLOR" else (0,255,0)
                            frame.draw_rectangle(r["rect"],color=color,thickness=2)
                            frame.draw_cross(r["cx"],r["cy"],color=color,thickness=2)
                    for code in codes:
                        frame.draw_rectangle(code.rect(),color=(0,255,0),thickness=2)
                    current = work.current()
                    title = ("%s S%d C%d P%d" % (current["phase"],work.step,current["color"],current["slot"])) if current else work.state
                    frame.draw_string_advanced(0,0,22,title,color=(255,255,255))
                    frame.draw_string_advanced(0,26,20,"FPS %.1f DET %.1f %s" % (fps,detect_fps,cfg.BUILD_ID),color=(255,255,0))
                    if work.raw:
                        frame.draw_string_advanced(0,52,24,work.raw,color=(255,255,255))
                        frame.draw_string_advanced(0,80,20,"DONE G%d P%d" % (work.grabs,work.places),color=(0,255,0))
                    if records and mode != "QR" and time.ticks_diff(stamp,last_detect) <= cfg.MAX_RESULT_AGE_MS:
                        r=records[0]
                        frame.draw_string_advanced(0,104,20,"ID %d XY %d,%d valid=%d stable=%d" %
                            (r["id"],r["cx"],r["cy"],r["valid"],r["stable"]),color=(255,255,255))
                    Display.show_image(frame)
                    display_ms = time.ticks_diff(time.ticks_ms(),stamp)
                    frames += 1
                except Exception as exc:
                    if "IDE interrupt" in str(exc):
                        raise
                    tracker = core.StableTracker()
                    records = []
                    if work.state == "SCAN":
                        work.previous,work.streak = None,0
                    reason = str(exc)[:40]
                    if reason != last_error:
                        print("[FLOW_FRAME_ERROR]",mode,reason)
                        last_error = reason
                    if pending is not None:
                        link.send(pending,"ERROR",reason if reason == "NO_SLOT_MAP" else "VISION_FAILED")
                        link.send(pending,"DONE",0,time.ticks_ms())
                    error_frame = image.Image(cfg.WIDTH,cfg.HEIGHT,image.RGB565)
                    error_frame.draw_string_advanced(0,20,24,"%s %s" % (cfg.BUILD_ID,work.state),color=(255,255,255))
                    error_frame.draw_string_advanced(0,80,24,reason,color=(255,80,80))
                    Display.show_image(error_frame)
                    time.sleep_ms(20)
            stamp = time.ticks_ms()
            if time.ticks_diff(stamp,last_report) >= cfg.PRINT_INTERVAL_MS:
                elapsed = max(1,time.ticks_diff(stamp,last_report))
                fps,detect_fps = frames*1000/elapsed,detections*1000/elapsed
                print("[FLOW_PERF] state=%s display_fps=%.1f detect_fps=%.1f capture_ms=%d detect_ms=%d draw_ms=%d" %
                      (work.state,fps,detect_fps,capture_ms,detect_ms,display_ms))
                if work.state == "RUN":
                    age=time.ticks_diff(stamp,last_detect)
                    for r in records if age <= cfg.MAX_RESULT_AGE_MS else ():
                        print("[FLOW_TARGET] id=%d cx=%d cy=%d valid=%d stable=%d age_ms=%d" %
                              (r["id"],r["cx"],r["cy"],r["valid"],r["stable"],age))
                    if not records or age > cfg.MAX_RESULT_AGE_MS:
                        print("[FLOW_NO_TARGET]")
                frames=detections=0
                last_report=stamp
            if time.ticks_diff(stamp,last_gc) >= cfg.GC_INTERVAL_MS:
                gc.collect()
                last_gc=stamp
    except KeyboardInterrupt:
        print("[FLOW_STOP]")
    except Exception as exc:
        sys.print_exception(exc)
        if display_ready:
            try:
                error_frame=image.Image(cfg.WIDTH,cfg.HEIGHT,image.RGB565)
                error_frame.draw_string_advanced(0,20,24,"START ERROR "+cfg.BUILD_ID,color=(255,80,80))
                error_frame.draw_string_advanced(0,75,20,str(exc)[:55],color=(255,255,255))
                Display.show_image(error_frame)
                while True:
                    os.exitpoint()
                    time.sleep_ms(50)
            except (Exception,KeyboardInterrupt):
                pass
    finally:
        for obj,method in ((link,"close"),(camera,"stop")):
            if obj is not None:
                try: getattr(obj,method)()
                except Exception as exc: print("[FLOW_CLEANUP]",exc)
        if display_ready:
            Display.deinit()
        if media_ready:
            MediaManager.deinit()

if __name__ == "__main__":
    main()
