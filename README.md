# Beyond Post-Processing: Multi-Style Path Tracing in La Jolla

**CSE 272 Final Project — Jason Zhu, UCSD Winter 2025**

A personal extension of the [La Jolla physically-based renderer](https://github.com/BachiLi/lajolla_public) implementing West's *Stylized Rendering as a Function of Expectation* (SIGGRAPH 2024) across four rendering pipelines.

📄 [Full Report](final_project/report/CSE272_Jason_Zhu.pdf) · 🔗 [Original La Jolla](https://github.com/BachiLi/lajolla_public)

---

## Overview

| Pipeline | Name | Description |
|---|---|---|
| **P1** | Post-Processing NPR | Image-space effects: 1-bit dithering, toon shading, Kuwahara painterly, Sobel outlines |
| **P2** | Deer Hunter II Viewer | Real-time unlit flat-albedo renderer with ground shadows and fog (Embree + SDL2) |
| **P3** | Deterministic Cel-Shading | Monte Carlo cel-shading with animated PBR→stylized crossfade |
| **P4** | Multi-Style Showcase | Per-object dispatch of cel, tie-dye, and ACP styles in a single render |

---

## Build

> Requires: C++17 compiler, CMake ≥ 3.18, Python ≥ 3.9

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

**Apple Silicon (M-series):** The prebuilt Embree binary supports both arm64 and x86_64 via universal binary. If you hit architecture issues, build Embree from source.

Verify the build:
```bash
cd build && ctest --output-on-failure
```

---

## Pipeline 1 — Post-Processing NPR

Image-space stylization applied to finished renders. All effects are implemented in [`final_project/npr_integrator.h`](final_project/npr_integrator.h) and the Python post-processing scripts.

### Step 1: Render with NPR integrator

```bash
# Renders with the NPR integrator — outputs 4 EXRs:
# image.exr  image_depth.exr  image_normal.exr  image_objectid.exr
build/lajolla scenes/skypop_game/scene.xml
```

### Step 2: Apply post-processing effects

```bash
# Run the full post-processing pipeline (dithering, toon, painterly, outlines)
python3 final_project/animate_npr.py

# Individual passes via sobel_post.py:
python3 final_project/sobel_post.py image.exr                        # Sobel outlines only
python3 final_project/sobel_post.py image.exr \
    --depth_thresh 0.05 --normal_thresh 0.40                         # Custom thresholds
python3 final_project/sobel_post.py image.exr --debug-aov depth      # Inspect depth AOV
python3 final_project/sobel_post.py image.exr --debug-aov normal     # Inspect normals
python3 final_project/sobel_post.py image.exr --debug-aov objectid   # Inspect object IDs
```

### Convert to PNG for reports

```bash
python3 final_project/_convert_pngs.py
# Writes: render_color.png, render_outlined.png, render_depth.png,
#         render_normal.png, render_objectid.png
```

---

## Pipeline 2 — Deer Hunter II Real-Time Viewer

A standalone real-time renderer reproducing the [Sokpop Collective's Deer Hunter II](https://sokpop.itch.io/deer-hunter-ii) aesthetic: unlit flat albedo, binary ground shadows, and linear distance fog. Built on Embree 4 and SDL2.

### Build & Run

The viewer is compiled as part of the main build:

```bash
cmake --build build --target interactive_viewer --parallel

# Launch the interactive viewer
build/interactive_viewer scenes/skypop_game/scene.xml
```

### Controls

| Key | Action |
|---|---|
| `W/A/S/D` | Move camera |
| Mouse drag | Rotate view |
| `Q / E` | Move up / down |
| `ESC` | Quit |

### Screenshot & GIF capture

```bash
# Renders a series of screenshots from multiple angles
python3 final_project/render_report_imgs.py --pipeline p2
```

---

## Pipeline 3 — Deterministic Cel-Shading (Monte Carlo Transition)

Integrator: `StylizedPath` in [`final_project/stylized_pt_integrator.h`](final_project/stylized_pt_integrator.h). Renders with a k-sample inner Monte Carlo estimate; applies a hard-threshold cel-shading style function.

### Render a single frame

```bash
# Fully photorealistic (t=0%)
build/lajolla scenes/cbox/cbox_transition.xml

# Fully cel-shaded (t=100%)
# Edit <transition_t value="1.0"/> in the scene XML, then re-render
build/lajolla scenes/cbox/cbox_transition.xml
```

### Animated PBR → Cel-Shading transition

```bash
# Generates 8 frames at t = 0%, 2%, 4%, 8%, 16%, 32%, 64%, 100%
python3 final_project/animate_transition.py \
    --scene scenes/cbox/cbox_transition.xml \
    --steps 0 0.02 0.04 0.08 0.16 0.32 0.64 1.0 \
    --output-dir final_project/imgs/transition
```

### XML options (in `<integrator type="stylized_path">`)

```xml
<integer name="num_inner_samples" value="256"/>   <!-- k: inner MC samples -->
<integer name="num_samples" value="16"/>           <!-- SPP -->
<float   name="transition_t" value="1.0"/>         <!-- blend: 0=PBR, 1=styled -->
<boolean name="use_halton" value="false"/>         <!-- quasi-MC inner sampler -->
<boolean name="use_chebyshev" value="false"/>      <!-- Chebyshev cel estimator -->
```

---

## Pipeline 4 — Multi-Style Monte Carlo Showcase

Per-object dispatch of three style functions in the *Sculpture Garden* scene. Each object is assigned a style via ID lists in the scene XML.

### Render the Sculpture Garden

```bash
build/lajolla scenes/gallery/scene.xml
```

### Animated light sweep

```bash
# 6-frame animated light sweep (area light moves left-to-right across the scene)
python3 final_project/animate_gallery.py \
    --scene scenes/gallery/scene.xml \
    --frames 6 \
    --output-dir final_project/imgs/gallery
```

### Configuring per-object styles (in `scenes/gallery/scene.xml`)

```xml
<!-- Assign shapes to style groups by their integer shape IDs -->
<string name="cel_shape_ids"    value="0 1"/>      <!-- cel-shading targets -->
<string name="tiedye_shape_ids" value="2 3"/>      <!-- tie-dye targets -->
<string name="acp_shape_ids"    value="4"/>         <!-- ACP targets -->
<!-- All others default to standard PBR -->
```

---

## Advanced Options (Pipelines 3–4)

### Low-Discrepancy Sampling (Halton QMC)

Reduces shadow-boundary mollification without increasing k. Enable per scene:

```xml
<boolean name="use_halton" value="true"/>
```

Implemented as `HaltonSampler` (Cranley–Patterson scrambled, 8-dimensional) in `final_project/stylized_pt_integrator.h`.

### Chebyshev Polynomial Cel Estimator

Reduces bias at low k by approximating the step function with a degree-20 Chebyshev polynomial (Clenshaw recurrence evaluation). Enable per scene:

```xml
<boolean name="use_chebyshev" value="true"/>
```

Implemented as `eval_cheby_step` / `stylized_apply_cel_chebyshev` in `final_project/stylized_pt_integrator.h`.

---

## Diagnostics

```bash
# Inspect per-object normal stability
python3 final_project/_diag_normals.py

# Inspect per-shape color values in latest render
python3 final_project/_diag_color.py

# Inspect AOV neighbor differences (edge detection debug)
python3 final_project/_diag_aov.py
```

---

## Project Structure

```
lajolla_public/
├── final_project/
│   ├── stylized_pt_integrator.h   # Pipelines 3–4: stylized MC integrator
│   ├── npr_integrator.h            # Pipeline 1: deterministic NPR integrator
│   ├── interactive_viewer.cpp      # Pipeline 2: real-time SDL2 viewer
│   ├── animate_transition.py       # Pipeline 3: animated cel-shading transition
│   ├── animate_gallery.py          # Pipeline 4: animated light sweep
│   ├── animate_npr.py              # Pipeline 1: NPR orbit animation
│   ├── sobel_post.py               # Post-processing: Sobel outline pass
│   ├── render_report_imgs.py       # Batch render for report figures
│   └── report/
│       ├── CSE272_Jason_Zhu.tex    # LaTeX report source
│       └── CSE272_Jason_Zhu.pdf    # Compiled report
├── scenes/
│   ├── skypop_game/                # Pipeline 1 & 2: Deer Hunter II savanna scene
│   ├── cbox/                       # Pipeline 3: Cornell Box cel-shading transition
│   └── gallery/                    # Pipeline 4: Sculpture Garden multi-style
└── src/
    ├── integrators/stylized_path.* # Integrator registration
    └── parsers/parse_scene.cpp     # XML parsing for new options
```

---

## Running Tests

```bash
cd build && ctest --output-on-failure
```

---

## Acknowledgements

Built on [La Jolla](https://github.com/BachiLi/lajolla_public) by Tzu-Mao Li.
Stylization framework from West & Mukherjee, *Stylized Rendering as a Function of Expectation*, SIGGRAPH 2024.
Deer Hunter II aesthetic inspired by [Sokpop Collective](https://sokpop.itch.io/deer-hunter-ii).
Uses [Embree](https://www.embree.org/), [pugixml](https://pugixml.org/), [pcg](https://www.pcg-random.org/), [stb_image](https://github.com/nothings/stb), [tinyexr](https://github.com/syoyo/tinyexr), [miniz](https://github.com/richgel999/miniz), [tinyply](https://github.com/ddiakopoulos/tinyply).
