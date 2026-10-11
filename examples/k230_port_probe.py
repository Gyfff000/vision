# Read-only capability probe. No UART, motion control or persistent board writes.
import os
import sys
print("[PROBE_BOARD]", os.uname())
for name in ("image", "ulab.numpy", "cv2", "cv_lite", "aidemo"):
    try:
        module = __import__(name, None, None, ["*"])
        print("[PROBE_MODULE]", name, "OK")
        if name == "image":
            print("[PROBE_IMAGE]", [x for x in dir(module) if "aruco" in x.lower() or "rgb" in x.lower()])
        if name == "cv_lite":
            print("[PROBE_CV_LITE]", dir(module))
    except Exception as exc:
        print("[PROBE_MODULE]", name, "MISSING", str(exc))
try:
    import image
    from ulab import numpy as np
    img = image.Image(16, 16, image.RGB565)
    print("[PROBE_METHODS]", [x for x in dir(img) if x in (
        "to_rgb888", "to_numpy_ref", "copy", "erode", "dilate", "open", "close",
        "find_blobs", "find_apriltags", "find_aruco", "find_aruco_markers")])
    rgb = img.to_rgb888()
    array = rgb.to_numpy_ref()
    print("[PROBE_ARRAY]", array.shape, array.dtype)
    small = img.copy(x_scale=0.5, y_scale=0.5)
    print("[PROBE_SCALE]", small.width(), small.height())
    print("[PROBE_NUMPY]", [x for x in ("maximum", "minimum", "where", "zeros", "uint8", "float") if hasattr(np, x)])
    float_data = np.array(array[:, :, 0], dtype=np.float)
    test = np.maximum(float_data, 1)
    print("[PROBE_NUMPY_OP]", test.shape, np.array(np.where(test > 0, 255, 0), dtype=np.uint8).shape)
    print("[PROBE_HSV_OP]", (test > 0) & (test < 256))
    mask_np = np.array(np.where(test > 0, 255, 0), dtype=np.uint8)
    mask = image.Image(16, 16, image.GRAYSCALE, alloc=image.ALLOC_REF, data=mask_np)
    mask.open(1)
    mask.close(1)
    print("[PROBE_MASK]", mask.find_blobs([(128, 255)], pixels_threshold=10, area_threshold=10))
    print("[PROBE_RECTS]", hasattr(img, "find_rects"))
except Exception as exc:
    sys.print_exception(exc)
print("[PROBE_DONE]")
