"""Use a 3.3V USB-TTL adapter on external UART, not CanMV IDE's USB COM."""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision_core import FrameParser, wire_frame, crc16
from workflow import parse_task

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port",help="USB-TTL COM port, e.g. COM6")
    parser.add_argument("--demo",action="store_true",help="Bench only: ACK task then request locations; never confirms robot actions")
    args=parser.parse_args()
    try:import serial
    except ImportError:parser.error("Install pyserial on PC: python -m pip install pyserial")
    decoder=FrameParser(); seq=1; running=False; pending=False; last=0; task_token=None
    with serial.Serial(args.port,115200,timeout=.05) as uart:
        try:
            while True:
                for number,kind,fields in decoder.feed(uart.read(512)):
                    print(number,kind,fields)
                    if kind=="TASK" and number==0 and len(fields)==2:
                        try:
                            token=int(fields[0]);parse_task(fields[1])
                            if token&65535!=crc16(fields[1].encode("ascii")):raise ValueError()
                        except ValueError:
                            print("BAD TASK");continue
                        task_token=token
                    if number==seq and kind=="ACK":running=True
                    if number==seq and kind=="DONE":pending=False
                if args.demo and task_token is not None and not pending and time.monotonic()-last>=.5:
                    seq=(seq+1)&65535
                    uart.write(wire_frame(seq,"LOCATE") if running else wire_frame(seq,"TASK_ACK",task_token))
                    pending=True;last=time.monotonic()
                if pending and time.monotonic()-last>3:
                    pending=False;last=time.monotonic()
        except KeyboardInterrupt:
            if args.demo:uart.write(wire_frame((seq+1)&65535,"STOP"))

if __name__=="__main__":main()
