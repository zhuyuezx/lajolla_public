"""
Return of the Obra Dinn style post-processing.

Replicates the 1-bit dithering aesthetic of Lucas Pope's "Return of the Obra Dinn".
The technique (based on Pope's TIGSource devlog and GDC talks):

1. Render scene with standard lighting (lajolla handles this)
2. Tone map HDR → LDR, convert to grayscale luminance
3. Detect edges via Sobel/Laplacian for crisp outlines
4. Apply ordered dithering with a Bayer matrix → 1-bit output
5. Composite edges (forced dark) over the dithered image
6. Map the binary result to a 2-color palette

The Bayer matrix creates the illusion of continuous tone using only two colors,
and the screen-space tiling keeps the pattern stable across frames.

Key tuning parameters:
  - exposure / contrast / brightness: control the tonal range before dithering
  - bayer_size: 2 (4x4) for coarse, 3 (8x8) for medium, 4 (16x16) for fine dithering
  - edge_threshold: lower = more edges visible
  - downscale: integer factor for a chunky pixel aesthetic
"""

import numpy as np
from image_io import tone_map, to_grayscale


# ── Convolution helper (no scipy dependency) ───────────────────────────────

def _convolve2d(img, kernel):
    """2D convolution via vectorized numpy slicing. Edges are replicate-padded."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(img, ((ph, ph), (pw, pw)), mode='edge')
    result = np.zeros_like(img)
    for i in range(kh):
        for j in range(kw):
            result += padded[i:i + img.shape[0], j:j + img.shape[1]] * kernel[i, j]
    return result


# ── Bayer dithering ─────────────────────────────────────────────────────────

def generate_bayer_matrix(n):
    """Generate a normalized Bayer threshold matrix of size 2^n × 2^n.
    
    Recursive definition:
        M(0) = [0]
        M(n) = (1/4^n) * [[4·M(n-1),   4·M(n-1)+2],
                           [4·M(n-1)+3, 4·M(n-1)+1]]
    Returns values in [0, 1).
    """
    if n == 0:
        return np.array([[0.0]], dtype=np.float32)
    prev = generate_bayer_matrix(n - 1)
    s = prev.shape[0]
    m = np.empty((2 * s, 2 * s), dtype=np.float32)
    m[:s, :s] = 4 * prev
    m[:s, s:] = 4 * prev + 2
    m[s:, :s] = 4 * prev + 3
    m[s:, s:] = 4 * prev + 1
    return m / float((2 * s) ** 2)


def ordered_dither(gray, bayer_size=3):
    """Ordered dithering using a tiled Bayer matrix.
    
    Args:
        gray: 2D float array in [0, 1]
        bayer_size: matrix order — produces a 2^n × 2^n threshold map
                    2 → 4×4, 3 → 8×8 (classic), 4 → 16×16 (fine)
    Returns:
        Binary float array (0.0 or 1.0)
    """
    bayer = generate_bayer_matrix(bayer_size)
    ms = bayer.shape[0]
    h, w = gray.shape
    # Tile the threshold map across the full image
    threshold = np.tile(bayer, (h // ms + 1, w // ms + 1))[:h, :w]
    return (gray > threshold).astype(np.float32)


# ── Edge detection ──────────────────────────────────────────────────────────

_SOBEL_X = np.array([[-1, 0, 1],
                     [-2, 0, 2],
                     [-1, 0, 1]], dtype=np.float32)

_SOBEL_Y = np.array([[-1, -2, -1],
                     [ 0,  0,  0],
                     [ 1,  2,  1]], dtype=np.float32)

_LAPLACIAN = np.array([[ 0,  1,  0],
                       [ 1, -4,  1],
                       [ 0,  1,  0]], dtype=np.float32)


def detect_edges(gray, method='sobel', threshold=0.1):
    """Detect edges in a grayscale image.
    
    Args:
        gray: 2D float array
        method: 'sobel', 'laplacian', or 'combined'
        threshold: normalized threshold (0–1) for binarizing edge strength
    Returns:
        Binary float edge map (1.0 = edge)
    """
    if method in ('sobel', 'combined'):
        gx = _convolve2d(gray, _SOBEL_X)
        gy = _convolve2d(gray, _SOBEL_Y)
        edges_sobel = np.sqrt(gx ** 2 + gy ** 2)

    if method in ('laplacian', 'combined'):
        edges_lap = np.abs(_convolve2d(gray, _LAPLACIAN))

    if method == 'sobel':
        edges = edges_sobel
    elif method == 'laplacian':
        edges = edges_lap
    elif method == 'combined':
        edges = np.maximum(edges_sobel, edges_lap * 0.5)
    else:
        raise ValueError(f"Unknown edge method: {method}")

    # Normalize to [0, 1] then threshold
    emax = edges.max()
    if emax > 0:
        edges = edges / emax
    return (edges > threshold).astype(np.float32)


# ── Color palettes ──────────────────────────────────────────────────────────

PALETTES = {
    # (dark_rgb_0-255, light_rgb_0-255)
    'bw':              (np.array([  0,   0,   0]), np.array([255, 255, 255])),
    'obra_dinn':       (np.array([ 46,  34,  47]), np.array([210, 202, 173])),
    'sepia':           (np.array([ 30,  20,  10]), np.array([210, 180, 140])),
    'mac_classic':     (np.array([ 30,  30,  30]), np.array([200, 200, 200])),
    'green_phosphor':  (np.array([  0,  20,   0]), np.array([  0, 255,   0])),
    'amber_phosphor':  (np.array([ 20,  10,   0]), np.array([255, 176,   0])),
}


def apply_palette(binary, palette='obra_dinn'):
    """Map a binary (0/1) image to a 2-color palette.
    
    Args:
        binary: 2D float array (0.0 or 1.0)
        palette: key from PALETTES dict, or (dark_rgb, light_rgb) tuple with 0-255 values
    Returns:
        Float RGB image (H, W, 3) in [0, 1]
    """
    if isinstance(palette, str):
        if palette not in PALETTES:
            raise ValueError(f"Unknown palette '{palette}'. Options: {list(PALETTES.keys())}")
        dark, light = PALETTES[palette]
    else:
        dark, light = palette
    dark = np.asarray(dark, dtype=np.float32) / 255.0
    light = np.asarray(light, dtype=np.float32) / 255.0

    h, w = binary.shape
    result = np.empty((h, w, 3), dtype=np.float32)
    mask = binary > 0.5
    result[mask] = light
    result[~mask] = dark
    return result


# ── Downscale / upscale helpers ─────────────────────────────────────────────

def _box_downscale(img, factor):
    """Average-pool downscale by an integer factor."""
    h, w = img.shape[:2]
    nh, nw = h // factor, w // factor
    # Crop to exact multiple
    cropped = img[:nh * factor, :nw * factor]
    if cropped.ndim == 3:
        return cropped.reshape(nh, factor, nw, factor, -1).mean(axis=(1, 3))
    return cropped.reshape(nh, factor, nw, factor).mean(axis=(1, 3))


def _nn_upscale(img, factor):
    """Nearest-neighbor upscale by an integer factor."""
    return np.repeat(np.repeat(img, factor, axis=0), factor, axis=1)


# ── Main effect ─────────────────────────────────────────────────────────────

def obra_dinn_effect(
    img,
    exposure=1.0,
    tone_map_method='reinhard',
    bayer_size=3,
    edge_method='sobel',
    edge_threshold=0.1,
    edge_weight=1.0,
    contrast=1.0,
    brightness=0.0,
    palette='obra_dinn',
    downscale=1,
):
    """Apply the full Return of the Obra Dinn post-processing pipeline.
    
    Args:
        img:             HDR float image (H, W, 3)
        exposure:        exposure multiplier applied before tone mapping
        tone_map_method: 'reinhard', 'aces', 'gamma', or 'clamp'
        bayer_size:      Bayer matrix order (2→4×4, 3→8×8, 4→16×16)
        edge_method:     'sobel', 'laplacian', or 'combined'
        edge_threshold:  edge binarization threshold (lower → more edges)
        edge_weight:     0 = no edges, 1 = full edge overlay
        contrast:        contrast multiplier around midpoint
        brightness:      additive brightness offset
        palette:         palette name or (dark_rgb, light_rgb) tuple
        downscale:       integer downscale factor for chunky pixel look

    Returns:
        Float RGB image (H, W, 3) in [0, 1]
    """
    original_h, original_w = img.shape[:2]

    # Optional downscale for pixelated aesthetic
    if downscale > 1:
        img = _box_downscale(img, downscale).astype(np.float32)

    h, w = img.shape[:2]

    # 1) Tone map HDR → [0, 1]
    ldr = tone_map(img[:, :, :3], exposure=exposure, method=tone_map_method)

    # 2) Grayscale luminance
    gray = to_grayscale(ldr)

    # 3) Contrast / brightness adjustment
    gray = np.clip((gray - 0.5) * contrast + 0.5 + brightness, 0, 1).astype(np.float32)

    # 4) Edge detection
    edges = detect_edges(gray, method=edge_method, threshold=edge_threshold)

    # 5) Ordered dithering → binary
    dithered = ordered_dither(gray, bayer_size=bayer_size)

    # 6) Composite: edges force dark pixels
    composited = dithered * (1.0 - edges * np.clip(edge_weight, 0, 1))
    composited = np.clip(composited, 0, 1)

    # 7) Apply 2-color palette
    result = apply_palette(composited, palette=palette)

    # Upscale back to original resolution if downscaled
    if downscale > 1:
        result = _nn_upscale(result, downscale)
        # Crop to original size (in case of rounding)
        result = result[:original_h, :original_w]

    return result
