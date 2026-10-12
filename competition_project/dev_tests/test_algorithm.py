import sys
from pathlib import Path
import unittest
import numpy as np
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"K230_competition"))
import vision_core as gx
class Blob:
    def __init__(self, stat, center): self.stat, self.center = stat, center
    def rect(self): return tuple(int(v) for v in self.stat[:4])
    def pixels(self): return int(self.stat[4])
    def cx(self): return self.center[0]
    def cy(self): return self.center[1]


class DesktopImage:
    def __init__(self, data): self.data = data
    def width(self): return self.data.shape[1]
    def height(self): return self.data.shape[0]
    def copy(self, x_scale=1, y_scale=1, roi=None):
        data=self.data
        if roi:
            x,y,w,h=roi; data=data[y:y+h,x:x+w]
        return DesktopImage(cv2.resize(data,None,fx=x_scale,fy=y_scale))
    def to_rgb888(self): return self
    def to_numpy_ref(self): return self.data
    def open(self, radius): self.data = cv2.morphologyEx(self.data,cv2.MORPH_OPEN,np.ones((2*radius+1,)*2,np.uint8))
    def close(self, radius): self.data = cv2.morphologyEx(self.data,cv2.MORPH_CLOSE,np.ones((2*radius+1,)*2,np.uint8))
    def find_blobs(self, thresholds, **kw):
        count, labels, stats, centers = cv2.connectedComponentsWithStats(self.data)
        return [Blob(stats[i],centers[i]) for i in range(1,count)
                if stats[i,4]>=kw["pixels_threshold"] and stats[i,2]*stats[i,3]>=kw["area_threshold"]]


class ImageModule:
    GRAYSCALE=0
    ALLOC_REF=0
    @staticmethod
    def Image(w,h,fmt,alloc=None,data=None): return DesktopImage(data.copy())


class AlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.old_roi=gx.DETECT_ROI
        self.old_scale=gx.PROCESS_SCALE
        gx.PROCESS_SCALE=0.5
        gx.DETECT_ROI=(0,0,640,480)

    def tearDown(self):
        gx.PLANE_H, gx.PLANE_ROI = None, None
        gx.DETECT_ROI=self.old_roi
        gx.PROCESS_SCALE=self.old_scale

    def test_hsv_matches_opencv_float(self):
        rgb=np.random.default_rng(7).integers(0,256,(100,160,3),dtype=np.uint8)
        h,s,v=gx.rgb_to_hsv(rgb,np)
        expected=cv2.cvtColor(rgb.astype(np.float32)/255,cv2.COLOR_RGB2HSV)
        hue_error=np.abs(h-expected[:,:,0]/2)
        hue_error=np.minimum(hue_error,180-hue_error)
        self.assertLess(hue_error.max(),.001)
        self.assertLess(np.max(np.abs(s-expected[:,:,1]*255)),.01)
        self.assertLess(np.max(np.abs(v-expected[:,:,2]*255)),.01)

    def test_six_colors_real_pipeline_and_empty(self):
        rgb=np.full((480,640,3),255,np.uint8)
        for index,color in enumerate(((240,20,20),(240,230,20),(20,20,220),(20,210,20),(20,20,20),(120,190,220))):
            rgb[180:240,30+index*100:90+index*100]=color
        records=gx.detect_colors(DesktopImage(rgb),np,ImageModule)
        self.assertEqual([r["id"] for r in records if r["valid"]],list(range(1,7)))
        self.assertLess(abs(records[0]["cx"]-60),3)
        self.assertEqual(gx.detect_colors(DesktopImage(np.full_like(rgb,255)),np,ImageModule),[])

    def test_red_wrap_and_white_rejection(self):
        hsv=np.array([[[179,220,200],[1,220,200],[90,220,200],[0,0,255]]],np.uint8)
        rgb=cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB)
        mask=gx.color_mask(*gx.rgb_to_hsv(rgb,np),gx.HSV_RANGES[1],np)
        self.assertEqual(mask.tolist(),[[255,255,0,0]])

    def test_largest_component_and_noise(self):
        rgb=np.full((480,640,3),255,np.uint8)
        rgb[100:180,100:180]=(240,20,20)
        rgb[300:340,400:440]=(240,20,20)
        rgb[20,20]=(240,20,20)
        record=gx.detect_colors(DesktopImage(rgb),np,ImageModule)[0]
        self.assertLess(abs(record["cx"]-140),3)

    def test_roi_origin_and_clipped_background_rejection(self):
        gx.DETECT_ROI=(100,80,400,300)
        rgb=np.full((480,640,3),255,np.uint8)
        rgb[150:230,250:330]=(240,20,20)
        rgb[80:250,100:150]=(10,10,10)  # background touching ROI edge
        records=gx.detect_colors(DesktopImage(rgb),np,ImageModule)
        self.assertEqual([r["id"] for r in records],[1])
        self.assertLess(abs(records[0]["cx"]-290),3)
        self.assertLess(abs(records[0]["cy"]-190),3)

    def test_temporal_stability_resets_on_loss_motion_invalid(self):
        t=gx.StableTracker()
        def update(x=100,valid=True):
            r={"id":1,"cx":x,"cy":100,"valid":valid}; t.update([r]); return r["stable"]
        self.assertFalse(update()); self.assertFalse(update()); self.assertFalse(update()); self.assertTrue(update())
        self.assertFalse(update(150)); t.update([]); self.assertFalse(update(150))
        update(); update(); update(); self.assertFalse(update(valid=False)); self.assertFalse(update())


    def test_fast_scale_preserves_target_ids_and_full_coordinates(self):
        gx.PROCESS_SCALE=0.25
        rgb=np.full((480,640,3),255,np.uint8)
        for index,color in enumerate(((240,20,20),(20,20,20),(120,190,220))):
            rgb[180:260,100+index*160:180+index*160]=color
        records=gx.detect_colors(DesktopImage(rgb),np,ImageModule,(1,5,6))
        self.assertEqual([r['id'] for r in records],[1,5,6])
        for index,r in enumerate(records):self.assertLess(abs(r['cx']-(140+index*160)),5)
