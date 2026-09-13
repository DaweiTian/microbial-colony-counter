import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.algorithm import process_image

r = process_image(None)
assert r["error"], r
r = process_image(np.zeros((0, 0, 3), dtype=np.uint8))
assert r["error"], r
img = np.zeros((50, 50, 3), dtype=np.uint8)
img[10:20, 10:20] = 255
r = process_image(img, segment_mode="labels", seed_kernel=100001)
assert r["error"] is None or isinstance(r["count"], int)
r = process_image(img, manual_roi=(-10, -10, 5, 5))
assert r["error"] is None
print("edge ok", r["count"], r.get("error"))
