#!/usr/bin/env python3
"""
animate_transition.py — PBR → Cel-shading transition with camera orbit
======================================================================
Renders N frames of the Cornell Box with the two pillars transitioning
from PBR to cel-shaded style via the West 2024 stylized integrator.

The camera simultaneously waves left/right (sinusoidal orbit) to
demonstrate full 3D integration — not a 2D post-process.

Run from the workspace root (lajolla_public/):
    python3 final_project/animate_transition.py [OPTIONS]

Options:
  --scene      Source scene XML  (default: scenes/cbox/cbox_transition.xml)
  --frames N   Number of frames  (default: 60)
  --fps N      GIF playback FPS  (default: 15)
  --output     Output GIF/MP4    (default: transition.gif)
  --frames-dir Intermediate dir  (default: /tmp/transition_frames)
  --orbit DEG  Camera wave arc   (default: 30)
  --gamma F    Display gamma     (default: 2.2)
"""

import argparse
import math
import os
import re
import subprocess
import sys

import numpy as np

try:
    import imageio.v2 as imageio
except ImportError:
    try:
        import imageio
    except ImportError:
        sys.exit("imageio is required: pip install imageio")

# ── Import EXR reader from sibling module ────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from sobel_post import read_exr


# ── Path absolutisation (same as animate_npr.py) ─────────────────────────────
_FILE_EXT_RE = re.compile(
    r'value="((?!\d)(?:[^"/]*[/\\])?[^"]+\.'
    r'(?:obj|xml|exr|hdr|png|jpg|jpeg|pfm|vol|vdb))"',
    re.IGNORECASE
)

def _absolutize_paths(xml: str, scene_dir: str) -> str:
    def _abs(m):
        val = m.group(1)
        if os.path.isabs(val):
            return m.group(0)
        return f'value="{os.path.abspath(os.path.join(scene_dir, val))}"'
    return _FILE_EXT_RE.sub(_abs, xml)


# ── Cornell Box geometry constants ───────────────────────────────────────────
_TARGET = (278.0, 273.0, 280.0)   # look-at target (box center)
_ORIGIN = (278.0, 273.0, -800.0)  # default camera origin


def _orbit_origin(frame: int, n_frames: int, orbit_deg: float):
    """Compute camera origin for a sinusoidal left/right wave.

    The camera sweeps ±orbit_deg around the vertical axis centred on _TARGET,
    completing one full wave (sin cycle) over all frames.
    """
    tx, ty, tz = _TARGET
    ox, oy, oz = _ORIGIN
    dx, dz = ox - tx, oz - tz
    r_xz = math.sqrt(dx ** 2 + dz ** 2)
    az_base = math.atan2(dx, -dz)

    # Sinusoidal sweep: frame 0 → centre, peaks at 1/4 and 3/4
    phase = 2.0 * math.pi * frame / max(n_frames, 1)
    az = az_base + math.radians(orbit_deg) * math.sin(phase)

    new_x = tx + r_xz * math.sin(az)
    new_z = tz - r_xz * math.cos(az)
    return (float(new_x), float(oy), float(new_z))


# ── XML patching ─────────────────────────────────────────────────────────────

def _patch_transition_t(xml: str, t: float) -> str:
    """Replace the transition_t value in the XML."""
    return re.sub(
        r'(<float\s+name="transition_t"\s+value=")[^"]*(")',
        rf'\g<1>{t:.6f}\2',
        xml, count=1
    )

def _patch_lookat(xml: str, origin: tuple) -> str:
    """Replace the <lookAt .../> with a new camera origin."""
    ox, oy, oz = origin
    tx, ty, tz = _TARGET
    new_lookat = (
        f'<lookAt origin="{ox:.2f}, {oy:.2f}, {oz:.2f}"'
        f' target="{tx:.2f}, {ty:.2f}, {tz:.2f}"'
        f' up="0, 1, 0"/>'
    )
    return re.sub(r'<lookAt\b[^/]*/>', new_lookat, xml,
                  count=1, flags=re.DOTALL)

