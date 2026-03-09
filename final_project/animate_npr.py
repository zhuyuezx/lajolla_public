#!/usr/bin/env python3
"""
animate_npr.py  –  Camera-orbit animation for the La Jolla NPR pipeline
========================================================================
Renders N frames with the camera orbiting horizontally around the Cornell
Box, applies Sobel outlines to each frame, then assembles an animated GIF.

Run from the workspace root (lajolla_public/):

    python3 final_project/animate_npr.py [OPTIONS]

Options
-------
  --scene        Source scene XML        (default: scenes/npr_cbox/scene.xml)
  --frames  N    Number of frames        (default: 36)
  --orbit   DEG  Total arc, degrees      (default: 360)
  --fps     N    GIF playback FPS        (default: 10)
  --output  PATH Output animated GIF     (default: animation.gif)
  --frames-dir D Intermediate EXR dir   (default: /tmp/npr_frames)
  --no-outline   Skip Sobel; use raw colour
  --depth-thresh F   Sobel depth threshold  (default: 0.10)
  --normal-thresh F  Sobel normal threshold (default: 0.50)
  --gamma F      Gamma exponent for GIF   (default: 2.2)
"""

import argparse, math, os, re, subprocess, sys
import numpy as np

# ── Import helpers from sibling Sobel module ─────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)
from sobel_post import run_sobel_pass, read_exr

try:
    import imageio
except ImportError:
    sys.exit("imageio is required: pip install imageio")

# ─── Scene geometry constants ─────────────────────────────────────────────────
# These match the Cornell Box center and the default camera position in the
# NPR scene.  Adjust if your scene differs.
_TARGET = (278.0, 274.0, 280.0)   # look-at target (box center)
_ORIGIN = (700.0, 650.0, -400.0)  # default camera origin


# ─── Camera orbit helpers ─────────────────────────────────────────────────────

def _orbit_origins(n_frames: int, orbit_deg: float):
    """Yield (x, y, z) camera origins spaced evenly along a horizontal orbit.

    The orbit keeps the camera at the same elevation as the default origin,
    sweeping `orbit_deg` degrees around the vertical axis centred on _TARGET.
    """
    tx, ty, tz = _TARGET
    ox, oy, oz = _ORIGIN
    dx, dy, dz = ox - tx, oy - ty, oz - tz          # default offset from target
    r_xz       = math.sqrt(dx ** 2 + dz ** 2)       # horizontal radius
    az_start   = math.atan2(dx, -dz)                # starting azimuth

    for i in range(n_frames):
        angle = az_start + math.radians(orbit_deg * i / n_frames)
        new_x = tx + r_xz *  math.sin(angle)
        new_z = tz - r_xz *  math.cos(angle)
        new_y = ty + dy                              # constant height
        yield float(new_x), float(new_y), float(new_z)


# ─── XML patching ─────────────────────────────────────────────────────────────

# File extensions that appear as relative paths in scene XMLs.
_FILE_EXT_RE = re.compile(
    r'value="((?!\d)(?:[^"/]*[/\\])?[^"]+\.'
    r'(?:obj|xml|exr|hdr|png|jpg|jpeg|pfm|vol|vdb))"',
    re.IGNORECASE
)

def _absolutize_paths(xml: str, scene_dir: str) -> str:
    """Replace every relative file path in XML value="" attrs with an absolute path."""
    def _abs(m):
        val = m.group(1)
        if os.path.isabs(val):
            return m.group(0)
        return f'value="{os.path.abspath(os.path.join(scene_dir, val))}"'
    return _FILE_EXT_RE.sub(_abs, xml)


def _make_frame_xml(src_xml: str, scene_dir: str,
                    origin: tuple, out_exr: str) -> str:
    """Return `src_xml` with absolute paths, updated camera, and output filename."""
    # 1. Make all relative mesh/texture paths absolute so the temp XML can live
    #    anywhere on disk without breaking path resolution.
    xml = _absolutize_paths(src_xml, scene_dir)

    ox, oy, oz = origin
    tx, ty, tz = _TARGET

    # 2. Replace the <lookAt .../> element (single-line or multi-line)
    new_lookat = (
        f'<lookAt origin="{ox:.2f}, {oy:.2f}, {oz:.2f}"\n'
        f'                    target="{tx:.2f}, {ty:.2f}, {tz:.2f}"\n'
        f'                    up="0, 1, 0"/>'
    )
    xml = re.sub(r'<lookAt\b[^/]*/>', new_lookat, xml,
                 count=1, flags=re.DOTALL)

    # 3. Set the output filename *within the <film> block only* — important
    #    because mesh shapes also use <string name="filename" .../> and we
    #    must not accidentally replace those.
    abs_out  = os.path.abspath(out_exr)
    fname_tag = f'<string name="filename" value="{abs_out}"/>'

    def _patch_film(m):
        block = m.group(0)
        if re.search(r'<string\s+name="filename"', block):
            return re.sub(
                r'<string\s+name="filename"\s+value="[^"]*"\s*/>',
                fname_tag, block, count=1
            )
        # Film block has no filename yet — insert just before </film>
        return re.sub(r'(</film>)',
                      f'            {fname_tag}\n        \\1',
                      block, count=1)

    xml = re.sub(r'<film\b[^>]*>.*?</film>', _patch_film, xml,
                 count=1, flags=re.DOTALL)
    return xml


