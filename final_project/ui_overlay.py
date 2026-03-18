#!/usr/bin/env python3
"""
ui_overlay.py — Game UI overlay compositing for NPR renders
============================================================
Composites 2D game-UI elements (health bar, inventory slots, mini-map)
on top of an outlined NPR render.  Runs AFTER sobel_post.py has produced
the *_outlined.exr image.

This script draws directly on the float-RGB buffer using numpy, so it
needs no extra dependencies beyond numpy and the EXR I/O helpers already
used by sobel_post.py.

Two compositing strategies are supported:

  1. OVERLAY (default) — draw UI as opaque coloured rectangles / shapes
     directly onto the final EXR.  Best for static screenshots.

  2. ALPHA — write the UI layer as a separate RGBA EXR that can be
     composited in any external tool or game engine HUD pipeline.

Usage:
    python3 ui_overlay.py  image_outlined.exr  [-o output.exr]
                           [--strategy overlay|alpha]
                           [--health 0.75]
                           [--inventory 4]

Dependencies:  numpy, OpenEXR (or imageio with freeimage plugin)

Design note
-----------
In a real game loop you would render the UI as flat 3D quads locked to
the camera frustum (billboards at near-plane distance).  For this offline
NPR pipeline the post-process approach is simpler and keeps the C++
renderer untouched.  If you want in-scene UI quads instead:

  1. Create thin OBJ planes at the camera's near-clip distance.
  2. Assign them a unique material id (e.g. `bsdf type="diffuse" id="ui_hp"`).
  3. In the NPR integrator, detect those material ids and skip shadow /
     cel logic — write the flat albedo colour directly.
  4. In sobel_post.py, mask out UI-material object-IDs from edge detection
     so no outlines appear across the UI surface.
"""

import argparse
import os
import sys

import numpy as np

# ── Import sibling EXR I/O ───────────────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from sobel_post import read_exr, write_exr


# ─────────────────────────────────────────────────────────────────────────────
# Primitive drawing helpers (operates on float H×W×3 arrays)
# ─────────────────────────────────────────────────────────────────────────────

def _rect(img, x0, y0, x1, y1, color, alpha=1.0):
    """Draw a filled rectangle with optional alpha blending."""
    h, w = img.shape[:2]
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    c = np.array(color, dtype=np.float32)
    if alpha >= 1.0:
        img[y0:y1, x0:x1] = c
    else:
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - alpha) + c * alpha


def _rect_outline(img, x0, y0, x1, y1, color, thickness=2):
    """Draw a rectangle outline (border only)."""
    _rect(img, x0, y0, x1, y0 + thickness, color)  # top
    _rect(img, x0, y1 - thickness, x1, y1, color)  # bottom
    _rect(img, x0, y0, x0 + thickness, y1, color)  # left
    _rect(img, x1 - thickness, y0, x1, y1, color)  # right


# ─────────────────────────────────────────────────────────────────────────────
# UI components
# ─────────────────────────────────────────────────────────────────────────────

# Colours (linear sRGB, will look correct after the usual gamma pass)
COL_HP_BG     = (0.15, 0.15, 0.18)     # dark panel background
COL_HP_FILL   = (0.28, 0.82, 0.40)     # green health fill
COL_HP_DAMAGE = (0.85, 0.22, 0.22)     # red missing-health
COL_HP_BORDER = (0.95, 0.92, 0.85)     # light border
COL_INV_BG    = (0.12, 0.12, 0.15)     # inventory slot background
COL_INV_ITEM  = (0.90, 0.75, 0.35)     # gold item placeholder
COL_INV_BORDER = (0.80, 0.78, 0.70)    # inventory border
COL_MINIMAP_BG = (0.10, 0.18, 0.10)    # dark green minimap bg
COL_MINIMAP_DOT = (1.0, 0.35, 0.35)    # red player dot
COL_MINIMAP_BORDER = (0.90, 0.88, 0.80)


def draw_health_bar(img, health_frac=0.75):
    """Draw a health bar in the top-left corner."""
    h, w = img.shape[:2]
    margin = int(w * 0.025)
    bar_w = int(w * 0.25)
    bar_h = int(h * 0.035)
    x0, y0 = margin, margin

    # Background / damage bar
    _rect(img, x0, y0, x0 + bar_w, y0 + bar_h, COL_HP_DAMAGE, alpha=0.85)
    # Health fill
    fill_w = int(bar_w * max(0, min(1, health_frac)))
    _rect(img, x0, y0, x0 + fill_w, y0 + bar_h, COL_HP_FILL, alpha=0.90)
    # Border
    _rect_outline(img, x0, y0, x0 + bar_w, y0 + bar_h, COL_HP_BORDER, thickness=2)


