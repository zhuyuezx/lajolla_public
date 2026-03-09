"""
Check geometric normal vs shading normal for each shape in the current render.
The shading normal comes from the OBJ vertex normals (exact face normals).
The geometric normal comes from Embree's float32 cross-product.
Differences reveal where the normal AOV is storing imprecise values.
"""
import os, sys
import numpy as np
import OpenEXR, Imath

BUILD = os.path.join(os.path.dirname(__file__), '..', 'build')

def read_ch(path, ch='R'):
    f = OpenEXR.InputFile(path)
    dw = f.header()['dataWindow']
    W = dw.max.x - dw.min.x + 1; H = dw.max.y - dw.min.y + 1
    PT = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.frombuffer(f.channel(ch, PT), dtype=np.float32).reshape(H, W)

n   = np.stack([read_ch(os.path.join(BUILD, 'image_normal.exr'), c)
                for c in ('R','G','B')], axis=-1)
oid = read_ch(os.path.join(BUILD, 'image_objectid.exr'))

# Expected OBJ vertex normals per shape ID
# (from OBJ files; -1 = background)
print("Normal consistency check per shape ID:")
print("(stdev across pixels should be ~0 for flat-shaded faces)")
for uid in sorted(set(oid.ravel().round(0).tolist())):
    mask = np.abs(oid - uid) < 0.5
    if not mask.any():
        continue
    n_face = n[mask]            # N×3 array
    std = n_face.std(axis=0)    # stddev per component
    mean = n_face.mean(axis=0)
    # Check if normal values are NOT snapped to 0 where they should be
    tiny = (np.abs(n_face) < 1e-4) & (np.abs(n_face) > 0)   # near-zero but not zero
    print(f"  ID {int(uid):3d}: pixels={mask.sum():6d}  "
          f"mean=({mean[0]:+.4f},{mean[1]:+.4f},{mean[2]:+.4f})  "
          f"std=({std[0]:.4f},{std[1]:.4f},{std[2]:.4f})  "
          f"near-zero-not-snapped={tiny.sum()}")

# Find pixels where the normal has abnormally large stddev within a neighborhood
# (indicates inconsistency on a flat surface)
print("\nChecking for locally-variable normals (should be ~0 within flat faces):")
# 3x3 neighborhood standard deviation of normal magnitude
from scipy.ndimage import uniform_filter
valid = (read_ch(os.path.join(BUILD, 'image_depth.exr')) >= 0)
nx = n[:,:,0]; ny = n[:,:,1]; nz = n[:,:,2]
# local std = sqrt(E[x^2] - E[x]^2) using uniform filter
def local_std(arr, size=3):
    ex2 = uniform_filter(arr**2, size=size)
    ex  = uniform_filter(arr,    size=size)
    var = np.maximum(ex2 - ex**2, 0)
    return np.sqrt(var)
local_var = local_std(nx)**2 + local_std(ny)**2 + local_std(nz)**2
threshold = 0.001
unstable = (local_var > threshold) & valid
print(f"  Pixels with locally variable normals (std>{threshold:.3f}): "
      f"{unstable.sum()} ({100*unstable.mean():.2f}%)")

# Per-shape
for uid in sorted(set(oid.ravel().round(0).tolist())):
    if uid < 0: continue
    mask = (np.abs(oid - uid) < 0.5) & valid
    if not mask.any(): continue
    local_bad = unstable & mask
    print(f"    shape ID {int(uid):2d}: unstable={local_bad.sum():5d} / {mask.sum():5d} "
          f"({100*local_bad.sum()/max(mask.sum(),1):.2f}%)")
