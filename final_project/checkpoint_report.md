---
title: "CSE272 Final Project Checkpoint Report"
author: Jason Zhu
date: March 9, 2026
geometry: margin=1in
fontfamily: libertinus
fontsize: 11pt
---

# CSE272 Final Project — Checkpoint Report

**Jason Zhu · March 9, 2026**

**Repository:** <https://github.com/zhuyuezx/lajolla_public> (forked from lajolla_public)

---

## Overview

This report covers the work completed for Phase 1 of the project: building a
Non-Photorealistic Rendering (NPR) pipeline on top of the La Jolla path tracer.
The deliverables span both a **2D post-processing baseline** (Python, applied to
photographs) and a **toon/cel-shading integrator with outline edge detection**
running inside the physically-based renderer.

---

## What Has Been Done

### 1. NPR Post-Processing Pipeline (`NPR/post_processing/`)

Three screen-space NPR effects were implemented in Python and demonstrated on
personal photographs via the interactive notebook `NPR/npr_demo.ipynb`.

#### 1a. 1-Bit Ordered Dithering — Obra Dinn style (`one_bit/obra_dinn.py`)

Converts an image to a 2-colour palette using a **Bayer ordered-dither** matrix.
Steps: (1) tone-map to LDR, (2) convert to luminance, (3) threshold against a
tiled Bayer matrix (configurable size 2–4 → 4×4 to 16×16 patterns), (4) perform
optional edge-enhancement before dithering, (5) remap the binary mask to the
chosen colour palette (`obra_dinn`, `bw`, `sepia`, `green_phosphor`, …).

![Obra Dinn — Geisel Library](npr_obra_dinn.png)

#### 1b. Toon / Cel Shading (`toon_shading/toon.py`)

Cel shading is achieved by **quantising the luminance channel** into a fixed
number of discrete bands and then detecting and drawing outlines.  Steps:
(1) tone-map, (2) convert to HSL, (3) snap the L channel to `num_bands` equal
steps, (4) recompose HSL → RGB (preserving hue and saturation), (5) detect edges
via a 4-connected neighbour luminance-difference test and paint them black.
Optional colour quantisation (`quantize_colors`) additionally snaps hue and
saturation to a coarse grid.

![Toon shading — Beach View](npr_toon.png)

#### 1c. Painterly Rendering (oil and Litwinowicz) (`painterly/painterly.py`)

Three painting styles are supported, all built on a **Kuwahara anisotropic
smoothing filter** that replaces each pixel with the mean of the lowest-variance
quadrant in its neighbourhood, producing the characteristic oil-paint blocky
abstraction.  The `litwinowicz` style additionally overlays oriented brush
strokes along image-gradient directions (Litwinowicz 1997).  Colour palette
reduction (uniform or k-means) reduces the final image to a target number of
distinct colours.

![Painterly — Campus Rainbow, oil](npr_painterly.png)

![Painterly — Campus Rainbow, Litwinowicz](npr_painterly_2.png)

---

### 2. Orthographic Camera

An orthographic sensor (`type="orthographic"`) was added to the La Jolla parser
and camera model.  An orthographic projection is the standard choice for
isometric / sketchbook-style NPR because it removes perspective distortion and
keeps far-away objects the same apparent size as close ones — matching the
flat, diagrammatic look of Skypop Collective's games.

The transform uses a `<lookAt>` tag identical to the perspective camera, and
the `scale` parameter controls the half-width of the view volume in world units.

---

### 3. NPR Integrator (`final_project/npr_integrator.h`)

A self-contained C++ integrator (`type="npr"`) was implemented.  Its key design
choices:

| Feature | Implementation |
|---|---|
| Shading | Flat (per-face `geometric_normal`) — no Gouraud or Phong interpolation |
| Light model | Single directional light; N·L dot product |
| Cel quantization | Hard threshold: pixels below `celThreshold` N·L receive a cool-tinted shadow |
| Ambient | Constant additive term |
| Shadow | Single shadow ray with a ray-origin bias of 1 × 10^-3^ world units |
| Background | Configurable miss colour |
| AOV outputs | Depth, surface normal, object ID — written automatically alongside the colour render |

All parameters (light direction/colour, ambient, shadow tint, cel threshold,
background colour) are exposed in the scene XML, e.g.:

```xml
<integrator type="npr">
    <string name="lightDir"        value="0.5, 0.5, -1"/>
    <string name="lightColor"      value="1.0, 0.98, 0.90"/>
    <string name="ambient"         value="0.05, 0.04, 0.06"/>
    <string name="shadowTint"      value="0.45, 0.45, 0.60"/>
    <float  name="celThreshold"    value="0.1"/>
    <string name="backgroundColor" value="0.75, 0.82, 0.95"/>
</integrator>
```

---

### 4. NPR Cornell Box Scene (`scenes/npr_cbox/`)

A dedicated Cornell Box scene was created that uses the NPR integrator and
orthographic camera.  Objects were given distinct, hand-tuned flat colours
distinct from the standard white/red/green Cornell Box:

- **Large box** — warm ochre `(0.76, 0.62, 0.42)`
- **Small box** — cool lavender `(0.45, 0.58, 0.72)`
- **Walls/floor/ceiling** — standard white, red, green

---

### 5. Render Results

