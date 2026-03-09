#!/usr/bin/env python3
"""
sobel_post.py  –  Sobel edge detection post-processing for NPR renders
=======================================================================
Reads the four EXR outputs produced by the NPR integrator:
  <stem>.exr           –  cel-shaded colour
  <stem>_depth.exr     –  ray-hit distance (-1 on miss)
  <stem>_normal.exr    –  flat geometric normals (XYZ in [-1,1])
  <stem>_objectid.exr  –  integer shape_id stored per channel

Runs a Sobel edge filter over each AOV.  Wherever a sharp discontinuity
is detected the colour pixel is overwritten with a solid outline colour
(default: black, set OUTLINE_COLOR below).

Usage:
    python sobel_post.py image.exr [--outline 0,0,0] [--depth_thresh 50]
                                   [--normal_thresh 0.3] [--id_thresh 0.5]
                                   [--outline_width 1] [-o output.exr]

Dependencies:
    numpy, OpenEXR, Imath   (pip install openexr)
    Alternatively: pip install imageio imageio-freeimage  (for FP EXR I/O)
"""

import argparse
import colorsys
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------
# EXR I/O helpers
# ---------------------------------------------------------------------------

def _try_import_openexr():
    try:
        import OpenEXR, Imath  # noqa: F401
        return True
    except ImportError:
        return False

def read_exr_openexr(path):
    import OpenEXR, Imath
    f = OpenEXR.InputFile(path)
    dw = f.header()['dataWindow']
    w = dw.max.x - dw.min.x + 1
    h = dw.max.y - dw.min.y + 1
    FLOAT = Imath.PixelType(Imath.PixelType.FLOAT)
    channels = list(f.header()['channels'].keys())
    # grab RGB or first 3 channels
    rgb_ch = [c for c in ('R','G','B') if c in channels]
    if len(rgb_ch) < 3:
        rgb_ch = channels[:3]
    r, g, b = [np.frombuffer(f.channel(c, FLOAT), dtype=np.float32).reshape(h, w)
                for c in rgb_ch]
    return np.stack([r, g, b], axis=-1)

def write_exr_openexr(path, img):
    import OpenEXR, Imath
    h, w, _ = img.shape
    header = OpenEXR.Header(w, h)
    header['channels'] = {
        'R': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)),
        'G': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)),
        'B': Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)),
    }
    f = OpenEXR.OutputFile(path, header)
    f.writePixels({
        'R': img[:,:,0].astype(np.float32).tobytes(),
        'G': img[:,:,1].astype(np.float32).tobytes(),
        'B': img[:,:,2].astype(np.float32).tobytes(),
    })
    f.close()

def read_exr_imageio(path):
    import imageio
    return np.array(imageio.imread(path, format='EXR-FI')).astype(np.float32)

def write_exr_imageio(path, img):
    import imageio
    imageio.imwrite(path, img.astype(np.float32), format='EXR-FI')

if _try_import_openexr():
    read_exr  = read_exr_openexr
    write_exr = write_exr_openexr
else:
    print("[sobel_post] OpenEXR not found, falling back to imageio.", file=sys.stderr)
    read_exr  = read_exr_imageio
    write_exr = write_exr_imageio

# ---------------------------------------------------------------------------
# Sobel filter helpers
# ---------------------------------------------------------------------------

SOBEL_X = np.array([[-1, 0, 1],
                     [-2, 0, 2],
                     [-1, 0, 1]], dtype=np.float32)

SOBEL_Y = np.array([[-1,-2,-1],
                     [ 0, 0, 0],
                     [ 1, 2, 1]], dtype=np.float32)

def sobel_magnitude(channel_2d):
    """Compute Sobel gradient magnitude for a single-channel 2D array."""
    from scipy.ndimage import convolve
    gx = convolve(channel_2d, SOBEL_X, mode='reflect')
    gy = convolve(channel_2d, SOBEL_Y, mode='reflect')
    return np.sqrt(gx**2 + gy**2)