# ─── EXR → uint8 conversion ───────────────────────────────────────────────────

def _exr_to_uint8(path: str, gamma: float) -> np.ndarray:
    """Load a linear-float EXR and return a gamma-corrected sRGB uint8 array."""
    img = read_exr(path)                          # float32 H×W×3
    img = np.clip(img, 0.0, 1.0)
    img = img ** (1.0 / gamma)                    # linear → display gamma
    return (img * 255.0 + 0.5).astype(np.uint8)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('--scene',         default='scenes/npr_cbox/scene.xml',
                    help='Source scene XML')
    ap.add_argument('--frames',        type=int,   default=36,
                    help='Number of frames')
    ap.add_argument('--orbit',         type=float, default=360.0,
                    help='Total arc in degrees (default 360 = full circle)')
    ap.add_argument('--fps',           type=int,   default=10,
                    help='GIF playback speed (frames per second)')
    ap.add_argument('--output',        default='animation.gif',
                    help='Output animated GIF path')
    ap.add_argument('--frames-dir',    default='/tmp/npr_frames',
                    help='Directory for intermediate EXR frames')
    ap.add_argument('--no-outline',    action='store_true',
                    help='Skip Sobel outline pass')
    ap.add_argument('--depth-thresh',  type=float, default=0.10,
                    help='Sobel depth discontinuity threshold')
    ap.add_argument('--normal-thresh', type=float, default=0.50,
                    help='Sobel normal discontinuity threshold')
    ap.add_argument('--gamma',         type=float, default=2.2,
                    help='Display gamma for GIF conversion')
    args = ap.parse_args()

    # ── Sanity checks ────────────────────────────────────────────────────────
    lajolla_bin = os.path.join('build', 'lajolla')
    if not os.path.isfile(lajolla_bin):
        sys.exit(
            f"Renderer not found: {lajolla_bin}\n"
            "  Run this script from the workspace root after building."
        )
    if not os.path.isfile(args.scene):
        sys.exit(f"Scene file not found: {args.scene}")

    os.makedirs(args.frames_dir, exist_ok=True)

    # ── Read source XML once ─────────────────────────────────────────────────
    scene_dir = os.path.dirname(os.path.abspath(args.scene))
    with open(args.scene) as fh:
        src_xml = fh.read()

    origins = list(_orbit_origins(args.frames, args.orbit))
    gif_frames = []
    n = len(origins)

    print(f"Rendering {n} frames "
          f"({args.orbit:.0f}° orbit, {args.fps} fps) …\n")

    for i, origin in enumerate(origins):
        tag     = f'frame_{i:04d}'
        exr     = os.path.join(args.frames_dir, f'{tag}.exr')
        tmp_xml = os.path.join(args.frames_dir, f'{tag}.xml')

        print(f"  [{i+1:3d}/{n}]  "
              f"origin=({origin[0]:6.0f}, {origin[1]:6.0f}, {origin[2]:6.0f})",
              end='  ', flush=True)

        # ── Patch XML and write temp file ────────────────────────────────────
        frame_xml = _make_frame_xml(src_xml, scene_dir, origin, exr)
        with open(tmp_xml, 'w') as fh:
            fh.write(frame_xml)

        # ── Render ───────────────────────────────────────────────────────────
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

        # ── Sobel outline pass ────────────────────────────────────────────────
        if not args.no_outline:
            run_sobel_pass(
                exr,
                depth_thresh  = args.depth_thresh,
                normal_thresh = args.normal_thresh,
            )
            display_exr = exr.replace('.exr', '_outlined.exr')
        else:
            display_exr = exr

        if not os.path.isfile(display_exr):
            print(f"Warning: display EXR missing: {display_exr}")
            continue

        # ── Convert to uint8 and collect ─────────────────────────────────────
        gif_frames.append(_exr_to_uint8(display_exr, args.gamma))
        print("done")

    if not gif_frames:
        sys.exit("No frames rendered successfully.")

    # ── Assemble GIF ─────────────────────────────────────────────────────────
    print(f"\nAssembling {len(gif_frames)} frames → {args.output} …")
    imageio.mimsave(args.output, gif_frames, fps=args.fps, loop=0)
    print(f"Done!  Saved: {args.output}")


if __name__ == '__main__':
    main()
