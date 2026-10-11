"""Generate the same single-file application in SELF_TEST mode (no camera/UART)."""
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output",type=Path,default=Path("examples/k230_gx_self_test.py"))
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]/"examples/k230_gx_vision.py"
args.output.write_text(source.read_text(encoding="utf-8").replace('MODE = "COLOR"','MODE = "SELF_TEST"',1),encoding="utf-8")
print(args.output.resolve())
