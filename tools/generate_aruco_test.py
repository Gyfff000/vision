"""Generate ArUco ID 0 bench target. Do not add markers to competition field."""
import argparse
from pathlib import Path
import cv2
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output",type=Path,default=Path("assets/aruco/dict-4x4-50-id0.png"))
args=parser.parse_args()
dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
marker=cv2.aruco.generateImageMarker(dictionary,0,480)
canvas=np.full((640,640),255,np.uint8); canvas[80:560,80:560]=marker
args.output.parent.mkdir(parents=True,exist_ok=True)
if not cv2.imwrite(str(args.output),canvas): raise OSError("Cannot save bench target")
print(args.output.resolve())
