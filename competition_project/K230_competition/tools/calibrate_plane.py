"""Fit one image plane from measured pixel/mm pairs; never invent camera scales."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np

def fit(samples):
    pixels=np.array([s["pixel"] for s in samples],dtype=np.float64)
    world=np.array([s["mm"] for s in samples],dtype=np.float64)
    if len(pixels)<4 or pixels.shape!=world.shape or pixels.shape[1]!=2:
        raise ValueError("Need at least four pixel/mm pairs")
    if not np.isfinite(pixels).all() or not np.isfinite(world).all():
        raise ValueError("Coordinates must be finite")
    H,status=cv2.findHomography(pixels,world,method=0)
    if H is None or np.linalg.matrix_rank(H)<3:
        raise ValueError("Degenerate calibration geometry")
    predicted=cv2.perspectiveTransform(pixels.reshape(-1,1,2),H).reshape(-1,2)
    errors=np.linalg.norm(predicted-world,axis=1)
    return H/H[2,2],errors

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile",required=True,choices=("RAW","PROCESS","STORE","STACK"))
    parser.add_argument("samples",type=Path,help='JSON list: [{"pixel":[x,y],"mm":[X,Y]}, ...]')
    args=parser.parse_args()
    H,errors=fit(json.loads(args.samples.read_text(encoding="utf-8")))
    print("H =",tuple(float(v) for v in H.ravel()))
    print("Set config.CALIBRATIONS[%r] = (H, measured_ROI) and rebuild install.py." % args.profile)
    print("Training reprojection errors (mm):",errors.tolist())
    print("Set PLANE_ROI inside sampled area. Validate separate held-out points at the same height.")

if __name__=="__main__": main()
