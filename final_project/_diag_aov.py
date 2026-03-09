"""Diagnose AOV buffer contents and simulate direct-neighbor edge detection."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
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

d   = read_ch(os.path.join(BUILD, 'image_depth.exr'))
n   = read_rgb(os.path.join(BUILD, 'image_normal.exr'))
oid = read_ch(os.path.join(BUILD, 'image_objectid.exr'))

valid = d >= 0
print(f'Image size:    {d.shape[1]}x{d.shape[0]}')
print(f'Valid pixels:  {valid.sum()} / {d.size} = {100*valid.mean():.1f}%')
print(f'Depth range:   {d[valid].min():.1f} .. {d[valid].max():.1f}')
print(f'Normal range:  {n[valid].min():.3f} .. {n[valid].max():.3f}')
print(f'ObjectID vals: {sorted(set(oid.ravel().round(0).tolist()))}')

# Normalise depth
d_norm = np.where(valid, d, 0.0)
d_norm /= (d_norm.max() + 1e-10)

depth_thresh  = 0.05
normal_thresh = 0.5

edge = np.zeros(d.shape, dtype=bool)

for dy, dx in ((0, 1), (1, 0)):
    h, w = d.shape
    hy = h - dy
    wx = w - dx
    r0 = (slice(None, hy or None), slice(None, wx or None))
    r1 = (slice(dy or None, None), slice(dx or None, None))

    s0 = valid[r0]; s1 = valid[r1]
    both = s0 & s1
    sil  = s0 ^ s1

    dd  = np.abs(d_norm[r0] - d_norm[r1])
    nd  = np.sqrt(np.sum((n[r0] - n[r1])**2, axis=-1))
    idc = np.abs(oid[r0] - oid[r1]) > 0.5

    interior = both & ((dd > depth_thresh) | (nd > normal_thresh) | idc)
    is_edge  = interior | sil

    edge[r0] |= is_edge
    edge[r1] |= is_edge

    label = 'horizontal' if dx==1 else 'vertical'
    print(f'  {label}  interior={interior.sum()}'
          f'  sil={sil.sum()}'
          f'  (dd>{depth_thresh}:{(both&(dd>depth_thresh)).sum()}'
          f'  nd>{normal_thresh}:{(both&(nd>normal_thresh)).sum()}'
          f'  id:{(both&idc).sum()})')

edge &= valid
print(f'Total edge pixels after valid-mask: {edge.sum()} ({100*edge.mean():.2f}%)')

# Print sample row to show normal change at interior corners
row = d.shape[0] // 2
print(f'\nRow {row} normal-Y: {n[row, 100:420:20, 1].round(2)}')
print(f'Row {row} objectid: {oid[row, 100:420:20].round(0).astype(int)}')
