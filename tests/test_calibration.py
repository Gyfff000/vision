import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location("calibrate",Path(__file__).resolve().parents[1]/"tools/calibrate_plane.py")
calibrate=importlib.util.module_from_spec(spec); spec.loader.exec_module(calibrate)

class CalibrationTests(unittest.TestCase):
    def test_recovers_known_transform(self):
        pixels=[(10,10),(400,10),(400,400),(10,400),(150,200),(300,200)]
        samples=[{"pixel":[x,y],"mm":[x*.5-100,y*.7-120]} for x,y in pixels]
        H,errors=calibrate.fit(samples)
        self.assertTrue(np.allclose(H,[[.5,0,-100],[0,.7,-120],[0,0,1]],atol=1e-5))
        self.assertLess(errors.max(),1e-5)

    def test_collinear_geometry_rejected(self):
        samples=[{"pixel":[x,x],"mm":[x,x]} for x in range(4)]
        with self.assertRaises(ValueError): calibrate.fit(samples)

    def test_non_finite_measurements_rejected(self):
        samples=[{"pixel":[x,float("nan")],"mm":[x,x]} for x in range(4)]
        with self.assertRaises(ValueError): calibrate.fit(samples)

if __name__=="__main__": unittest.main()
