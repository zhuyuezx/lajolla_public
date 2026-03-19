#!/usr/bin/env python3
"""
Render all images for the final report.
Outputs go to final_project/imgs/ with consistent 640x480 resolution.

Pipeline 1 (Skypop NPR): 3 angles of the deer-hunter / skypop_game scene + outlined
Pipeline 2 (Post-Processing): obra dinn, toon shading, painterly (side-by-side)
Pipeline 3 (West Animated): 7 transition steps (t=0, 2, 4, 8, 16, 32, 64, 100 %)
Pipeline 4 (Multi-Style): 6 light sweep positions with closer camera
"""

import math, os, re, subprocess, sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAJOLLA = ROOT / "build" / "lajolla"
IMGS = ROOT / "final_project" / "imgs"
IMGS.mkdir(parents=True, exist_ok=True)

W, H = 640, 480  # consistent resolution


def lajolla_render(scene_xml, output_png, cwd=None):
    """Render scene_xml -> image.exr -> output_png (8-bit sRGB)."""
    if cwd is None:
        cwd = str(ROOT)
    r = subprocess.run([str(LAJOLLA), scene_xml],
                       capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(f"  ERROR rendering {scene_xml}: {r.stderr[:300]}")
        return False
    exr = ROOT / "image.exr"
    if not exr.exists():
        print(f"  ERROR: image.exr not found after rendering")
        return False
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-apply_trc", "iec61966_2_1",
         "-i", str(exr), "-pix_fmt", "rgb24", str(output_png)],
        capture_output=True)
    return Path(output_png).exists()


# ═══════════════════════════════════════════════════════
# Pipeline 1: Skypop NPR — skypop_game scene, 3 angles
# ═══════════════════════════════════════════════════════
def render_pipeline1():
    print("═══ Pipeline 1: Skypop NPR — skypop_game scene (3 angles) ═══")
    scene_path = ROOT / "scenes" / "skypop_game" / "scene.xml"
    scene_dir = scene_path.parent
    text = scene_path.read_text()

    # Override resolution
    text = re.sub(r'name="width"\s+value="\d+"', f'name="width" value="{W}"', text)
    text = re.sub(r'name="height"\s+value="\d+"', f'name="height" value="{H}"', text)

    # 3 camera angles around the scene
    angles = [
        ("front",    "15, 14, 15",     "0, 1.2, 0"),      # original isometric
        ("side",     "-12, 10, 12",    "0, 1.5, 0"),      # left-side view
        ("close",    "6, 6, 8",        "0, 1.8, -1"),     # close-up 3/4 view
    ]

    for name, origin, target in angles:
        txt = re.sub(
            r'origin="[^"]*"\s*\n\s*target="[^"]*"',
            f'origin="{origin}"\n                    target="{target}"',
            text, count=1)
        tmp_xml = scene_dir / f"_tmp_{name}.xml"
        tmp_xml.write_text(txt)
        out = IMGS / f"p1_skypop_{name}.png"
        ok = lajolla_render(str(tmp_xml), str(out))
        tmp_xml.unlink(missing_ok=True)
        print(f"  {name}: {'OK' if ok else 'FAIL'}")

    # Also generate outlined version of front view
    txt_front = re.sub(
        r'origin="[^"]*"\s*\n\s*target="[^"]*"',
        f'origin="15, 14, 15"\n                    target="0, 1.2, 0"',
        text, count=1)
    tmp_xml = scene_dir / "_tmp_front_outline.xml"
    tmp_xml.write_text(txt_front)
    subprocess.run([str(LAJOLLA), str(tmp_xml)], capture_output=True, cwd=str(ROOT))
    tmp_xml.unlink(missing_ok=True)
    sobel_script = ROOT / "final_project" / "sobel_post.py"
    if sobel_script.exists() and (ROOT / "image.exr").exists():
        subprocess.run(
            ["python3", str(sobel_script), str(ROOT / "image.exr"),
             "-o", str(ROOT / "image_outlined.exr")],
            capture_output=True, cwd=str(ROOT))
        outlined_exr = ROOT / "image_outlined.exr"
        if outlined_exr.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-apply_trc", "iec61966_2_1",
                 "-i", str(outlined_exr), "-pix_fmt", "rgb24",
                 str(IMGS / "p1_skypop_outlined.png")],
                capture_output=True)
            print(f"  outlined: OK")
        else:
            print(f"  outlined: FAIL (no outlined exr)")


