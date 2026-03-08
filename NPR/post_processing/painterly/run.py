#!/usr/bin/env python3
"""
CLI for painterly rendering post-processing on lajolla renders.

Usage:
    # Litwinowicz '97 impressionist (default)
    python run.py path/to/render.exr -o impressionist.png

    # Litwinowicz with longer strokes, thicker brush
    python run.py render.exr -o imp.png --stroke-length 15 --brush-radius 3

    # Oil painting (Kuwahara-based, legacy)
    python run.py render.exr -o oil.png --style oil

    # Watercolor style (Kuwahara-based)
    python run.py render.exr -o watercolor.png --style watercolor
"""

import argparse
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from image_io import read_image, write_image
from painterly import painterly_effect


def main():
    parser = argparse.ArgumentParser(
        description='Painterly Rendering Post-Processing for lajolla renders',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('input', nargs='+', help='Input image(s)')
    parser.add_argument('-o', '--output', help='Output path')

    g = parser.add_argument_group('Style')
    g.add_argument('--style',             choices=['litwinowicz', 'oil', 'watercolor', 'impressionist'],
                   default='litwinowicz',
                   help="'litwinowicz' = Litwinowicz '97 stroke rendering (default); "
                        "'oil/watercolor/impressionist' = Kuwahara-based")

    g2 = parser.add_argument_group('Litwinowicz parameters')
    g2.add_argument('--grid-spacing',     type=int,   default=4,
                    help='Pixel distance between stroke centres (smaller=denser)')
    g2.add_argument('--stroke-length',    type=int,   default=10,
                    help='Half-length of each brush stroke in pixels')
    g2.add_argument('--brush-radius',     type=int,   default=2,
                    help='Radius of circular brush tip (pixels)')
    g2.add_argument('--jitter',           type=float, default=0.8,
                    help='Random offset per grid point (fraction of spacing)')
    g2.add_argument('--no-edge-clip',     action='store_true',
                    help='Disable edge clipping (strokes will bleed across edges)')
    g2.add_argument('--canny-low',        type=int,   default=50)
    g2.add_argument('--canny-high',       type=int,   default=150)
    g2.add_argument('--seed',             type=int,   default=42)

    g3 = parser.add_argument_group('Kuwahara parameters (oil/watercolor/impressionist)')
    g3.add_argument('--kuwahara-radius',  type=int,   default=4)
    g3.add_argument('--palette-method',   choices=['uniform', 'kmeans', 'none'], default='uniform')
    g3.add_argument('--num-colors',       type=int,   default=16)
    g3.add_argument('--stroke-strength',  type=float, default=0.15)
    g3.add_argument('--stroke-scale',     type=int,   default=8)
    g3.add_argument('--edge-darken',      type=float, default=0.3)
    g3.add_argument('--edge-threshold',   type=float, default=0.05)

    g4 = parser.add_argument_group('Common parameters')
    g4.add_argument('--exposure',         type=float, default=1.0)
    g4.add_argument('--tone-map',         choices=['reinhard', 'aces', 'gamma', 'clamp'], default='reinhard')
    g4.add_argument('--canvas-strength',  type=float, default=0.05,
                    help='Canvas/paper texture strength (0=off)')
    g4.add_argument('--pre-blur',         type=float, default=0.5)
    g4.add_argument('--saturation-boost', type=float, default=0.1)

    args = parser.parse_args()

    if len(args.input) > 1 and args.output:
        parser.error("--output cannot be used with multiple input files")

    for input_path in args.input:
        if not Path(input_path).exists():
            print(f"Error: '{input_path}' not found", file=sys.stderr)
            continue

        output_path = args.output or str(Path(input_path).parent / f"{Path(input_path).stem}_painterly.png")

        print(f"Reading {input_path} ...")
        img = read_image(input_path)
        print(f"  Image size: {img.shape[1]}×{img.shape[0]}, range: [{img.min():.3f}, {img.max():.3f}]")
        print(f"  Applying painterly effect (style={args.style}) ...")

        result = painterly_effect(
            img,
            exposure=args.exposure,
            tone_map_method=args.tone_map,
            style=args.style,
            # Kuwahara params
            kuwahara_radius=args.kuwahara_radius,
            palette_method=args.palette_method,
            num_colors=args.num_colors,
            stroke_strength=args.stroke_strength,
            stroke_scale=args.stroke_scale,
            edge_darken=args.edge_darken,
            edge_threshold=args.edge_threshold,
            # Litwinowicz params
            grid_spacing=args.grid_spacing,
            stroke_length=args.stroke_length,
            brush_radius=args.brush_radius,
            jitter=args.jitter,
            edge_clip=not args.no_edge_clip,
            canny_low=args.canny_low,
            canny_high=args.canny_high,
            seed=args.seed,
            # Common
            canvas_strength=args.canvas_strength,
            pre_blur_sigma=args.pre_blur,
            saturation_boost=args.saturation_boost,
        )

        write_image(output_path, result)
        print(f"  Saved → {output_path}")

    print("Done.")


if __name__ == '__main__':
    main()