def sobel_magnitude_manual(channel_2d):
    """
    Pure-numpy Sobel (no scipy).  Slightly slower but no extra dependency.
    """
    h, w = channel_2d.shape
    img = np.pad(channel_2d, 1, mode='reflect')

    gx  = (-img[0:h, 0:w] + img[0:h, 2:w+2]
           - 2*img[1:h+1, 0:w] + 2*img[1:h+1, 2:w+2]
           -   img[2:h+2, 0:w] +   img[2:h+2, 2:w+2])

    gy  = (-img[0:h, 0:w] - 2*img[0:h, 1:w+1] - img[0:h, 2:w+2]
           + img[2:h+2, 0:w] + 2*img[2:h+2, 1:w+1] + img[2:h+2, 2:w+2])

    return np.sqrt(gx**2 + gy**2)

try:
    from scipy.ndimage import convolve as _scipy_convolve  # noqa: F401
    _sobel = sobel_magnitude
except ImportError:
    _sobel = sobel_magnitude_manual

def edge_mask(aov, threshold, dilate=0):
    """
    Return a boolean H×W mask that is True where an edge exceeds `threshold`.
    `aov` shape: H×W×3.  We take the max gradient magnitude across channels.
    """
    mag = np.max(np.stack([_sobel(aov[:,:,c]) for c in range(3)], axis=-1), axis=-1)
    mask = mag > threshold
    if dilate > 0:
        # simple dilation: OR with its neighbourhood
        pad = np.pad(mask.astype(np.uint8), dilate, mode='constant')
        result = np.zeros_like(mask, dtype=bool)
        for dy in range(-dilate, dilate+1):
            for dx in range(-dilate, dilate+1):
                result |= pad[dilate+dy:dilate+dy+mask.shape[0],
                               dilate+dx:dilate+dx+mask.shape[1]].astype(bool)
        return result
    return mask

# ---------------------------------------------------------------------------
# Main post-processing pipeline
# ---------------------------------------------------------------------------

