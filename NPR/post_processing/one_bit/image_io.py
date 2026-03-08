"""
Image I/O and basic processing utilities for NPR post-processing.
Handles HDR (EXR) input from lajolla and LDR (PNG) output.
"""

import os
os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')

import numpy as np
from pathlib import Path


def read_image(filepath):
    """Read an image file and return as float32 numpy array (H, W, 3) in RGB order.
    
    Supports EXR (lajolla output), HDR, PNG, JPG, etc.
    Tries multiple backends: cv2, pyexr, imageio, PIL.
    """
    filepath = str(filepath)
    errors = []

    # Try OpenCV (handles EXR if compiled with OpenEXR support)
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

    # Try pyexr (reliable EXR reader)
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

    # Try imageio
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

    # Try PIL (LDR only)
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


def write_image(filepath, img):
    """Write image to file. Input should be float32 (H, W, 3) in [0, 1] for LDR.
    
    For PNG output, values are clipped to [0, 1] and mapped to uint8.
    For EXR output, values are written as-is in float32.
    """
    filepath = str(filepath)
    img = np.asarray(img, dtype=np.float32)

    if filepath.lower().endswith('.png') or filepath.lower().endswith('.jpg'):
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


# --- Tone mapping ---

def tone_map_reinhard(img):
    """Reinhard tone mapping: L / (1 + L)."""
    return img / (1.0 + img)


def tone_map_aces(img):
    """ACES filmic tone mapping curve."""
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)


def tone_map_gamma(img, gamma=2.2):
    """Simple gamma correction."""
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


def to_grayscale(img):
    """Convert RGB to grayscale using Rec. 709 luminance weights."""
    if img.ndim == 2:
        return img
    return 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
