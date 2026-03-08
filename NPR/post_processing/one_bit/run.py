#!/usr/bin/env python3
"""
CLI entry point for NPR post-processing on lajolla renders.

Usage examples:
    # Obra Dinn with defaults
    python run.py path/to/render.exr -o output.png

    # Tweak exposure and use sepia palette
    python run.py render.exr -o sepia.png --exposure 2.0 --palette sepia

    # Coarser dithering + pixelated look
    python run.py render.exr -o chunky.png --bayer-size 2 --downscale 2

    # Higher contrast, more visible edges
    python run.py render.exr -o contrasty.png --contrast 1.5 --edge-threshold 0.05

    # Batch: process all EXR files in a directory
    python run.py images/*.exr --effect obra_dinn
"""

import argparse
import sys
from pathlib import Path

from image_io import read_image, write_image
from obra_dinn import obra_dinn_effect, PALETTES


def default_output_path(input_path, effect):
    p = Path(input_path)
    return str(p.parent / f"{p.stem}_{effect}.png")


def main():
    parser = argparse.ArgumentParser(
        description='NPR Post-Processing for lajolla renders',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'input', nargs='+',
        help='Input image(s): EXR, HDR, PNG, etc.',
    )
    parser.add_argument(
        '-o', '--output',
        help='Output path (for single input). Default: <input>_<effect>.png',
    )
    parser.add_argument(
        '--effect', choices=['obra_dinn'],
        default='obra_dinn',
        help='NPR effect to apply (default: obra_dinn)',
    )

    # ── Obra Dinn parameters ────────────────────────────────────────────
    g = parser.add_argument_group('Obra Dinn parameters')
    g.add_argument('--exposure',        type=float, default=1.0,
                   help='Exposure multiplier (default: 1.0)')
    g.add_argument('--tone-map',        choices=['reinhard', 'aces', 'gamma', 'clamp'],
                   default='reinhard',
                   help='Tone mapping curve (default: reinhard)')
    g.add_argument('--bayer-size',      type=int, default=3,
                   help='Bayer matrix order: 2→4×4, 3→8×8, 4→16×16 (default: 3)')
    g.add_argument('--edge-method',     choices=['sobel', 'laplacian', 'combined'],
                   default='sobel',
                   help='Edge detection method (default: sobel)')
    g.add_argument('--edge-threshold',  type=float, default=0.1,
                   help='Edge threshold, lower→more edges (default: 0.1)')
    g.add_argument('--edge-weight',     type=float, default=1.0,
                   help='Edge overlay strength 0–1 (default: 1.0)')
    g.add_argument('--contrast',        type=float, default=1.0,
                   help='Contrast multiplier (default: 1.0)')
    g.add_argument('--brightness',      type=float, default=0.0,
                   help='Brightness offset (default: 0.0)')
    g.add_argument('--palette',         default='obra_dinn',
                   help=f'Palette: {", ".join(PALETTES.keys())} (default: obra_dinn)')
    g.add_argument('--downscale',       type=int, default=1,
                   help='Integer downscale factor for pixelated look (default: 1)')

    args = parser.parse_args()

    if len(args.input) > 1 and args.output:
        parser.error("--output cannot be used with multiple input files")

    for input_path in args.input:
        if not Path(input_path).exists():
            print(f"Error: '{input_path}' not found", file=sys.stderr)
            continue

        output_path = args.output or default_output_path(input_path, args.effect)

        print(f"Reading {input_path} ...")
        img = read_image(input_path)
        print(f"  Image size: {img.shape[1]}×{img.shape[0]}, range: [{img.min():.3f}, {img.max():.3f}]")

        if args.effect == 'obra_dinn':
            print(f"  Applying Obra Dinn effect (palette={args.palette}, bayer={args.bayer_size}) ...")
            result = obra_dinn_effect(
                img,
                exposure=args.exposure,
                tone_map_method=args.tone_map,
                bayer_size=args.bayer_size,
                edge_method=args.edge_method,
                edge_threshold=args.edge_threshold,
                edge_weight=args.edge_weight,
                contrast=args.contrast,
                brightness=args.brightness,
                palette=args.palette,
                downscale=args.downscale,
            )

        write_image(output_path, result)
        print(f"  Saved → {output_path}")

    print("Done.")


if __name__ == '__main__':
    main()
