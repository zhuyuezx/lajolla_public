"""
Painterly rendering post-processing effect.

Two modes:

1. **Litwinowicz '97** (``style='litwinowicz'``):
   Stroke-based impressionist rendering following:
     P. Litwinowicz, "Processing Images and Video for an Impressionist
     Effect", SIGGRAPH 1997.
   Algorithm:
     a) Place stroke centers on a jittered grid (spacing ``grid_spacing``).
     b) Compute per-pixel Sobel gradient; orient each stroke *perpendicular*
        to the local gradient so strokes follow contours.
     c) Clip strokes at detected edges (Canny) so paint does not bleed
        across object boundaries.
     d) Render each stroke as an anti-aliased line with circular brush tip
        (radius ``brush_radius``, half-length ``stroke_length``).
     e) Colour is sampled from the *source image* at the stroke center.

2. **Kuwahara-based** (``style='oil'/'watercolor'/'impressionist'``):
   Pixel-level Kuwahara smoothing + palette reduction + noise-based
   texture overlay (the original module, kept for backward compat).

The pipeline (Litwinowicz path):
    HDR input → tone map → pre-blur → compute gradient & edges →
    place jittered grid → orient & clip strokes → render to canvas →
    (optional) canvas texture → output
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import cv2
from image_io import (
    tone_map, to_grayscale, gaussian_blur, convolve2d,
    edge_strength, SOBEL_X, SOBEL_Y,
)


# ── Litwinowicz '97 stroke-based rendering ──────────────────────────────────

def _compute_gradient(gray):
    """Sobel gradient magnitude and direction."""
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    theta = np.arctan2(gy, gx)           # gradient direction
    return mag, theta


def _canny_edges(gray_u8, low=50, high=150):
    """Binary edge map via Canny."""
    return cv2.Canny(gray_u8, low, high) > 0


def _clip_stroke_at_edge(cx, cy, dx, dy, half_len, edge_map):
    """Walk from center outward in +/- direction; stop at edge pixel.

    Returns clipped (p0, p1) as integer pixel coords.
    """
    h, w = edge_map.shape
    steps = int(np.ceil(half_len))

    def _walk(sign):
        """Return max valid length in the given direction."""
        for t in range(1, steps + 1):
            px = int(round(cx + sign * dx * t))
            py = int(round(cy + sign * dy * t))
            if px < 0 or px >= w or py < 0 or py >= h:
                return t - 1
            if edge_map[py, px]:
                return t - 1
        return steps

    pos_len = _walk(+1)
    neg_len = _walk(-1)

    x0 = cx - dx * neg_len
    y0 = cy - dy * neg_len
    x1 = cx + dx * pos_len
    y1 = cy + dy * pos_len
    return (int(round(x0)), int(round(y0))), (int(round(x1)), int(round(y1)))


def litwinowicz_effect(
    img,
    exposure=1.0,
    tone_map_method='reinhard',
    grid_spacing=4,
    stroke_length=10,
    brush_radius=2,
    jitter=0.8,
    edge_clip=True,
    canny_low=50,
    canny_high=150,
    canvas_colour=None,
    canvas_strength=0.0,
    pre_blur_sigma=0.5,
    saturation_boost=0.15,
    seed=42,
):
    """Litwinowicz '97 stroke-based impressionist rendering.

    Args:
        img:              HDR float image (H, W, 3)
        exposure:         exposure multiplier
        tone_map_method:  'reinhard', 'aces', 'gamma', or 'clamp'
        grid_spacing:     pixel distance between stroke centers
        stroke_length:    half-length of each brush stroke (pixels)
        brush_radius:     radius of the circular brush tip (pixels)
        jitter:           random offset per grid point (fraction of spacing)
        edge_clip:        clip strokes at Canny edges
        canny_low/high:   Canny thresholds
        canvas_colour:    RGB [0-1] background; None → mean image colour
        canvas_strength:  paper/canvas noise strength (0 = off)
        pre_blur_sigma:   Gaussian blur to reduce MC noise before processing
        saturation_boost: boost colour vibrancy
        seed:             random seed for jitter / draw order

    Returns:
        Float RGB image (H, W, 3) in [0, 1]
    """
    h, w = img.shape[:2]
    rng = np.random.RandomState(seed)

    # 1) Tone map
    ldr = tone_map(img[:, :, :3], exposure=exposure, method=tone_map_method)

    # 2) Pre-blur to smooth Monte-Carlo noise
    if pre_blur_sigma > 0:
        ldr = gaussian_blur(ldr, sigma=pre_blur_sigma)

    # 3) Saturation boost
    if saturation_boost != 0:
        gray_tmp = to_grayscale(ldr)
        ldr = ldr + (ldr - gray_tmp[:, :, np.newaxis]) * saturation_boost
        ldr = np.clip(ldr, 0, 1).astype(np.float32)

    # 4) Gradient field (on grayscale)
    gray = to_grayscale(ldr)
    gray_u8 = np.clip(gray * 255, 0, 255).astype(np.uint8)
    mag, theta = _compute_gradient(gray)

    # 5) Edge map for clipping
    edge_map = _canny_edges(gray_u8, canny_low, canny_high) if edge_clip else np.zeros((h, w), dtype=bool)

    # 6) Build jittered grid of stroke centres
    ys = np.arange(0, h, grid_spacing)
    xs = np.arange(0, w, grid_spacing)
    centres = np.array(np.meshgrid(xs, ys)).T.reshape(-1, 2)  # (N, 2) as (x, y)
    # Add jitter
    jitter_px = grid_spacing * jitter
    centres = centres.astype(np.float64)
    centres += rng.uniform(-jitter_px, jitter_px, centres.shape)
    centres[:, 0] = np.clip(centres[:, 0], 0, w - 1)
    centres[:, 1] = np.clip(centres[:, 1], 0, h - 1)

    # Random painting order
    order = rng.permutation(len(centres))

    # 7) Prepare canvas
    canvas = np.empty((h, w, 3), dtype=np.float32)
    if canvas_colour is not None:
        canvas[:] = np.array(canvas_colour, dtype=np.float32)
    else:
        canvas[:] = ldr.mean(axis=(0, 1))

    # 8) Paint strokes
    brush_d = max(1, brush_radius * 2)  # diameter for cv2 line thickness
    for idx in order:
        cx, cy = int(round(centres[idx, 0])), int(round(centres[idx, 1]))
        if cx < 0 or cx >= w or cy < 0 or cy >= h:
            continue

        # Colour from source image
        colour = ldr[cy, cx]

        # Stroke direction = perpendicular to gradient
        t = theta[cy, cx] + np.pi / 2.0
        dx = np.cos(t)
        dy = np.sin(t)

        half_len = stroke_length

        # Clip at edges
        if edge_clip:
            p0, p1 = _clip_stroke_at_edge(cx, cy, dx, dy, half_len, edge_map)
        else:
            p0 = (int(round(cx - dx * half_len)), int(round(cy - dy * half_len)))
            p1 = (int(round(cx + dx * half_len)), int(round(cy + dy * half_len)))

        # Skip degenerate strokes
        if p0 == p1:
            continue

        # Render anti-aliased line with cv2 (canvas is RGB, cv2 is channel-agnostic for float)
        colour_rgb = (float(colour[0]), float(colour[1]), float(colour[2]))
        cv2.line(canvas, p0, p1, colour_rgb, thickness=brush_d, lineType=cv2.LINE_AA)

    # 9) Optional canvas/paper texture
    if canvas_strength > 0:
        canvas = apply_canvas_texture(canvas, strength=canvas_strength)

    return np.clip(canvas, 0, 1).astype(np.float32)


# ── Kuwahara filter ─────────────────────────────────────────────────────────

def kuwahara_filter(img, radius=4):
    """Apply Kuwahara filter for oil-painting-like smoothing.
    
    For each pixel, divides a (2r+1)×(2r+1) neighborhood into 4 overlapping
    quadrants. Picks the quadrant with the lowest variance and uses its mean
    as the output color. This smooths flat areas while preserving edges.
    
    Args:
        img: float32 (H, W, 3) image in [0, 1]
        radius: filter radius (larger = smoother/more painterly)
    Returns:
        Filtered image
    """
    h, w, c = img.shape
    r = radius
    padded = np.pad(img, ((r, r), (r, r), (0, 0)), mode='edge')
    result = np.empty_like(img)

    # Precompute integral images for mean and mean-of-squares (fast box sums)
    integral = np.zeros((h + 2 * r + 1, w + 2 * r + 1, c), dtype=np.float64)
    integral_sq = np.zeros_like(integral)

    np.cumsum(padded, axis=0, out=integral[1:, :, :])
    integral = integral[:h + 2 * r, :, :]
    integral = np.insert(integral, 0, 0, axis=0)
    # Recompute properly
    integral = np.zeros((h + 2 * r + 1, w + 2 * r + 1, c), dtype=np.float64)
    integral_sq = np.zeros_like(integral)
    integral[1:, 1:, :] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    integral_sq[1:, 1:, :] = np.cumsum(np.cumsum(padded ** 2, axis=0), axis=1)

    def _box_stats(y0, x0, y1, x1):
        """Get mean and variance for a rectangular region using integral images."""
        n = max((y1 - y0) * (x1 - x0), 1)
        s = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
        sq = integral_sq[y1, x1] - integral_sq[y0, x1] - integral_sq[y1, x0] + integral_sq[y0, x0]
        mean = s / n
        var = np.sum(sq / n - mean ** 2, axis=-1)  # Sum variance across channels
        return mean, var

    # For each pixel, compute stats for 4 quadrants and pick lowest variance
    for y in range(h):
        for x in range(w):
            py, px = y + r, x + r  # Position in padded/integral coords

            # Four quadrants: top-left, top-right, bottom-left, bottom-right
            regions = [
                (py - r, px - r, py + 1, px + 1),  # top-left
                (py - r, px,     py + 1, px + r + 1),  # top-right
                (py,     px - r, py + r + 1, px + 1),  # bottom-left
                (py,     px,     py + r + 1, px + r + 1),  # bottom-right
            ]

            best_mean = None
            best_var = float('inf')
            for (y0, x0, y1, x1) in regions:
                mean, var = _box_stats(y0, x0, y1, x1)
                if var < best_var:
                    best_var = var
                    best_mean = mean

            result[y, x] = best_mean

    return np.clip(result, 0, 1).astype(np.float32)


def kuwahara_filter_fast(img, radius=4):
    """Vectorized approximate Kuwahara filter (much faster for large images).
    
    Instead of pixel-by-pixel, computes all 4 quadrant statistics using
    integral images and vectorized numpy ops.
    """
    h, w, c = img.shape
    r = radius
    padded = np.pad(img, ((r, r), (r, r), (0, 0)), mode='edge')
    ph, pw = padded.shape[:2]

    # Integral images
    integral = np.zeros((ph + 1, pw + 1, c), dtype=np.float64)
    integral_sq = np.zeros((ph + 1, pw + 1, c), dtype=np.float64)
    integral[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    integral_sq[1:, 1:] = np.cumsum(np.cumsum(padded ** 2, axis=0), axis=1)

    def _box_sum(integ, y0, x0, y1, x1):
        return integ[y1, x1] - integ[y0, x1] - integ[y1, x0] + integ[y0, x0]

    # Quadrant regions for all pixels (in integral coords, 1-indexed)
    # Each pixel (y, x) in original maps to (y+r, x+r) in padded
    ys = np.arange(h) + r  # padded y coords
    xs = np.arange(w) + r
    n_quad = (r + 1) * (r + 1)  # pixels per quadrant

    # Compute integral coords for each quadrant
    # Top-left: [y-r .. y+1) × [x-r .. x+1)
    quadrants = [
        (ys - r, xs - r, ys + 1, xs + 1),      # top-left
        (ys - r, xs,     ys + 1, xs + r + 1),   # top-right
        (ys,     xs - r, ys + r + 1, xs + 1),   # bottom-left
        (ys,     xs,     ys + r + 1, xs + r + 1),  # bottom-right
    ]

    means = np.empty((4, h, w, c), dtype=np.float64)
    variances = np.empty((4, h, w), dtype=np.float64)

    for qi, (qy0, qx0, qy1, qx1) in enumerate(quadrants):
        # Build index arrays for all pixels
        y0 = qy0[:, np.newaxis]  # (h, 1)
        x0 = qx0[np.newaxis, :]  # (1, w)
        y1 = qy1[:, np.newaxis]
        x1 = qx1[np.newaxis, :]

        s = (integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0])
        sq = (integral_sq[y1, x1] - integral_sq[y0, x1] - integral_sq[y1, x0] + integral_sq[y0, x0])

        mean = s / n_quad
        var = np.sum(sq / n_quad - mean ** 2, axis=-1)

        means[qi] = mean
        variances[qi] = var

    # Pick quadrant with minimum variance per pixel
    best_q = np.argmin(variances, axis=0)  # (h, w)

    # Gather the best mean for each pixel
    result = np.empty((h, w, c), dtype=np.float32)
    for qi in range(4):
        mask = (best_q == qi)
        result[mask] = means[qi][mask]

    return np.clip(result, 0, 1).astype(np.float32)


# ── Brush stroke texture ────────────────────────────────────────────────────

def generate_stroke_noise(h, w, scale=8, seed=42):
    """Generate oriented noise for brush stroke texture.
    
    Creates a tileable noise pattern that simulates paint strokes
    when combined with image gradients.
    """
    rng = np.random.RandomState(seed)
    # Multi-octave noise gives more natural brush texture
    noise = np.zeros((h, w), dtype=np.float32)
    for octave in range(3):
        freq = max(1, scale // (2 ** octave))
        small = rng.rand(max(1, h // freq), max(1, w // freq)).astype(np.float32)
        # Bilinear upsample
        from numpy import interp
        ys = np.linspace(0, small.shape[0] - 1, h)
        xs = np.linspace(0, small.shape[1] - 1, w)
        # Row-wise interpolation
        rows = np.array([np.interp(xs, np.arange(small.shape[1]), small[int(y)])
                         for y in np.floor(ys).astype(int)])
        amplitude = 1.0 / (2 ** octave)
        noise += rows * amplitude
    noise = noise / noise.max()
    return noise


def apply_stroke_texture(img, gray, strength=0.15, scale=8, seed=42):
    """Overlay brush stroke texture oriented by image gradients.
    
    Args:
        img: RGB image (H, W, 3)
        gray: grayscale version
        strength: texture visibility (0 = none, 0.3 = heavy)
        scale: noise scale (larger = bigger strokes)
        seed: random seed for reproducibility
    Returns:
        Textured image
    """
    h, w = gray.shape
    noise = generate_stroke_noise(h, w, scale=scale, seed=seed)

    # Modulate noise by edge proximity: less texture near edges
    edges = edge_strength(gray, method='sobel')
    noise_modulated = noise * (1.0 - edges * 0.7)

    # Apply as multiplicative texture
    texture = 1.0 + (noise_modulated - 0.5) * 2.0 * strength
    result = img * texture[:, :, np.newaxis]
    return np.clip(result, 0, 1).astype(np.float32)


# ── Color palette reduction ─────────────────────────────────────────────────

def reduce_palette_uniform(img, num_colors=16):
    """Reduce color palette by uniform quantization per channel.
    
    Args:
        img: RGB float image [0, 1]
        num_colors: total palette size (will be cube-rooted per channel)
    Returns:
        Quantized image
    """
    levels = max(2, int(round(num_colors ** (1 / 3))))
    quantized = np.round(img * (levels - 1)) / (levels - 1)
    return np.clip(quantized, 0, 1).astype(np.float32)


def reduce_palette_kmeans(img, num_colors=12, max_iter=20):
    """Reduce color palette via simple k-means clustering.
    
    Args:
        img: RGB float image [0, 1]
        num_colors: number of palette colors
        max_iter: k-means iterations
    Returns:
        Quantized image
    """
    h, w, c = img.shape
    pixels = img.reshape(-1, c).astype(np.float64)

    # Initialize centroids from random pixels
    rng = np.random.RandomState(42)
    indices = rng.choice(len(pixels), size=num_colors, replace=False)
    centroids = pixels[indices].copy()

    for _ in range(max_iter):
        # Assign each pixel to nearest centroid
        dists = np.sum((pixels[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2, axis=2)
        labels = np.argmin(dists, axis=1)
        # Update centroids
        new_centroids = np.empty_like(centroids)
        for k in range(num_colors):
            mask = (labels == k)
            if np.any(mask):
                new_centroids[k] = pixels[mask].mean(axis=0)
            else:
                new_centroids[k] = centroids[k]
        if np.allclose(centroids, new_centroids, atol=1e-5):
            break
        centroids = new_centroids

    # Final assignment
    dists = np.sum((pixels[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2, axis=2)
    labels = np.argmin(dists, axis=1)
    result = centroids[labels].reshape(h, w, c)
    return np.clip(result, 0, 1).astype(np.float32)


# ── Canvas texture ──────────────────────────────────────────────────────────

def apply_canvas_texture(img, strength=0.05, seed=123):
    """Add subtle canvas/paper texture.
    
    Simulates the texture of painting on canvas or rough paper.
    """
    h, w = img.shape[:2]
    rng = np.random.RandomState(seed)
    # High-frequency canvas texture
    canvas = rng.rand(h, w).astype(np.float32)
    # Low-pass to make it less noisy
    from image_io import gaussian_blur as gb
    canvas = gb(canvas, sigma=0.8)
    canvas = (canvas - canvas.mean()) * strength
    result = img + canvas[:, :, np.newaxis]
    return np.clip(result, 0, 1).astype(np.float32)


# ── Main effects ────────────────────────────────────────────────────────────

def painterly_effect(
    img,
    exposure=1.0,
    tone_map_method='reinhard',
    style='litwinowicz',
    kuwahara_radius=4,
    palette_method='uniform',
    num_colors=16,
    stroke_strength=0.15,
    stroke_scale=8,
    edge_darken=0.3,
    edge_threshold=0.05,
    canvas_strength=0.05,
    pre_blur_sigma=0.5,
    saturation_boost=0.1,
    # Litwinowicz-specific params
    grid_spacing=4,
    stroke_length=10,
    brush_radius=2,
    jitter=0.8,
    edge_clip=True,
    canny_low=50,
    canny_high=150,
    seed=42,
):
    """Apply painterly rendering post-processing.
    
    Args:
        img:                HDR float image (H, W, 3)
        exposure:           exposure multiplier
        tone_map_method:    'reinhard', 'aces', 'gamma', or 'clamp'
        style:              'litwinowicz' (Litwinowicz '97 stroke rendering),
                            'oil' (Kuwahara heavy), 'watercolor' (lighter + bleed),
                            'impressionist' (stroke-heavy + vibrant — Kuwahara based)
        --- Kuwahara-based params (oil/watercolor/impressionist) ---
        kuwahara_radius:    smoothing radius (larger = more abstract)
        palette_method:     'uniform', 'kmeans', or 'none'
        num_colors:         palette size for color reduction
        stroke_strength:    brush texture visibility (0–0.4)
        stroke_scale:       brush stroke size
        edge_darken:        darken edges to simulate paint accumulation
        edge_threshold:     edge detection sensitivity
        canvas_strength:    paper/canvas texture strength (0 = off)
        pre_blur_sigma:     smooth MC noise before processing
        saturation_boost:   boost color vibrancy
        --- Litwinowicz params ---
        grid_spacing:       pixel distance between stroke centers
        stroke_length:      half-length of each brush stroke (pixels)
        brush_radius:       radius of the circular brush tip (pixels)
        jitter:             random offset per grid point (fraction of spacing)
        edge_clip:          clip strokes at Canny edges
        canny_low/high:     Canny thresholds
        seed:               random seed

    Returns:
        Float RGB image (H, W, 3) in [0, 1]
    """
    # ── Litwinowicz '97 path ────────────────────────────────────────────
    if style == 'litwinowicz':
        return litwinowicz_effect(
            img,
            exposure=exposure,
            tone_map_method=tone_map_method,
            grid_spacing=grid_spacing,
            stroke_length=stroke_length,
            brush_radius=brush_radius,
            jitter=jitter,
            edge_clip=edge_clip,
            canny_low=canny_low,
            canny_high=canny_high,
            canvas_strength=canvas_strength,
            pre_blur_sigma=pre_blur_sigma,
            saturation_boost=saturation_boost,
            seed=seed,
        )
    # ── Kuwahara-based path (oil / watercolor / impressionist) ────────────
    # Apply style presets
    if style == 'watercolor':
        if kuwahara_radius == 4:  # Only override if still default
            kuwahara_radius = 3
        if stroke_strength == 0.15:
            stroke_strength = 0.05
        if edge_darken == 0.3:
            edge_darken = 0.15
        if saturation_boost == 0.1:
            saturation_boost = -0.05  # Watercolors are more washed out
    elif style == 'impressionist':
        if kuwahara_radius == 4:
            kuwahara_radius = 3
        if stroke_strength == 0.15:
            stroke_strength = 0.3
        if stroke_scale == 8:
            stroke_scale = 12
        if saturation_boost == 0.1:
            saturation_boost = 0.25  # Impressionism = vivid colors

    h, w = img.shape[:2]

    # 1) Tone map
    ldr = tone_map(img[:, :, :3], exposure=exposure, method=tone_map_method)

    # 2) Pre-blur to smooth MC noise
    if pre_blur_sigma > 0:
        ldr = gaussian_blur(ldr, sigma=pre_blur_sigma)

    # 3) Kuwahara filter for paint-like smoothing
    if kuwahara_radius > 0:
        print(f"    Kuwahara filter (radius={kuwahara_radius}) ...")
        ldr = kuwahara_filter_fast(ldr, radius=kuwahara_radius)

    # 4) Saturation boost
    if saturation_boost != 0:
        gray = to_grayscale(ldr)
        ldr = ldr + (ldr - gray[:, :, np.newaxis]) * saturation_boost
        ldr = np.clip(ldr, 0, 1).astype(np.float32)

    # 5) Color palette reduction
    if palette_method == 'uniform':
        ldr = reduce_palette_uniform(ldr, num_colors=num_colors)
    elif palette_method == 'kmeans':
        print(f"    K-means palette reduction ({num_colors} colors) ...")
        ldr = reduce_palette_kmeans(ldr, num_colors=num_colors)

    # 6) Brush stroke texture
    gray = to_grayscale(ldr)
    if stroke_strength > 0:
        ldr = apply_stroke_texture(ldr, gray, strength=stroke_strength, scale=stroke_scale)

    # 7) Edge darkening (paint accumulates at edges)
    if edge_darken > 0:
        edges = edge_strength(gray, method='sobel')
        darkening = 1.0 - edges * edge_darken
        ldr = ldr * darkening[:, :, np.newaxis]
        ldr = np.clip(ldr, 0, 1).astype(np.float32)

    # 8) Canvas texture
    if canvas_strength > 0:
        ldr = apply_canvas_texture(ldr, strength=canvas_strength)

    return ldr
