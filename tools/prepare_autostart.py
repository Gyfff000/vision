"""Build an IDE-run installer embedding the tested K230 RGB application."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
payload=(root/"examples/k230_silver_rgb.py").read_text(encoding="utf-8")
launcher='''# K230 vision autostart. Original startup is in /sdcard/vision_backup/.
import sys
import time
time.sleep_ms(3000)
if "/sdcard" not in sys.path:
    sys.path.insert(0, "/sdcard")
import k230_silver_rgb
k230_silver_rgb.main()
'''
installer='''# Run this file ONCE in CanMV IDE, then disconnect and power-cycle.
# Saves files to SD card; never burns/replaces firmware. Preserves prior files.
import os

PAYLOAD = %s
LAUNCHER = %s

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
            backup = root + "/vision_backup/" + name + ".%%03d.bak" %% number
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
    safe_replace(root, "k230_silver_rgb.py", PAYLOAD)
    safe_replace(root, "main.py", LAUNCHER)
    if hasattr(os, "sync"):
        os.sync()
    print("[INSTALL_OK]", root + "/k230_silver_rgb.py")
    print("[INSTALL_OK]", root + "/main.py")
    print("[INSTALL_NEXT] Disconnect IDE, power off, reconnect power; wait for GX_START.")

if __name__ == "__main__":
    if "k230" not in str(os.uname()).lower():
        raise RuntimeError("Run installer on K230 using CanMV IDE, not PC Python")
    install()
''' % (repr(payload),repr(launcher))
output=root/"examples/k230_install_autostart.py"
output.write_text(installer,encoding="utf-8")
print(output)
