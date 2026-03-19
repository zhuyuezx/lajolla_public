#!/usr/bin/env python3
"""
Animate the Sculpture Garden with a MOVING LIGHT SOURCE.

The area light sweeps in a semicircular arc:
  Frame 0:   far left,  low  (grazing angle from the left)
  Frame N/2: overhead,   high (top-down illumination)
  Frame N:   far right,  low  (grazing angle from the right)

Camera stays fixed so the lighting change is the star of the show.
transition_t is held at 1.0 (fully stylized) throughout.

Usage:
    python3 final_project/animate_gallery.py \
        --scene scenes/gallery/scene.xml \
        --frames 60 --fps 15 --output gallery.gif
"""

import argparse, math, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--output", default="gallery.gif")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    lajolla = root / "build" / "lajolla"
    if not lajolla.exists():
        sys.exit(f"Error: {lajolla} not found. Build first.")

    scene_path = Path(args.scene).resolve()
    scene_text = scene_path.read_text()
    scene_dir  = scene_path.parent  # meshes are relative to this!

    # Temp directory for PNG frames (NOT for XMLs — those go in scene_dir)
    tmpdir = tempfile.mkdtemp(prefix="gallery_")
    frame_paths = []

    # Light sweep arc: always stays above camera (y=12) so it's invisible.
    # Sweeps from far-left grazing to overhead to far-right grazing.
    light_arc_radius = 25.0   # horizontal sweep range
    light_min_y   = 30.0      # height at grazing (above camera y=12, never visible)
    light_max_y   = 55.0      # height at zenith (directly overhead)
    light_z       = 10.0      # behind camera (camera at z=20 looking toward z≈-2)

    print(f"Rendering {args.frames} frames (light sweep: left→top→right, {args.fps} fps) …\n")

    for i in range(args.frames):
        frac = i / max(args.frames - 1, 1)
        arc_angle = math.pi * frac   # 0..π

        light_x = -light_arc_radius * math.cos(arc_angle)
        light_y = light_min_y + (light_max_y - light_min_y) * math.sin(arc_angle)

        # Patch the area light's <translate> (first occurrence only)
        txt = re.sub(
            r'(<translate\s+x=")[^"]*("\s+y=")[^"]*("\s+z=")[^"]*("/)',
            rf'\g<1>{light_x:.1f}\g<2>{light_y:.1f}\g<3>{light_z:.1f}\g<4>',
            scene_text, count=1)

        # Write temp XML in the SCENE DIRECTORY so mesh paths resolve!
        frame_xml = scene_dir / f"_tmp_frame_{i:04d}.xml"
        frame_xml.write_text(txt)

        subprocess.run([str(lajolla), str(frame_xml)],
                       capture_output=True, cwd=str(root))

        src_exr = root / "image.exr"
        dst_png = os.path.join(tmpdir, f"frame_{i:04d}.png")

        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-apply_trc", "iec61966_2_1",
             "-i", str(src_exr), dst_png],
            capture_output=True)

        if os.path.exists(dst_png):
            frame_paths.append(dst_png)

        # Clean up temp XML immediately
        frame_xml.unlink(missing_ok=True)

        print(f"  [{i+1:3d}/{args.frames}]  x={light_x:+6.1f}  y={light_y:5.1f}  done")

    if not frame_paths:
        sys.exit("No frames rendered!")

    out_path = str(root / args.output)
    print(f"\nAssembling {len(frame_paths)} frames → {args.output} …")

    palette_path = os.path.join(tmpdir, "palette.png")
    input_pattern = os.path.join(tmpdir, "frame_%04d.png")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-framerate", str(args.fps),
         "-i", input_pattern,
         "-vf", "palettegen=stats_mode=diff",
         palette_path],
        check=True)

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-framerate", str(args.fps),
         "-i", input_pattern,
         "-i", palette_path,
         "-lavfi", "paletteuse=dither=bayer:bayer_scale=3",
         "-loop", "0",
         out_path],
        check=True)

    print(f"Done!  Saved: {args.output}")
    shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    main()