# ═══════════════════════════════════════════════════════
# Pipeline 2: Post-Processing NPR effects
# ═══════════════════════════════════════════════════════
def render_pipeline2():
    print("═══ Pipeline 2: Post-Processing NPR ═══")
    npr_dir = ROOT / "NPR"
    os.chdir(str(npr_dir))
    sys.path.insert(0, str(npr_dir / "post_processing"))
    for sub in ['one_bit', 'toon_shading', 'painterly']:
        p = str(npr_dir / "post_processing" / sub)
        if p not in sys.path:
            sys.path.append(p)

    from image_io import read_image
    from obra_dinn import obra_dinn_effect
    from toon import toon_shading_effect
    from painterly import painterly_effect

    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    img_dir = npr_dir / "images" / "New-to_UCSD"

    def save_compare(original, result, left_title, right_title, out_path):
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        axes[0].imshow(np.clip(original, 0, 1))
        axes[0].set_title(left_title, fontsize=12, fontweight='bold')
        axes[0].axis('off')
        axes[1].imshow(np.clip(result, 0, 1))
        axes[1].set_title(right_title, fontsize=12, fontweight='bold')
        axes[1].axis('off')
        plt.tight_layout()
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close()

    # 1. Obra Dinn
    img = read_image(str(img_dir / "geisel.jpg"))
    result = obra_dinn_effect(img, tone_map_method='clamp', palette='obra_dinn',
                              bayer_size=3, edge_threshold=0.08, contrast=1.2)
    save_compare(img, result, 'Original — Geisel Library',
                 'Obra Dinn 1-bit dithering', str(IMGS / "p2_obra_dinn.png"))
    print("  obra_dinn: OK")

    # 2. Toon Shading
    img = read_image(str(img_dir / "beach_view.jpg"))
    result = toon_shading_effect(img, tone_map_method='clamp', num_bands=4,
                                 edge_threshold=0.06, edge_thickness=1)
    save_compare(img, result, 'Original — Beach View',
                 'Toon shading (4 bands)', str(IMGS / "p2_toon.png"))
    print("  toon: OK")

    # 3. Painterly (Litwinowicz)
    img = read_image(str(img_dir / "campus_rainbow.jpg"))
    result = painterly_effect(img, tone_map_method='clamp', style='litwinowicz',
                             grid_spacing=4, stroke_length=10, brush_radius=4)
    save_compare(img, result, 'Original — Campus Rainbow',
                 'Painterly (Litwinowicz)', str(IMGS / "p2_painterly.png"))
    print("  painterly: OK")

    # 4. Painterly (Oil / Kuwahara)
    img = read_image(str(img_dir / "campus_rainbow.jpg"))
    result = painterly_effect(img, tone_map_method='clamp', style='oil',
                             grid_spacing=4, stroke_length=10, brush_radius=4)
    save_compare(img, result, 'Original — Campus Rainbow',
                 'Oil Paint (Kuwahara)', str(IMGS / "p2_oil.png"))
    print("  oil: OK")

    os.chdir(str(ROOT))


