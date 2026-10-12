# Install first, then run this file in CanMV IDE. Does not start motors or UART.
import sys
with open("/sdcard/main.py","r") as entry:
    for line in entry:
        if line.startswith("APP_DIR = "):
            sys.path.insert(0,line.split("=",1)[1].split("#",1)[0].strip().strip("\"'"))
            break
import image
from ulab import numpy as np
import vision_core as core
from workflow import Workflow
frame=image.Image(640,480,image.RGB565)
frame.draw_rectangle((0,0,640,480),color=(255,255,255),fill=True)
colors=((240,20,20),(240,230,20),(20,20,220),(20,210,20),(20,20,20),(120,190,220))
for i,color in enumerate(colors):
    frame.draw_rectangle((30+i*100,180,60,60),color=color,fill=True)
core.DETECT_ROI=None
records=core.detect_colors(frame,np,image)
assert sorted(r["id"] for r in records if r["valid"])==[1,2,3,4,5,6],records
assert core.crc16(b"123456789")==0x29B1
work=Workflow(123)
for _ in range(3):work.observe("156+123+516+231",core.crc16)
assert work.state=="WAIT_ACK"
assert [s["slot"] for s in work.plan[-3:]]==[2,1,3]
work.acknowledge(work.token)
for step in range(24):work.confirm_step(work.token,step)
assert work.state=="RETURN_HOME"
work.complete_home(work.token)
assert work.state=="COMPLETE" and work.grabs==12 and work.places==12
print("[FLOW_SELF_TEST] six-color HSV + CRC + task handoff + 24 steps PASS")
