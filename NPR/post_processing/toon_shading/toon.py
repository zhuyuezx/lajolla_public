"""
Toon / Cel Shading post-processing effect.

Simulates the classic cel-shaded look used in games like Jet Set Radio,
The Legend of Zelda: Wind Waker, and Borderlands.

Pipeline:
1. Tone map HDR → LDR
2. Quantize luminance into discrete shading bands (cel shading)
3. Optionally quantize hue/saturation for a limited color palette feel
4. Detect edges (Sobel) and overlay as dark outlines
5. Optional specular highlight band (hard cutoff)

The key artistic insight: real-time toon shaders quantize the N·L dot product
into 2-4 bands. In post-processing we approximate this by quantizing the
luminance channel, which captures the same light/shadow transitions.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from image_io import (
    tone_map, to_grayscale, detect_edges, edge_strength,
    gaussian_blur, convolve2d, SOBEL_X, SOBEL_Y,
)


# ── Luminance quantization (cel bands) ──────────────────────────────────────

def quantize_luminance(gray, num_bands=4, smoothing=0.0):
    """Quantize grayscale values into discrete bands.
    
    Args:
        gray: 2D float array in [0, 1]
        num_bands: number of shading levels (2 = binary shadow/lit, 4 = typical cel)
        smoothing: transition softness between bands (0 = hard, >0 = smooth)
    Returns:
        Quantized 2D float array in [0, 1]
    """
    if smoothing > 0:
        # Soft quantization: smoothstep-like transitions
        scaled = gray * num_bands
        floored = np.floor(scaled).astype(np.float32)
        t = scaled - floored
        # Smooth hermite interpolation at band edges
        width = smoothing
        t_smooth = np.clip((t - 0.5 + width) / (2 * width), 0, 1)
        t_smooth = t_smooth * t_smooth * (3 - 2 * t_smooth)  # smoothstep
        quantized = (floored + t_smooth) / num_bands
    else:
        # Hard quantization
        quantized = np.floor(gray * num_bands) / num_bands
    return np.clip(quantized, 0, 1).astype(np.float32)


# ── Color quantization ──────────────────────────────────────────────────────

def rgb_to_hsv(img):
    """Convert RGB [0,1] to HSV [0,1]."""
    r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    # Hue
    h = np.zeros_like(delta)
    mask_r = (cmax == r) & (delta > 0)
    mask_g = (cmax == g) & (delta > 0)
    mask_b = (cmax == b) & (delta > 0)
    h[mask_r] = ((g[mask_r] - b[mask_r]) / delta[mask_r]) % 6
    h[mask_g] = (b[mask_g] - r[mask_g]) / delta[mask_g] + 2
    h[mask_b] = (r[mask_b] - g[mask_b]) / delta[mask_b] + 4
    h = h / 6.0

    # Saturation
    s = np.where(cmax > 0, delta / np.maximum(cmax, 1e-10), 0)

    # Value
    v = cmax

    return np.stack([h, s, v], axis=-1).astype(np.float32)


def hsv_to_rgb(img):
    """Convert HSV [0,1] to RGB [0,1]."""
    h, s, v = img[:, :, 0] * 6.0, img[:, :, 1], img[:, :, 2]
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))

    result = np.zeros_like(img)
    for idx, (r, g, b) in enumerate([(v, t, p), (q, v, p), (p, v, t),
                                      (p, q, v), (t, p, v), (v, p, q)]):
        mask = (i == idx)
        result[:, :, 0][mask] = r[mask]
        result[:, :, 1][mask] = g[mask]
        result[:, :, 2][mask] = b[mask]
    return np.clip(result, 0, 1).astype(np.float32)


def quantize_color(img, hue_bins=12, sat_bins=4, val_bins=4):
    """Quantize colors in HSV space for a limited-palette cartoon look.
    
    Args:
        img: RGB float image [0, 1]
        hue_bins: number of hue quantization levels (12 = 30° steps)
        sat_bins: number of saturation levels
        val_bins: number of value/brightness levels
    Returns:
        Quantized RGB image
    """
    hsv = rgb_to_hsv(img)
    if hue_bins > 0:
        hsv[:, :, 0] = np.round(hsv[:, :, 0] * hue_bins) / hue_bins
    if sat_bins > 0:
        hsv[:, :, 1] = np.round(hsv[:, :, 1] * sat_bins) / sat_bins
    if val_bins > 0:
        hsv[:, :, 2] = np.round(hsv[:, :, 2] * val_bins) / val_bins
    return hsv_to_rgb(hsv)


# ── Specular highlight band ─────────────────────────────────────────────────

def specular_band(gray, threshold=0.85, boost=0.15):
    """Create a hard specular highlight band for cel-shading.
    
    Adds a bright highlight to pixels above a luminance threshold,
    mimicking the hard specular disc in cel shaders.
    """
    highlight = np.where(gray > threshold, boost, 0.0).astype(np.float32)
    return highlight


# ── Main effect ─────────────────────────────────────────────────────────────

def toon_shading_effect(
    img,
    exposure=1.0,
    tone_map_method='reinhard',
    num_bands=4,
    band_smoothing=0.0,
    quantize_colors=False,
    hue_bins=12,
    sat_bins=4,
    edge_method='sobel',
    edge_threshold=0.08,
    edge_thickness=1,
    outline_color=(0.0, 0.0, 0.0),
    specular=False,
    specular_threshold=0.85,
    specular_boost=0.15,
    saturation_boost=0.0,
    pre_blur_sigma=0.0,
):
    """Apply toon/cel-shading post-processing.
    
    Args:
        img:                HDR float image (H, W, 3)
        exposure:           exposure multiplier
        tone_map_method:    'reinhard', 'aces', 'gamma', or 'clamp'
        num_bands:          number of shading bands (2 = stark, 3-4 = typical, 6+ = subtle)
        band_smoothing:     smoothness of band transitions (0 = hard, 0.1 = soft)
        quantize_colors:    also quantize hue/saturation for limited-palette look
        hue_bins:           hue quantization bins (if quantize_colors=True)
        sat_bins:           saturation quantization bins
        edge_method:        'sobel', 'laplacian', or 'combined'
        edge_threshold:     edge detection sensitivity (lower = more outlines)
        edge_thickness:     outline thickness (1 = thin, 2+ = thick via dilation)
        outline_color:      RGB tuple for outlines (default: black)
        specular:           enable hard specular highlight band
        specular_threshold: luminance cutoff for specular band
        specular_boost:     brightness boost for specular highlights
        saturation_boost:   increase/decrease saturation (-1 to 1)
        pre_blur_sigma:     Gaussian blur before processing (smooths noise from MC renders)

    Returns:
        Float RGB image (H, W, 3) in [0, 1]
    """
    h, w = img.shape[:2]

    # 1) Tone map HDR → [0, 1]
    ldr = tone_map(img[:, :, :3], exposure=exposure, method=tone_map_method)

    # Optional pre-blur to smooth Monte Carlo noise
    if pre_blur_sigma > 0:
        ldr = gaussian_blur(ldr, sigma=pre_blur_sigma)

    # 2) Compute grayscale for luminance-based operations
    gray = to_grayscale(ldr)

    # 3) Edge detection → binary outlines
    edges = detect_edges(gray, method=edge_method, threshold=edge_threshold)

    # Thicken edges via dilation if requested
    if edge_thickness > 1:
        from image_io import convolve2d
        dilation_kernel = np.ones((edge_thickness * 2 + 1, edge_thickness * 2 + 1), dtype=np.float32)
        edges = (convolve2d(edges, dilation_kernel) > 0.5).astype(np.float32)

    # 4) Quantize luminance into shading bands
    quant_gray = quantize_luminance(gray, num_bands=num_bands, smoothing=band_smoothing)

    # 5) Apply quantized luminance to the original color
    #    Strategy: scale each pixel's color by (quantized_lum / original_lum)
    #    This preserves hue while applying the cel shading bands.
    gray_safe = np.maximum(gray, 1e-6)
    lum_ratio = (quant_gray / gray_safe)[:, :, np.newaxis]
    result = ldr * lum_ratio
    result = np.clip(result, 0, 1).astype(np.float32)

    # 6) Optional color quantization
    if quantize_colors:
        result = quantize_color(result, hue_bins=hue_bins, sat_bins=sat_bins, val_bins=num_bands)

    # 7) Optional saturation boost
    if saturation_boost != 0:
        hsv = rgb_to_hsv(result)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] + saturation_boost, 0, 1)
        result = hsv_to_rgb(hsv)

    # 8) Specular highlight band
    if specular:
        highlight = specular_band(gray, threshold=specular_threshold, boost=specular_boost)
        result = np.clip(result + highlight[:, :, np.newaxis], 0, 1)

    # 9) Composite outlines
    outline = np.array(outline_color, dtype=np.float32).reshape(1, 1, 3)
    edge_mask = edges[:, :, np.newaxis]
    result = result * (1 - edge_mask) + outline * edge_mask
    result = np.clip(result, 0, 1).astype(np.float32)

    return result
