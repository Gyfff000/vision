"""Desktop algorithm/packet checks. Native K230 checks use MODE=SELF_TEST."""
import importlib.util
import unittest
from pathlib import Path
import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("gx", Path(__file__).resolve().parents[1]/"examples/k230_gx_vision.py")
gx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gx)


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
        gx.DETECT_ROI=(0,0,640,480)

    def tearDown(self):
        gx.PLANE_H, gx.PLANE_ROI = None, None
        gx.DETECT_ROI=self.old_roi

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

    def test_all_aruco_dictionary_ids_and_rotations(self):
        dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        for marker_id in range(50):
            image=cv2.aruco.generateImageMarker(dictionary,marker_id,60)
            cells=(image[5::10,5::10]>127).astype(int)
            for rot in range(4):
                decoded=gx.decode_aruco_cells(np.rot90(cells,rot).ravel().tolist())
                self.assertIsNotNone(decoded,(marker_id,rot))
                self.assertEqual(decoded[0],marker_id)
        cells[0,0]=1
        self.assertIsNone(gx.decode_aruco_cells(cells.ravel().tolist()))

    def test_aruco_one_bit_correction(self):
        data=cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),0,60)
        cells=(data[5::10,5::10]>127).astype(int)
        cells[2,3]^=1
        self.assertEqual(gx.decode_aruco_cells(cells.ravel().tolist())[0],0)

    def test_projective_sampling_matches_opencv(self):
        corners=np.float32([[80,30],[280,70],[250,260],[30,200]])
        H=cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]),corners)
        for u,v in ((.1,.1),(.5,.5),(.9,.8)):
            expected=cv2.perspectiveTransform(np.float32([[[u,v]]]),H)[0,0]
            self.assertTrue(np.allclose(gx.quad_point(corners,u,v),expected,atol=.001))

    def test_qr_task_semantics(self):
        self.assertTrue(gx.valid_task("156+123+516+231"))
        for text in ("Good","156+111+516+231","116+123+611+231","156+123+234+231","156+123+516+23"):
            self.assertFalse(gx.valid_task(text))

    def test_plane_requires_calibration_and_roi(self):
        self.assertIsNone(gx.plane_point(320,240))
        gx.PLANE_H=(.5,0,-160,0,.5,-120,0,0,1); gx.PLANE_ROI=(100,100,400,300)
        self.assertEqual(gx.plane_point(340,260),(10,10))
        self.assertIsNone(gx.plane_point(20,20))

    def test_crc_fragment_noise_bad_crc_resync(self):
        self.assertEqual(gx.crc16(b"123456789"),0x29B1)
        parser=gx.FrameParser(); packet=gx.wire_frame(42,"COLOR")
        self.assertEqual(parser.feed(b"noise"+packet[:7]),[])
        self.assertEqual(parser.feed(packet[7:]),[(42,"COLOR",[])])
        self.assertEqual(parser.feed(packet.replace(b"COLOR",b"COLOr")),[])
        self.assertEqual(parser.feed(b"$"+b"x"*400+packet),[(42,"COLOR",[])])
        self.assertGreater(parser.errors,0)

    def test_result_transaction_no_default_and_na(self):
        parser=gx.FrameParser()
        decoded=parser.feed(b"".join(gx.result_frames(2,"COLOR",[],None,None,0,100)))
        self.assertEqual(decoded,[(2,"NO_TARGET",[]),(2,"DONE",["0","100"])])
        record={"id":1,"cx":330,"cy":250,"pixels":600,"pos":-1,"valid":True,"stable":False}
        decoded=parser.feed(b"".join(gx.result_frames(3,"COLOR",[record],None,None,0,101)))
        self.assertEqual(decoded[0][2][-3:],["0","NA","NA"])
        self.assertEqual(decoded[-1],(3,"DONE",["1","101"]))

    def test_qr_wire_hex_utf8_and_good_not_task(self):
        packets=gx.FrameParser().feed(b"".join(gx.result_frames(4,"QR",[],None,"Good",3,100)))
        self.assertEqual(packets[0],(4,"QR",["0","1","476F6F64"]))
        self.assertEqual(gx.hex_payload("中"),"E4B8AD")
        self.assertIsNone(gx.hex_payload("x"*65))


if __name__ == "__main__": unittest.main()
