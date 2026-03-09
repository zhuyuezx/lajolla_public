#!/usr/bin/env python3
"""Convert EXR render outputs to PNG for the checkpoint report."""
import sys, os
import numpy as np

# Use OpenEXR if available; otherwise imageio v3
try:
    import OpenEXR, Imath
    def _read_exr(path):
        f = OpenEXR.InputFile(path)
        dw = f.header()['dataWindow']
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        FT = Imath.PixelType(Imath.PixelType.FLOAT)
        r, g, b = [np.frombuffer(f.channel(c, FT), dtype=np.float32).reshape(h, w)
                   for c in ('R', 'G', 'B')]
        return np.stack([r, g, b], axis=-1)
except ImportError:
    import imageio.v3 as iio
    def _read_exr(path):
        return np.array(iio.imread(path)).astype(np.float32)

import imageio

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out  = os.path.join(root, 'final_project')

pairs = [
    ('image.exr',          'render_color.png'),
    ('image_outlined.exr', 'render_outlined.png'),
    ('image_depth.exr',    'render_depth.png'),
    ('image_normal.exr',   'render_normal.png'),
    ('image_objectid.exr', 'render_objectid.png'),
]

for src, dst in pairs:
    p = os.path.join(root, src)
    if not os.path.exists(p):
        print(f'missing: {src}')
        continue
    img = _read_exr(p)
    if 'depth' in dst:
        valid = img[:, :, 0] > 0
        if valid.any():
            mn = img[:, :, 0][valid].min()
            mx = img[:, :, 0][valid].max()
            img = np.clip((img - mn) / (mx - mn + 1e-9), 0, 1)
    elif 'objectid' in dst:
        mx = img[:, :, 0].max() + 1e-9
        img = img / mx
    elif 'normal' in dst:
        img = img * 0.5 + 0.5  # remap [-1,1] -> [0,1] for display
    img = np.clip(img, 0, 1) ** (1.0 / 2.2)
    imageio.imwrite(os.path.join(out, dst), (img * 255 + 0.5).astype(np.uint8))
    print(f'wrote {dst}')
