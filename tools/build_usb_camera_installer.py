"""Embed the standalone USB preview in a backup-preserving CanMV installer."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "examples/k230_usb_camera_install.py"
subprocess.run([sys.executable, str(ROOT / "tools/prepare_autostart.py"),
                "--source", str(ROOT / "examples/k230_usb_camera_test.py"),
                "--output", str(output)], check=True)
text = output.read_text(encoding="utf-8")
text = text.replace("k230_silver_rgb", "usb_camera_preview")
text = text.replace("wait for GX_START", "wait for USB_TEST")
text = text.replace("K230 vision autostart", "K230 USB camera preview autostart")
compile(text, str(output), "exec")
output.write_text(text, encoding="utf-8")
print("USB preview installer:", output)
