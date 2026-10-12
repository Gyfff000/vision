"""Cross-language tests: Python transmitter -> compiled portable STM32 parser."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"K230_competition"
import sys
sys.path.insert(0,str(ROOT))
import vision_core as gx


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gcc=shutil.which("gcc") or "D:/w64devkit/w64devkit/bin/gcc.exe"
        if not gcc: raise unittest.SkipTest("C99 compiler unavailable")
        cls.temp=tempfile.TemporaryDirectory(prefix="vision-c-",dir=ROOT.parent)
        cls.exe=Path(cls.temp.name)/"vision_client_test.exe"
        subprocess.run([gcc,"-std=c99","-Wall","-Wextra","-Werror","-I",str(ROOT/"stm32"),
                        str(ROOT/"stm32/vision_client.c"),str(Path(__file__).parent/"vision_client_harness.c"),
                        "-o",str(cls.exe)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def run_packet(self,packet,command="COLOR",timeout=False,profile=None):
        path=Path(self.temp.name)/"packet.bin"; path.write_bytes(packet)
        args=[str(self.exe),str(path),command,str(int(timeout))]+([profile] if profile else [])
        output=subprocess.check_output(args,text=True)
        lines=output.splitlines()
        self.assertEqual(lines[0],"TX "+gx.wire_frame(42,command,*([profile] if profile else [])).decode().strip())
        state=next(line for line in lines if line.startswith("STATE ")).split()
        return [int(value) for value in state[1:10]],output

    def test_color_complete_uncalibrated(self):
        record={"id":1,"cx":340,"cy":250,"pixels":800,"valid":True,"stable":True}
        packet=b"".join(gx.result_frames(42,"COLOR",[record],None,None,0,100))
        state,out=self.run_packet(packet)
        self.assertEqual(state[:6],[0,1,0,0,1,0])
        self.assertIn("RECORD BLOCK 1 340 1 0",out)

    def test_qr_and_task_flags(self):
        packet=b"".join(gx.result_frames(42,"QR",[],None,"156+123+516+231",3,100))
        state,out=self.run_packet(packet,"QR")
        self.assertEqual(state[:8],[0,1,0,0,0,1,1,1])
        self.assertIn("QR 156+123+516+231",out)

    def test_missing_record_bad_crc_cannot_complete_valid_transaction(self):
        packet=gx.wire_frame(42,"BLOCK",1,340,250,20,10,800,0,1,1,0,"NA","NA")
        packet=packet.replace(b"BLOCK",b"block")+gx.wire_frame(42,"DONE",1,100)
        state,out=self.run_packet(packet)
        self.assertEqual(state[:5],[0,1,1,0,0])
        self.assertEqual(state[8],1)
        self.assertIn("INCOMPLETE",out)

    def test_stale_sequence_ignored_then_timeout_and_timer_wrap(self):
        packet=gx.wire_frame(41,"DONE",0,100)
        state,out=self.run_packet(packet,timeout=True)
        self.assertEqual(state[:5],[0,0,1,1,0])
        self.assertIn("TIMEOUT",out)

    def test_no_target_fresh_empty_transaction(self):
        packet=b"".join(gx.result_frames(42,"COLOR",[],None,None,0,100))
        state,out=self.run_packet(b"noise$"+b"x"*400+packet)
        self.assertEqual(state[:5],[0,1,0,0,0]); self.assertGreater(state[8],0)

    def test_error_clears_partial_results(self):
        packet=gx.wire_frame(42,"BLOCK",1,340,250,20,10,800,0,1,1,0,"NA","NA")
        packet+=gx.wire_frame(42,"ERROR","VISION_FAILED")+gx.wire_frame(42,"DONE",1,100)
        state,out=self.run_packet(packet)
        self.assertEqual(state[:5],[0,1,1,0,0]); self.assertIn("VISION_FAILED",out)

    def test_calibrated_coordinates(self):
        packet=gx.wire_frame(42,"RING",2,340,250,20,10,0,2,1,1,1,"10.500","-3.250")
        packet+=gx.wire_frame(42,"DONE",1,100)
        state,out=self.run_packet(packet,"RING")
        self.assertEqual(state[:5],[0,1,0,0,1])
        self.assertIn("RECORD RING 2 340 1 1 10.500 -3.250",out)

    def test_profile_request_encoding(self):
        state,out=self.run_packet(gx.wire_frame(42,"NO_TARGET")+gx.wire_frame(42,"DONE",0,100),profile="RAW")
        self.assertEqual(state[:3],[0,1,0])

    def test_missing_empty_status_rejected(self):
        state,out=self.run_packet(gx.wire_frame(42,"DONE",0,100))
        self.assertEqual(state[:3],[0,1,1])


if __name__=="__main__": unittest.main()