def run_sobel_pass(color_path: str,
                   depth_thresh: float  = 0.01,
                   normal_thresh: float = 0.10,
                   id_thresh: float     = 1e-3,
                   outline_color        = (0.0, 0.0, 0.0),
                   outline_width: int   = 1,
                   output_path: str | None = None,
                   debug_aov: str       = 'none'):

    stem, ext = os.path.splitext(color_path)
    color    = read_exr(color_path)
    depth    = read_exr(stem + '_depth'    + ext)
    normal   = read_exr(stem + '_normal'   + ext)
    objectid = read_exr(stem + '_objectid' + ext)
    h, w = color.shape[:2]

    # --- DEBUG AOV visualisation ---
    if debug_aov != 'none':
        if debug_aov == 'depth':
            d = depth[:, :, 0]
            d_vis = np.where(d >= 0, d, 0.0)
            d_vis = (d_vis / (np.max(d_vis) + 1e-10)).astype(np.float32)
            result = np.stack([d_vis, d_vis, d_vis], axis=-1)
            tag = '_debug_depth'
        elif debug_aov == 'normal':
            result = ((normal + 1.0) * 0.5).clip(0, 1).astype(np.float32)
            tag = '_debug_normal'
        elif debug_aov == 'objectid':
            ids = objectid[:, :, 0]
            unique_ids = sorted(set(ids.ravel().tolist()))
            n = max(len(unique_ids), 1)
            result = np.zeros((h, w, 3), dtype=np.float32)
            for i, uid in enumerate(unique_ids):
                r, g, b = colorsys.hsv_to_rgb(
                    i / n,
                    0.0 if uid < 0 else 0.75,
                    0.15 if uid < 0 else 0.95)
                result[ids == uid] = [r, g, b]
            tag = '_debug_objectid'
        else:
            tag = '_debug_unknown'
            result = color.copy()
        out = output_path or (stem + tag + ext)
        write_exr(out, result)
        print(f'[sobel_post] Debug AOV ({debug_aov}) written -> {out}')
        return result

    # Task 3 — NaN / Infinity trap
    # If any AOV contains non-finite values, write a magenta debug image and abort.
    def _check_finite(arr, label):
        mask = ~np.isfinite(arr)
        if mask.any():
            return mask
        return None

    bad_depth  = _check_finite(depth,    'depth')
    bad_normal = _check_finite(normal,   'normal')
    bad_id     = _check_finite(objectid, 'objectid')
    any_bad    = np.zeros((h, w), dtype=bool)
    if bad_depth  is not None: any_bad |= bad_depth.any(axis=-1)
    if bad_normal is not None: any_bad |= bad_normal.any(axis=-1)
    if bad_id     is not None: any_bad |= bad_id.any(axis=-1)
    if any_bad.any():
        count = int(any_bad.sum())
        print(f'[sobel_post] WARNING: {count} pixels contain NaN/Inf in AOV buffers!')
        print(f'             depth  bad: {int(bad_depth.any(-1).sum())  if bad_depth  is not None else 0}')
        print(f'             normal bad: {int(bad_normal.any(-1).sum()) if bad_normal is not None else 0}')
        print(f'             id     bad: {int(bad_id.any(-1).sum())     if bad_id     is not None else 0}')
        # Write a magenta debug image highlighting the corrupt pixels
        debug_img = color.copy()
        debug_img[any_bad] = np.array([1.0, 0.0, 1.0], dtype=np.float32)  # magenta
        dbg_path = (output_path or (stem + '_outlined' + ext)).replace('.exr', '_nan_debug.exr')
        write_exr(dbg_path, debug_img)
        print(f'[sobel_post] Magenta debug image written -> {dbg_path}')
        # Replace bad values with safe defaults so edge detection can still run
        depth   = np.where(np.isfinite(depth),   depth,   -1.0)
        normal  = np.where(np.isfinite(normal),  normal,   0.0)
        objectid= np.where(np.isfinite(objectid),objectid, -1.0)

    # valid-pixel mask (depth >= 0 means the ray hit geometry)
    valid = (depth[:, :, 0] >= 0)

    # Normalise depth to [0,1] so depth_thresh is scale-invariant
    d_norm = np.where(valid, depth[:, :, 0], 0.0)
    d_norm = d_norm / (d_norm.max() + 1e-10)

    n   = normal                  # H×W×3, normals in [-1,1]
    oid = objectid[:, :, 0]       # H×W, integer shape IDs stored as float

    # -----------------------------------------------------------------------
    # Direct 4-connected neighbor comparison
    # For each adjacent pixel pair (right-neighbor + down-neighbor):
    #   depth_diff  = abs(depth[x,y]  - depth[neighbor])       (normalised)
    #   normal_diff = length(normal[x,y] - normal[neighbor])   (vector diff)
    #   id_changed  = (objectID[x,y] != objectID[neighbor])    (int compare)
    # Edge condition (OR-gate):
    #   depth_diff > depth_thresh  OR  normal_diff > normal_thresh  OR  id_changed
    # Silhouette: one pixel valid, its neighbor is background → mark the
    # valid pixel as an edge regardless of thresholds.
    # -----------------------------------------------------------------------
    cnt_depth  = np.zeros((h, w), dtype=bool)
    cnt_normal = np.zeros((h, w), dtype=bool)
    cnt_id     = np.zeros((h, w), dtype=bool)
    combined   = np.zeros((h, w), dtype=bool)

    for dy, dx in ((0, 1), (1, 0)):   # right-neighbor, then down-neighbor
        hy = h - dy          # number of rows in the slice
        wx = w - dx          # number of columns in the slice

        # Slice indices for the "self" pixel and the neighbor pixel
        r0 = (slice(None, hy or None), slice(None, wx or None))
        r1 = (slice(dy or None, None), slice(dx or None, None))

        s0 = valid[r0];  s1 = valid[r1]
        both = s0 & s1          # both pixels are valid geometry
        sil  = s0 ^ s1          # exactly one is valid → silhouette boundary

        depth_diff  = np.abs(d_norm[r0] - d_norm[r1])
        normal_diff = np.sqrt(np.sum((n[r0] - n[r1]) ** 2, axis=-1))
        # Robust integer comparison: any change >= 0.5 is a different shape ID
        id_changed  = np.abs(oid[r0] - oid[r1]) > 0.5

        edge_d = both & (depth_diff  > depth_thresh)
        edge_n = both & (normal_diff > normal_thresh)
        edge_i = both & id_changed
        interior = edge_d | edge_n | edge_i

        is_edge = interior | sil

        cnt_depth [r0] |= edge_d;   cnt_depth [r1] |= edge_d
        cnt_normal[r0] |= edge_n;   cnt_normal[r1] |= edge_n
        cnt_id    [r0] |= edge_i;   cnt_id    [r1] |= edge_i
        combined  [r0] |= is_edge;  combined  [r1] |= is_edge

    # Only stamp outlines on geometry pixels (leave background colour unchanged)
    combined   &= valid
    cnt_depth  &= valid
    cnt_normal &= valid
    cnt_id     &= valid

    print(f'[sobel_post]  depth  edges: {int(cnt_depth.sum()):>7}  ({100*cnt_depth.mean():.2f}%)')
    print(f'[sobel_post]  normal edges: {int(cnt_normal.sum()):>7}  ({100*cnt_normal.mean():.2f}%)')
    print(f'[sobel_post]  id     edges: {int(cnt_id.sum()):>7}  ({100*cnt_id.mean():.2f}%)')

    # Optional dilation for thicker outlines
    if outline_width > 1:
        pad     = outline_width - 1
        padded  = np.pad(combined.astype(np.uint8), pad, mode='constant')
        dilated = np.zeros((h, w), dtype=bool)
        for dy2 in range(-pad, pad + 1):
            for dx2 in range(-pad, pad + 1):
                if dy2 == 0 and dx2 == 0:
                    continue
                dilated |= padded[pad + dy2: pad + dy2 + h,
                                  pad + dx2: pad + dx2 + w].astype(bool)
        combined |= (dilated & valid)

    print(f'[sobel_post]  total  edges: {int(combined.sum()):>7}  ({100*combined.mean():.2f}%)')

    result = color.copy()
    result[combined] = np.array(outline_color, dtype=np.float32)

    if output_path is None:
        output_path = stem + '_outlined' + ext
    write_exr(output_path, result)
    print(f'[sobel_post] Wrote outlined image -> {output_path}')
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_rgb(s):
    parts = s.split(',')
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected R,G,B e.g. 0,0,0")
    return tuple(float(p) for p in parts)

