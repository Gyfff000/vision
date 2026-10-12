# Fixed startup entry. Install using install.py in CanMV IDE, not MTP editing.
import sys
import time
APP_DIR = "/sdcard/vision_current"  # install.py replaces with a verified release directory.
sys.path.insert(0, APP_DIR)
time.sleep_ms(3000)
print("[FLOW_SOURCE]",APP_DIR)
for module in ("vision_app", "vision_core", "workflow", "config"):
    if module in sys.modules:
        del sys.modules[module]
import vision_app
vision_app.main()