# ═══════════════════════════════════════════════════════
# Pipeline 3: West Animated — 7 transition steps
# (t = 0, 2, 4, 8, 16, 32, 64, 100 %)
# ═══════════════════════════════════════════════════════
def render_pipeline3():
    print("═══ Pipeline 3: West Animated (7 transition steps) ═══")
    scene_path = ROOT / "scenes" / "cbox" / "cbox_transition.xml"
    text = scene_path.read_text()
    text = re.sub(r'name="width"\s+value="\d+"', f'name="width" value="{W}"', text)
    text = re.sub(r'name="height"\s+value="\d+"', f'name="height" value="{H}"', text)
    text = re.sub(r'name="inner_samples"\s+value="\d+"', 'name="inner_samples" value="128"', text)
    text = re.sub(r'name="sampleCount"\s+value="\d+"', 'name="sampleCount" value="16"', text)

    # t values: 0, 2, 4, 8, 16, 32, 64, 100 (as percentages)
    t_percents = [0, 2, 4, 8, 16, 32, 64, 100]

    for pct in t_percents:
        t_val = pct / 100.0
        txt = re.sub(
            r'name="transition_t"\s+value="[^"]*"',
            f'name="transition_t" value="{t_val:.2f}"',
            text)
        tmp_xml = scene_path.parent / f"_tmp_p3_{pct}.xml"
        tmp_xml.write_text(txt)
        out = IMGS / f"p3_transition_t{pct:03d}.png"
        ok = lajolla_render(str(tmp_xml), str(out))
        tmp_xml.unlink(missing_ok=True)
        print(f"  t={pct}%: {'OK' if ok else 'FAIL'}")


# ═══════════════════════════════════════════════════════
# Pipeline 4: Multi-Style — 6 light sweep, CLOSER camera
# ═══════════════════════════════════════════════════════
def render_pipeline4():
    print("═══ Pipeline 4: Multi-Style (6 light positions, close view) ═══")
    scene_path = ROOT / "scenes" / "gallery" / "scene.xml"
    scene_dir = scene_path.parent
    text = scene_path.read_text()

    # Move camera closer: reduce distance by ~40%, lower angle
    # Original: origin="18, 12, 20" target="0, 3, -2"
    # New closer: origin="12, 8, 14" target="0, 3, -1" with wider FOV
    text = re.sub(
        r'origin="18, 12, 20"',
        'origin="12, 8, 14"',
        text)
    text = re.sub(
        r'target="0, 3, -2"',
        'target="0, 3, -1"',
        text)
    text = re.sub(
        r'name="fov"\s+value="\d+"',
        'name="fov" value="55"',
        text)

    light_arc_radius = 25.0
    light_min_y = 30.0
    light_max_y = 55.0
    light_z = 10.0

    for i, frac in enumerate([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]):
        arc_angle = math.pi * frac
        lx = -light_arc_radius * math.cos(arc_angle)
        ly = light_min_y + (light_max_y - light_min_y) * math.sin(arc_angle)

        txt = re.sub(
            r'(<translate\s+x=")[^"]*("\s+y=")[^"]*("\s+z=")[^"]*("/)',
            rf'\g<1>{lx:.1f}\g<2>{ly:.1f}\g<3>{light_z:.1f}\g<4>',
            text, count=1)

        pct = int(frac * 100)
        # Write in scene dir so mesh paths resolve
        tmp_xml = scene_dir / f"_tmp_p4_{pct}.xml"
        tmp_xml.write_text(txt)
        out = IMGS / f"p4_gallery_light{pct:03d}.png"
        ok = lajolla_render(str(tmp_xml), str(out))
        tmp_xml.unlink(missing_ok=True)
        ang_deg = int(math.degrees(arc_angle))
        print(f"  light {ang_deg}°: {'OK' if ok else 'FAIL'}")


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    if not LAJOLLA.exists():
        sys.exit(f"Build lajolla first: {LAJOLLA}")

    render_pipeline1()
    render_pipeline2()
    render_pipeline3()
    render_pipeline4()

    print(f"\n═══ Done! Images in {IMGS} ═══")
    for f in sorted(IMGS.iterdir()):
        if f.suffix == '.png':
            print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")
