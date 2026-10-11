"""Generate a single-red, small-ROI diagnostic variant from the same application."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=(root/"examples/k230_gx_vision.py").read_text(encoding="utf-8")
source=source.replace("ACTIVE_COLOR_IDS = (1, 2, 3, 4, 5, 6)","ACTIVE_COLOR_IDS = (1,)",1)
source=source.replace("DETECT_ROI = (80, 60, 480, 360)","DETECT_ROI = (160, 100, 320, 280)",1)
output=root/"examples/k230_red_check.py"
output.write_text(source,encoding="utf-8")
print(output)
