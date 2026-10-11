"""PC UART request tool. K230 IDE USB COM is not the external UART connection."""
import argparse
import importlib.util
import time
from pathlib import Path

spec=importlib.util.spec_from_file_location("gx",Path(__file__).resolve().parents[1]/"examples/k230_gx_vision.py")
gx=importlib.util.module_from_spec(spec); spec.loader.exec_module(gx)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port",help="USB-to-3.3V-TTL adapter COM port, not IDE COM")
    parser.add_argument("command",choices=("PING","COLOR","RING","ARUCO","QR","STOP"))
    parser.add_argument("--baud",type=int,default=115200)
    parser.add_argument("--seq",type=int,default=1)
    parser.add_argument("--profile",choices=("GRASP","PLACE","STACK"))
    parser.add_argument("--timeout",type=float,default=5)
    args=parser.parse_args()
    try: import serial
    except ImportError: parser.error("Install PC dependency: python -m pip install pyserial")
    decoder=gx.FrameParser()
    with serial.Serial(args.port,args.baud,timeout=.05) as uart:
        uart.reset_input_buffer()
        uart.write(gx.wire_frame(args.seq,args.command,*([args.profile] if args.profile else [])))
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            for seq,kind,fields in decoder.feed(uart.read(256)):
                if seq!=args.seq: continue
                if kind=="QR" and len(fields)==3:
                    print(kind,fields[:2],bytes.fromhex(fields[2]).decode("utf-8",errors="replace"))
                else: print(kind,fields)
                if kind=="DONE": return
        raise TimeoutError("K230 response timed out; discard this transaction")

if __name__=="__main__": main()
