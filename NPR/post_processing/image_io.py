"""
Shared image I/O and processing utilities for all NPR post-processing effects.
Lives at the post_processing/ level so every subfolder can import it.

Usage from any subfolder:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from image_io import read_image, write_image, tone_map, to_grayscale
"""

import os
os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')

import numpy as np
from pathlib import Path


# ── Reading ──────────────────────────────────────────────────────────────────

def read_image(filepath):
    """Read an image file and return as float32 numpy array (H, W, 3) in RGB order."""
    filepath = str(filepath)
    errors = []

    try:
        import cv2
        img = cv2.imread(filepath, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if img is not None:
            orig_dtype = img.dtype
            if len(img.shape) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            elif len(img.shape) == 2:
                img = np.stack([img] * 3, axis=-1)
            img = img.astype(np.float32)
            # Normalize integer-sourced (LDR) images to [0, 1]
            if orig_dtype == np.uint8:
                img /= 255.0
            elif orig_dtype == np.uint16:
                img /= 65535.0
            return img
        errors.append("cv2: imread returned None")
    except ImportError:
        errors.append("cv2: not installed")
    except Exception as e:
        errors.append(f"cv2: {e}")

    try:
        import pyexr
        img = pyexr.read(filepath).astype(np.float32)
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=-1)
        return img[:, :, :3]
    except ImportError:
        errors.append("pyexr: not installed")
    except Exception as e:
        errors.append(f"pyexr: {e}")

    try:
        import imageio.v3 as iio
        img = iio.imread(filepath).astype(np.float32)
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=-1)
        return img[:, :, :3]
    except ImportError:
        errors.append("imageio: not installed")
    except Exception as e:
        errors.append(f"imageio: {e}")

    try:
        from PIL import Image
        img = np.array(Image.open(filepath).convert('RGB')).astype(np.float32) / 255.0
        return img
    except ImportError:
        errors.append("PIL: not installed")
    except Exception as e:
        errors.append(f"PIL: {e}")

    raise RuntimeError(
        f"Could not read '{filepath}'. Tried backends:\n  " + "\n  ".join(errors)
        + "\nInstall one of: opencv-python, pyexr, imageio, Pillow"
    )


# ── Writing ──────────────────────────────────────────────────────────────────

def write_image(filepath, img):
    """Write image to file. Float32 (H, W, 3) in [0, 1] for LDR."""
    filepath = str(filepath)
    img = np.asarray(img, dtype=np.float32)

    if filepath.lower().endswith(('.png', '.jpg')):
        img_uint8 = np.clip(img * 255.0, 0, 255).astype(np.uint8)
        try:
            import cv2
            out = cv2.cvtColor(img_uint8, cv2.COLOR_RGB2BGR) if img_uint8.ndim == 3 else img_uint8
            cv2.imwrite(filepath, out)
            return
        except ImportError:
            pass
        try:
            from PIL import Image as PILImage
            PILImage.fromarray(img_uint8).save(filepath)
            return
        except ImportError:
            pass
        raise RuntimeError("Cannot write PNG/JPG. Install opencv-python or Pillow.")

    elif filepath.lower().endswith('.exr'):
        try:
            import cv2
            out = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.ndim == 3 else img
            cv2.imwrite(filepath, out)
            return
        except ImportError:
            pass
        raise RuntimeError("Cannot write EXR. Install opencv-python.")

    else:
        raise ValueError(f"Unsupported output format: {Path(filepath).suffix}")


# ── Tone mapping ─────────────────────────────────────────────────────────────

def tone_map_reinhard(img):
    return img / (1.0 + img)

def tone_map_aces(img):
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)

def tone_map_gamma(img, gamma=2.2):
    return np.clip(np.power(np.maximum(img, 0), 1.0 / gamma), 0, 1)

def tone_map(img, exposure=1.0, method='reinhard'):
    """Apply exposure and tone mapping. Returns values in [0, 1]."""
    img = np.maximum(img * exposure, 0)
    if method == 'reinhard':
        return tone_map_reinhard(img)
    elif method == 'aces':
        return tone_map_aces(img)
    elif method == 'gamma':
        return tone_map_gamma(img)
    elif method == 'clamp':
        return np.clip(img, 0, 1)
    else:
        raise ValueError(f"Unknown tone mapping method: {method}")


# ── Grayscale ────────────────────────────────────────────────────────────────

def to_grayscale(img):
    """Convert RGB to grayscale using Rec. 709 luminance weights."""
    if img.ndim == 2:
        return img
    return (0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]).astype(np.float32)


# ── Convolution ──────────────────────────────────────────────────────────────

def convolve2d(img, kernel):
    """2D convolution via vectorized numpy slicing. Edges are replicate-padded."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(img, ((ph, ph), (pw, pw)), mode='edge')
    result = np.zeros_like(img, dtype=np.float64)
    for i in range(kh):
        for j in range(kw):
            result += padded[i:i + img.shape[0], j:j + img.shape[1]] * kernel[i, j]
    return result.astype(np.float32)


# ── Gaussian blur ────────────────────────────────────────────────────────────

def gaussian_kernel(size, sigma):
    """Generate a 2D Gaussian kernel (normalized)."""
    ax = np.arange(-size // 2 + 1, size // 2 + 1, dtype=np.float32)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx ** 2 + yy ** 2) / (2. * sigma ** 2))
    return kernel / kernel.sum()


def gaussian_blur(img, sigma=1.0, size=None):
    """Apply Gaussian blur to a 2D or 3D image."""
    if size is None:
        size = int(np.ceil(sigma * 3)) * 2 + 1
    kern = gaussian_kernel(size, sigma)
    if img.ndim == 2:
        return convolve2d(img, kern)
    else:
        return np.stack([convolve2d(img[:, :, c], kern) for c in range(img.shape[2])], axis=-1)


# ── Edge detection ───────────────────────────────────────────────────────────

SOBEL_X = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
SOBEL_Y = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
LAPLACIAN = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)


def detect_edges(gray, method='sobel', threshold=0.1):
    """Detect edges in a grayscale image. Returns binary edge map (1.0 = edge)."""
    if method in ('sobel', 'combined'):
        gx = convolve2d(gray, SOBEL_X)
        gy = convolve2d(gray, SOBEL_Y)
        edges_sobel = np.sqrt(gx ** 2 + gy ** 2)
    if method in ('laplacian', 'combined'):
        edges_lap = np.abs(convolve2d(gray, LAPLACIAN))
    if method == 'sobel':
        edges = edges_sobel
    elif method == 'laplacian':
        edges = edges_lap
    elif method == 'combined':
        edges = np.maximum(edges_sobel, edges_lap * 0.5)
    else:
        raise ValueError(f"Unknown edge method: {method}")
    emax = edges.max()
    if emax > 0:
        edges = edges / emax
    return (edges > threshold).astype(np.float32)


def edge_strength(gray, method='sobel'):
    """Returns continuous edge strength in [0, 1] (not thresholded)."""
    if method == 'sobel':
        gx = convolve2d(gray, SOBEL_X)
        gy = convolve2d(gray, SOBEL_Y)
        edges = np.sqrt(gx ** 2 + gy ** 2)
    elif method == 'laplacian':
        edges = np.abs(convolve2d(gray, LAPLACIAN))
    else:
        gx = convolve2d(gray, SOBEL_X)
        gy = convolve2d(gray, SOBEL_Y)
        edges = np.sqrt(gx ** 2 + gy ** 2)
    emax = edges.max()
    return (edges / emax).astype(np.float32) if emax > 0 else edges.astype(np.float32)