def main():
    p = argparse.ArgumentParser(
        description="Sobel edge post-processing for NPR renders")
    p.add_argument("color_exr",
                   help="Path to the colour EXR (AOVs must be alongside it)")
    p.add_argument("--outline", default="0,0,0", type=_parse_rgb,
                   metavar="R,G,B",
                   help="Outline colour in linear float (default: 0,0,0 = black)")
    p.add_argument("--depth_thresh",  type=float, default=0.01,
                   help="Depth-difference threshold for edge detection, as a "
                        "fraction of the total depth range [0,1] (default 0.01)")
    p.add_argument("--normal_thresh", type=float, default=0.10,
                   help="Normal-difference threshold: Euclidean length of the "
                        "per-pixel normal vector difference in [-1,1] space "
                        "(max 2.0 at 180 deg; 1.41 at 90 deg; default 0.10)")
    p.add_argument("--id_thresh",     type=float, default=1e-3,
                   help="(Legacy, not used.) Object-ID comparison is now a "
                        "direct integer check (any ID boundary is an edge).")
    p.add_argument("--outline_width", type=int,   default=1,
                   help="Line thickness in pixels (default 1)")
    p.add_argument("-o", "--output",  default=None,
                   help="Output filename (default: <stem>_outlined.exr)")
    p.add_argument("--debug-aov", dest="debug_aov",
                   choices=['none', 'depth', 'normal', 'objectid'],
                   default='none',
                   help="Instead of outlining, write a visualisation of one "
                        "AOV buffer to verify it contains valid data. "
                        "depth: normalised [0,1] greyscale; "
                        "normal: XYZ remapped to [0,1] RGB; "
                        "objectid: unique colour per shape.")
    args = p.parse_args()

    run_sobel_pass(
        color_path    = args.color_exr,
        depth_thresh  = args.depth_thresh,
        normal_thresh = args.normal_thresh,
        id_thresh     = args.id_thresh,
        outline_color = args.outline,
        outline_width = args.outline_width,
        output_path   = args.output,
        debug_aov     = args.debug_aov,
    )

if __name__ == "__main__":
    main()