def draw_inventory(img, n_slots=4, n_filled=2):
    """Draw inventory slots along the bottom-center."""
    h, w = img.shape[:2]
    slot_sz = int(min(w, h) * 0.065)
    gap = int(slot_sz * 0.20)
    total_w = n_slots * slot_sz + (n_slots - 1) * gap
    x_start = (w - total_w) // 2
    y0 = h - int(h * 0.03) - slot_sz

    for i in range(n_slots):
        sx = x_start + i * (slot_sz + gap)
        # Slot background
        _rect(img, sx, y0, sx + slot_sz, y0 + slot_sz, COL_INV_BG, alpha=0.80)
        # Item placeholder in filled slots
        if i < n_filled:
            inset = int(slot_sz * 0.22)
            _rect(img, sx + inset, y0 + inset,
                  sx + slot_sz - inset, y0 + slot_sz - inset,
                  COL_INV_ITEM, alpha=0.90)
        # Border
        _rect_outline(img, sx, y0, sx + slot_sz, y0 + slot_sz,
                      COL_INV_BORDER, thickness=2)


def draw_minimap(img):
    """Draw a small mini-map square in the bottom-right corner."""
    h, w = img.shape[:2]
    mm_sz = int(min(w, h) * 0.15)
    margin = int(w * 0.025)
    x0 = w - margin - mm_sz
    y0 = h - margin - mm_sz

    # Background
    _rect(img, x0, y0, x0 + mm_sz, y0 + mm_sz, COL_MINIMAP_BG, alpha=0.75)
    # Player dot (center)
    dot = max(3, int(mm_sz * 0.06))
    cx, cy = x0 + mm_sz // 2, y0 + mm_sz // 2
    _rect(img, cx - dot, cy - dot, cx + dot, cy + dot, COL_MINIMAP_DOT)
    # Border
    _rect_outline(img, x0, y0, x0 + mm_sz, y0 + mm_sz,
                  COL_MINIMAP_BORDER, thickness=2)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def overlay_ui(input_path, output_path=None,
               health=0.75, n_inventory=4, strategy='overlay'):
    """Load an outlined EXR, draw game UI on top, save result."""
    img = read_exr(input_path).copy()

    if strategy == 'alpha':
        # Write a separate RGBA UI-only layer (transparent background)
        h, w = img.shape[:2]
        ui_layer = np.zeros((h, w, 3), dtype=np.float32)
        draw_health_bar(ui_layer, health)
        draw_inventory(ui_layer, n_inventory, n_filled=min(2, n_inventory))
        draw_minimap(ui_layer)
        out = output_path or input_path.replace('.exr', '_ui_layer.exr')
        write_exr(out, ui_layer)
        print(f'[ui_overlay] UI-only alpha layer written → {out}')
        print(f'             Composite over the render in any image editor.')
        return ui_layer

    # Default: direct overlay onto the render
    draw_health_bar(img, health)
    draw_inventory(img, n_inventory, n_filled=min(2, n_inventory))
    draw_minimap(img)

    out = output_path or input_path.replace('.exr', '_ui.exr')
    write_exr(out, img)
    print(f'[ui_overlay] Composited game UI → {out}')
    return img


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Composite 2D game-UI elements over an NPR render")
    p.add_argument("input_exr",
                   help="Path to the outlined EXR render")
    p.add_argument("-o", "--output", default=None,
                   help="Output filename (default: <stem>_ui.exr)")
    p.add_argument("--strategy", choices=['overlay', 'alpha'],
                   default='overlay',
                   help="'overlay' draws directly; 'alpha' writes a "
                        "separate compositing layer")
    p.add_argument("--health", type=float, default=0.75,
                   help="Health bar fill fraction 0–1 (default 0.75)")
    p.add_argument("--inventory", type=int, default=4,
                   help="Number of inventory slots (default 4)")
    args = p.parse_args()

    overlay_ui(
        args.input_exr,
        output_path=args.output,
        health=args.health,
        n_inventory=args.inventory,
        strategy=args.strategy,
    )


if __name__ == "__main__":
    main()
