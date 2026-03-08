#!/usr/bin/env python3
"""
CLI for toon/cel-shading post-processing on lajolla renders.

Usage:
    python run.py path/to/render.exr -o toon_output.png
    python run.py render.exr -o output.png --bands 3 --edge-threshold 0.05
    python run.py render.exr -o output.png --quantize-colors --specular --pre-blur 1.0
"""

import argparse
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from image_io import read_image, write_image
from toon import toon_shading_effect


def main():
    parser = argparse.ArgumentParser(
        description='Toon/Cel-Shading Post-Processing for lajolla renders',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('input', nargs='+', help='Input image(s)')
    parser.add_argument('-o', '--output', help='Output path')

    g = parser.add_argument_group('Toon shading parameters')
    g.add_argument('--exposure',            type=float, default=1.0)
    g.add_argument('--tone-map',            choices=['reinhard', 'aces', 'gamma', 'clamp'], default='reinhard')
    g.add_argument('--bands',               type=int,   default=4,
                   help='Number of shading bands (2=stark, 4=typical)')
    g.add_argument('--band-smoothing',      type=float, default=0.0,
                   help='Band transition softness (0=hard, 0.1=soft)')
    g.add_argument('--quantize-colors',     action='store_true',
                   help='Also quantize hue/saturation')
    g.add_argument('--hue-bins',            type=int,   default=12)
    g.add_argument('--sat-bins',            type=int,   default=4)
    g.add_argument('--edge-method',         choices=['sobel', 'laplacian', 'combined'], default='sobel')
    g.add_argument('--edge-threshold',      type=float, default=0.08)
    g.add_argument('--edge-thickness',      type=int,   default=1,
                   help='Outline thickness (1=thin, 2+=thick)')
    g.add_argument('--outline-color',       type=float, nargs=3, default=[0, 0, 0],
                   metavar=('R', 'G', 'B'),
                   help='Outline color as 0-1 RGB (default: 0 0 0)')
    g.add_argument('--specular',            action='store_true',
                   help='Enable hard specular highlight band')
    g.add_argument('--specular-threshold',  type=float, default=0.85)
    g.add_argument('--specular-boost',      type=float, default=0.15)
    g.add_argument('--saturation-boost',    type=float, default=0.0,
                   help='Saturation adjustment (-1 to 1)')
    g.add_argument('--pre-blur',            type=float, default=0.0,
                   help='Gaussian blur sigma to smooth MC noise before processing')

    args = parser.parse_args()

    if len(args.input) > 1 and args.output:
        parser.error("--output cannot be used with multiple input files")

    for input_path in args.input:
        if not Path(input_path).exists():
            print(f"Error: '{input_path}' not found", file=sys.stderr)
            continue

        output_path = args.output or str(Path(input_path).parent / f"{Path(input_path).stem}_toon.png")

        print(f"Reading {input_path} ...")
        img = read_image(input_path)
        print(f"  Image size: {img.shape[1]}×{img.shape[0]}, range: [{img.min():.3f}, {img.max():.3f}]")
        print(f"  Applying toon shading (bands={args.bands}, edges={args.edge_threshold}) ...")

        result = toon_shading_effect(
            img,
            exposure=args.exposure,
            tone_map_method=args.tone_map,
            num_bands=args.bands,
            band_smoothing=args.band_smoothing,
            quantize_colors=args.quantize_colors,
            hue_bins=args.hue_bins,
            sat_bins=args.sat_bins,
            edge_method=args.edge_method,
            edge_threshold=args.edge_threshold,
            edge_thickness=args.edge_thickness,
            outline_color=tuple(args.outline_color),
            specular=args.specular,
            specular_threshold=args.specular_threshold,
            specular_boost=args.specular_boost,
            saturation_boost=args.saturation_boost,
            pre_blur_sigma=args.pre_blur,
        )

        write_image(output_path, result)
        print(f"  Saved → {output_path}")

    print("Done.")


if __name__ == '__main__':
    main()