#### Cel-shaded colour render
![Cel-shaded Cornell Box](render_color.png)

The two-step cel shading (lit / shadowed) is clearly visible on the box surfaces.
The cool shadow tint echoes the standard ink-shadow trick used in hand-drawn
illustration.

#### AOV buffers

| Depth | Surface Normals | Object ID |
|:---:|:---:|:---:|
| ![Depth](render_depth.png) | ![Normals](render_normal.png) | ![Object ID](render_objectid.png) |

The normal buffer stores camera-facing geometric normals (a sign-flip was
required for the Cornell Box ceiling, whose two quads have opposite winding
orders — see §6 below).

---

### 6. Sobel Edge Detection (`final_project/sobel_post.py`)

Outline edges are computed in a Python post-process using **direct 4-connected
neighbour comparison** rather than a Sobel convolution kernel.  A convolution
approach blurs sharp 1-pixel-wide geometry discontinuities; the neighbour
comparison detects them reliably.

Three independent edge sources are OR-ed together per pixel:

| Source | Criterion |
|---|---|
| Depth | `\|d[x,y] − d[neighbour]\| > depth_thresh` (normalised) |
| Normal | `‖n[x,y] − n[neighbour]‖₂ > normal_thresh` |
| Object ID | Object ID differs across the pixel boundary |

Additionally, pixels at the boundary between valid geometry and background
(silhouette) are always marked as edges.

#### Outlined render
![Outlined Cornell Box](render_outlined.png)

---

### 7. Normal AOV Bug Fix — Camera-Facing Flip

During development, spurious black clusters appeared on the ceiling.  Diagnosis
showed that `cbox_ceiling.obj` contains two quads with **opposite winding
orders**: the main ceiling face and the light-hole cutout.  Because no vertex
normals are stored in the OBJ, the geometric cross-product normals point in
opposite directions (`(0,−1,0)` vs `(0,+1,0)`).  Adjacent pixels across the
hole boundary produced a normal difference of 2.0, far exceeding the threshold.

Fix: before storing the normal into the AOV buffer, flip it to be camera-facing:

```cpp
if (dot(N_aov, -ray.dir) < Real(0)) N_aov = -N_aov;
```

Result: normal edge count dropped from **7,627 → 4,857** (−36%), and total
outlined pixels from 7,897 → 5,146 (−35%).

---

### 8. Orbit Animation (`final_project/animate_npr.py`)

A Python script was written to generate a live camera-orbit demo for the
report.  It:

1. Generates `N` camera positions on a horizontal circle around the scene centre.
2. For each frame: patches the scene XML (camera origin + absolute mesh paths),
   runs `build/lajolla`, and applies the Sobel outline pass.
3. Assembles the frames into an animated GIF with `imageio`.

The full 36-frame, 360° orbit runs in under 4 seconds.

```bash
python3 final_project/animate_npr.py \
    --frames 36 --orbit 360 --fps 12 --output animation.gif
```

#### Animated orbit (36 frames, 12 fps)
![360° camera orbit](animation.gif)

---

## What's Next

### Phase 2 — West's Stylized Path Tracing

The primary goal for the final report is to understand and replicate
[West (2024)](https://dl.acm.org/doi/epdf/10.1145/3658161): *"Stylized Path Tracing"*.
West's key insight is to **move the stylisation decision inside the recursive
path-tracing loop** rather than applying it as a screen-space post-process — at
each bounce, the integrator evaluates a stylisation function applied to the
expected radiance rather than the raw value.

After studying the paper more carefully, it is clear that this is
**significantly more complex than initially anticipated**.  The formalisation
involves non-linear expectation operators, a custom stroke BSDF, and careful
Monte Carlo estimator design that is not a straightforward extension of the
existing `path_tracing.h`.  The bulk of the time before the final report will
be dedicated to fully understanding the paper and producing at least a
single-bounce implementation with validation against the paper's figures.

### Backup Plan — Vivid Skypop Collective Demo

If a complete West implementation is not achievable in time, the backup is to
produce a rich, fully realised scene in the
[Skypop Collective](https://www.sokpop.co/) aesthetic.  The current Cornell Box
demo is a proof-of-concept; the target for the final report is a much more
immersive scene including:

- **Characters** — low-poly humanoid or creature models with flat cel-shaded
  skin tones
- **Trees and vegetation** — stylised chunky foliage with distinct lit/shadow
  bands
- **Sea / water** — flat animated panels with a simple animated light-direction
  sweep to simulate waves catching light
- **Environment** — tiled ground, simple buildings, distant hills; everything
  staying strictly low-poly and texture-free

The isometric orthographic camera and the current NPR integrator already handle
all of this; the remaining work is asset creation and scene assembly.

### Timeline

| Period | Goal |
|---|---|
| Now → +2 weeks | Deep-dive West paper; attempt single-bounce implementation |
| +2 → +3 weeks | Either: validate West integrator, or pivot fully to Skypop scene build |
| +3 → final report | Polish, renders, write-up |

---

## References

- T. West, *"Stylized Path Tracing"*, ACM SIGGRAPH 2024, [doi:10.1145/3658161](https://dl.acm.org/doi/epdf/10.1145/3658161)
- Skypop Collective, [sokpop.co](https://www.sokpop.co/)
- B. Phong, *"Illumination for Computer Generated Pictures"*, CACM 1975

