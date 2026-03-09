"""
Sample pixel values from box, white-wall, and colored-wall regions,
printing objectID, RGB, and material info to diagnose the color issue.
"""
import os, sys
import numpy as np
import OpenEXR, Imath

BUILD = os.path.join(os.path.dirname(__file__), '..', 'build')

def read_ch(path, ch='R'):
    f = OpenEXR.InputFile(path)
    dw = f.header()['dataWindow']
    W = dw.max.x - dw.min.x + 1
    H = dw.max.y - dw.min.y + 1
    PT = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.frombuffer(f.channel(ch, PT), dtype=np.float32).reshape(H, W)

def read_rgb(path):
    return np.stack([read_ch(path, c) for c in ('R','G','B')], axis=-1)

color  = read_rgb(os.path.join(BUILD, 'image.exr'))
oid    = read_ch(os.path.join(BUILD, 'image_objectid.exr'))
normal = read_rgb(os.path.join(BUILD, 'image_normal.exr'))
h, w   = color.shape[:2]

print(f"Image: {w}x{h}")
print()

# Sample a grid of pixels and print their objectID + RGB
# so we can identify which region belongs to which shape
print("ObjectID distribution:")
for uid in sorted(set(oid.ravel().round(0).tolist())):
    mask = (np.abs(oid - uid) < 0.5)
    if mask.sum() == 0:
        continue
    rgb = color[mask]
    print(f"  ID {int(uid):3d}:  pixels={mask.sum():6d}  "
          f"avg_rgb=({rgb[:,0].mean():.3f}, {rgb[:,1].mean():.3f}, {rgb[:,2].mean():.3f})  "
          f"max_rgb=({rgb[:,0].max():.3f}, {rgb[:,1].max():.3f}, {rgb[:,2].max():.3f})")

print()
# Sample the center column to trace from top to bottom
cx = w // 2
print(f"Center column (x={cx}) — objectID and RGB per 32 rows:")
for row in range(0, h, 32):
    r, g, b = color[row, cx]
    o = oid[row, cx]
    nx, ny, nz = normal[row, cx]
    print(f"  row {row:3d}: id={int(o):2d}  rgb=({r:.3f},{g:.3f},{b:.3f})  n=({nx:.2f},{ny:.2f},{nz:.2f})")