def _patch_output_filename(xml: str, out_path: str) -> str:
    """Insert or replace an output filename in the <film> block."""
    abs_out = os.path.abspath(out_path)
    fname_tag = f'<string name="filename" value="{abs_out}"/>'

    def _patch_film(m):
        block = m.group(0)
        if re.search(r'<string\s+name="filename"', block):
            return re.sub(
                r'<string\s+name="filename"\s+value="[^"]*"\s*/>',
                fname_tag, block, count=1
            )
        return re.sub(r'(</film>)',
                      f'\t\t\t{fname_tag}\n\t\t\\1',
                      block, count=1)

    return re.sub(r'<film\b[^>]*>.*?</film>', _patch_film, xml,
                  count=1, flags=re.DOTALL)


# ── EXR → uint8 ─────────────────────────────────────────────────────────────

def _exr_to_uint8(path: str, gamma: float) -> np.ndarray:
    img = read_exr(path)
    img = np.clip(img, 0.0, 1.0)
    img = img ** (1.0 / gamma)
    return (img * 255.0 + 0.5).astype(np.uint8)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('--scene',      default='scenes/cbox/cbox_transition.xml')
    ap.add_argument('--frames',     type=int,   default=60)
    ap.add_argument('--fps',        type=int,   default=15)
    ap.add_argument('--output',     default='transition.gif')
    ap.add_argument('--frames-dir', default='/tmp/transition_frames')
    ap.add_argument('--orbit',      type=float, default=30.0,
                    help='Camera wave arc in degrees (default 30)')
    ap.add_argument('--gamma',      type=float, default=2.2)
    args = ap.parse_args()

    lajolla_bin = os.path.join('build', 'lajolla')
    if not os.path.isfile(lajolla_bin):
        sys.exit(f"Renderer not found: {lajolla_bin}\n"
                 "  Run from workspace root after building.")
    if not os.path.isfile(args.scene):
        sys.exit(f"Scene file not found: {args.scene}")

    os.makedirs(args.frames_dir, exist_ok=True)

    scene_dir = os.path.dirname(os.path.abspath(args.scene))
    with open(args.scene) as fh:
        src_xml = fh.read()

    # Absolutize mesh paths so temp XMLs work from any directory
    src_xml = _absolutize_paths(src_xml, scene_dir)

    n = args.frames
    gif_frames = []

    print(f"Rendering {n} frames (t: 0→1, ±{args.orbit:.0f}° orbit, {args.fps} fps) …\n")

    for i in range(n):
        t = i / max(n - 1, 1)
        origin = _orbit_origin(i, n, args.orbit)
        tag = f'frame_{i:04d}'
        exr = os.path.join(args.frames_dir, f'{tag}.exr')
        tmp_xml = os.path.join(args.frames_dir, f'{tag}.xml')

        print(f"  [{i+1:3d}/{n}]  t={t:.4f}  az={origin[0]-278:.0f}",
              end='  ', flush=True)

        # Patch XML: update transition_t, camera, and output filename
        frame_xml = _patch_transition_t(src_xml, t)
        frame_xml = _patch_lookat(frame_xml, origin)
        frame_xml = _patch_output_filename(frame_xml, exr)

        with open(tmp_xml, 'w') as fh:
            fh.write(frame_xml)

        # Render
        result = subprocess.run(
            [lajolla_bin, tmp_xml],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"RENDER ERROR:\n{result.stderr[:400]}")
            continue
        if not os.path.isfile(exr):
            print(f"Warning: expected output not found: {exr}")
            continue

        # Convert to uint8
        gif_frames.append(_exr_to_uint8(exr, args.gamma))
        print("done")

    if not gif_frames:
        sys.exit("No frames rendered successfully.")

    # Assemble GIF
    print(f"\nAssembling {len(gif_frames)} frames → {args.output} …")
    imageio.mimsave(args.output, gif_frames, fps=args.fps, loop=0)
    print(f"Done!  Saved: {args.output}")


if __name__ == '__main__':
    main()
