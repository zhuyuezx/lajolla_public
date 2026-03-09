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
                   depth_thresh: float  = 50.0,
                   normal_thresh: float = 0.30,
                   id_thresh: float     = 0.50,
                   outline_color        = (0.0, 0.0, 0.0),
                   outline_width: int   = 1,
                   output_path: str | None = None):

    stem, ext = os.path.splitext(color_path)

    # --- load all buffers ---
    color    = read_exr(color_path)
    depth    = read_exr(stem + '_depth'    + ext)
    normal   = read_exr(stem + '_normal'   + ext)
    objectid = read_exr(stem + '_objectid' + ext)

    print(f"[sobel_post] Loaded buffers  {color.shape[0]}×{color.shape[1]}")

    # --- build edge masks per AOV ---
    # Depth: miss pixels hold depth=-1; clamp their gradient to zero so we
    # don't draw outlines at the scene boundary vs sky (unless desired).
    depth_valid = (depth[:,:,0] >= 0).astype(np.float32)
    depth_masked = depth[:,:,0] * depth_valid
    depth_mag  = _sobel(depth_masked)
    edge_depth = (depth_mag > depth_thresh)

    edge_norm  = edge_mask(normal,   normal_thresh, dilate=0)
    edge_id    = edge_mask(objectid, id_thresh,     dilate=0)

    # Union of all edge sources
    combined = edge_depth | edge_norm | edge_id

    # Dilate to desired line width
    if outline_width > 1:
        combined = edge_mask(
            np.stack([combined.astype(np.float32)]*3, axis=-1),
            0.5, dilate=outline_width-1)

    print(f"[sobel_post] Edge pixels: {combined.sum()} / {combined.size}  "
          f"({100*combined.mean():.2f}%)")

    # --- composite onto colour image ---
    result = color.copy()
    oc = np.array(outline_color, dtype=np.float32)
    result[combined] = oc

    # --- write output ---
    if output_path is None:
        output_path = stem + '_outlined' + ext
    write_exr(output_path, result)
    print(f"[sobel_post] Wrote outlined image → {output_path}")
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
    p.add_argument("--depth_thresh",  type=float, default=50.0,
                   help="Sobel magnitude threshold for depth edges (default 50)")
    p.add_argument("--normal_thresh", type=float, default=0.30,
                   help="Sobel magnitude threshold for normal edges (default 0.3)")
    p.add_argument("--id_thresh",     type=float, default=0.50,
                   help="Sobel magnitude threshold for object-ID edges (default 0.5)")
    p.add_argument("--outline_width", type=int,   default=1,
                   help="Line thickness in pixels (default 1)")
    p.add_argument("-o", "--output",  default=None,
                   help="Output filename (default: <stem>_outlined.exr)")
    args = p.parse_args()

    run_sobel_pass(
        color_path    = args.color_exr,
        depth_thresh  = args.depth_thresh,
        normal_thresh = args.normal_thresh,
        id_thresh     = args.id_thresh,
        outline_color = args.outline,
        outline_width = args.outline_width,
        output_path   = args.output,
    )

if __name__ == "__main__":
    main()
