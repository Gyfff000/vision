"""Reference RGB HSV parameters on the portable K230 pipeline (V1 UART)."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=(root/"examples/k230_gx_vision.py").read_text(encoding="utf-8")
source=source.replace("ACTIVE_COLOR_IDS = (1, 2, 3, 4, 5, 6)","ACTIVE_COLOR_IDS = (1, 4, 3)",1)
source=source.replace("DETECT_ROI = (80, 60, 480, 360)","DETECT_ROI = None",1)
source=source.replace("MIN_PIXELS = 200", "MIN_PIXELS = 125",1)
source=source.replace("(0, 10, 100, 255, 60, 255), (170, 179, 100, 255, 60, 255)",
                      "(0, 10, 100, 255, 100, 255), (170, 179, 100, 255, 100, 255)",1)
source=source.replace("(35, 79, 80, 255, 60, 255)","(35, 85, 100, 255, 100, 255)",1)
source=source.replace("(100, 135, 150, 255, 60, 255)","(100, 130, 100, 255, 100, 255)",1)
output=root/"examples/k230_silver_rgb.py"
output.write_text(source,encoding="utf-8")
print(output)
