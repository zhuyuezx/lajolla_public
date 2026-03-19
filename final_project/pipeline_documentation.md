# NPR Rendering Pipelines — La Jolla

Three rendering pipelines implemented in the La Jolla physically-based renderer, each building on the previous one.

---

## Pipeline 1: Skypop-Style NPR Rendering

A deterministic, non-physically-based cel-shading pipeline inspired by the Skypop Collective aesthetic. **Zero Monte Carlo sampling** — one ray per pixel, fully deterministic.

### Pipeline Diagram

```
Scene XML (integrator type="npr")
        │
        ▼
┌─────────────────────────────────┐
│  npr_render() — per pixel:      │
│                                 │
│  1. Cast primary ray            │
│  2. Intersect scene (Embree)    │
│  3. npr_shade_pixel()           │
│  4. Write AOVs (depth/N/id)     │
└────────┬────────────────────────┘
         │  Outputs 4 EXR files
         ▼
┌─────────────────────────────────┐
│  sobel_post.py                  │
│                                 │
│  Read AOVs → Sobel edge detect  │
│  Composite black outlines       │
└────────┬────────────────────────┘
         ▼
    Final outlined EXR
```

### Shading Model ([npr_shade_pixel](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/npr_integrator.h#50-111))

Per-pixel logic (no randomness, no bounces):

```
Input: geometric_normal N, material albedo, light_dir L

1. Flip N to face camera:  if (N · (-ray_dir) < 0) N = -N
2. Compute  NdotL = N · L
3. Shadow test:
     if NdotL > 0 → cast shadow ray toward L to infinity
     if occluded → in_shadow = true
4. Cel quantization (hard step):
     if (!in_shadow && NdotL > cel_threshold)
       → diffuse = albedo × light_color       (LIT)
     else
       → diffuse = albedo × shadow_tint        (SHADOW)
5. Add flat ambient:  result = diffuse + albedo × ambient
```

### AOV Output

Each pixel also writes:

| AOV | Content |
|-----|---------|
| **Depth** | [dot(hit_pos - ray_origin, ray_dir)](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/interactive_viewer.cpp#44-45) — projected distance; −1 on miss |
| **Normal** | Flat geometric normal, camera-facing flip, near-zero cleanup |
| **Object ID** | `shape_id` as float; −1 on miss |

### Sobel Outline Post-Processing ([sobel_post.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/sobel_post.py))

4-connected neighbor comparison (right + down neighbors):

```
For each adjacent pixel pair:
  depth_diff   = |depth[self] - depth[neighbor]|   (normalised)
  normal_diff  = length(normal[self] - normal[neighbor])
  id_changed   = |objectID[self] - objectID[neighbor]| > 0.5

Edge if:  depth_diff > threshold  OR  normal_diff > threshold  OR  id_changed
Silhouette: one pixel valid, neighbor is background → always edge
```

Overwrites edge pixels with solid outline color (default: black).

### Source Files

| File | Role |
|------|------|
| [npr_integrator.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/npr_integrator.h) | [NprAovs](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/npr_integrator.h#32-37), [npr_shade_pixel](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/npr_integrator.h#50-111), [npr_render](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/npr_integrator.h#112-193) |
| [sobel_post.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/sobel_post.py) | Sobel edge detection + outline compositing |
| [scene.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/npr_cbox/scene.xml) | NPR Cornell Box scene |

### Run Commands

```bash
# Render
./build/lajolla scenes/npr_cbox/scene.xml

# Apply outlines
python3 final_project/sobel_post.py image.exr -o image_outlined.exr
```

---

## Pipeline 2: West's Stylized Path Tracing (Static)

Implements West 2024 — "Stylized Rendering as a Function of Expectation." A **physically-based** path tracer with a non-linear style function g_θ applied to the MC estimate at the first camera hit. Produces GI-aware cel shading with proper color bleed, soft shadows, and indirect illumination — unlike Pipeline 1 which used a single directional light.

### Pipeline Diagram

```
Scene XML (integrator type="stylized_pt")
        │
        ▼
┌──────────────────────────────────────┐
│  stylized_pt_render() — per pixel:   │
│                                      │
│  1. Cast primary ray                 │
│  2. Intersect scene                  │
│  3. k-sample inner MC estimate:      │
│     for s in 0..k:                   │
│       inner_sum += stylized_inner_   │
│                    trace(vertex)     │
│     ⟨I⟩ = inner_sum / k             │
│  4. Apply g_θ: cel step on ⟨I⟩      │
│  5. Write AOVs (depth/N/id)          │
└────────┬─────────────────────────────┘
         │  Outputs 4 EXR files
         ▼
┌──────────────────────────────────────┐
│  sobel_post.py (same as Pipeline 1)  │
└────────┬─────────────────────────────┘
         ▼
    Final outlined EXR
```

### Inner Trace ([stylized_inner_trace](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#32-191))

Each of the k inner samples is a **full physical path trace** from the first-hit vertex:

```
Starting from vertex (first camera hit):

1. Account for emission if vertex is a light
2. Loop (bounded by max_depth, or unbounded if -1):
   a. Next Event Estimation (NEE):
      - Sample a light source
      - Cast shadow ray
      - Evaluate BSDF f(ωi, ωo) × L × G
      - MIS weight: w₁ = p₁² / (p₁² + p₂²)
   b. BSDF sampling:
      - Sample outgoing direction from BSDF
      - Cast continuation ray
      - If hits light: evaluate emission with MIS weight w₂
      - Update ray differentials
   c. Russian Roulette (depth ≥ rr_depth):
      - Survival probability: min(max(throughput), 0.95)
      - If terminated → break
   d. Update throughput: T *= (G × f) / (pdf × rr_prob)
```

### Style Function g_θ ([stylized_apply_g_theta](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#192-217))

Applied to the **averaged** inner estimate ⟨I⟩:

```
lum = luminance(⟨I⟩)       // scalar brightness

if lum >= cel_threshold:
  result = albedo × light_color     // LIT band
else:
  result = albedo × shadow_tint     // SHADOW band

result += albedo × ambient          // flat ambient
```

> [!IMPORTANT]
> **Mollification:** At low k, variance in ⟨I⟩ causes pixels near the cel threshold to flip randomly between lit/shadow → soft, blurred boundaries. At high k (≥256), the estimate converges → pixels land cleanly on one side → **sharp discrete bands**. This is the super-linear convergence from West 2024 §3.2.

### Source Files

| File | Role |
|------|------|
| [stylized_pt_integrator.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h) | [stylized_inner_trace](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#32-191), [stylized_apply_g_theta](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#192-217), [stylized_pt_render](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#299-364) |
| [sobel_post.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/sobel_post.py) | Sobel outlines (shared with Pipeline 1) |
| [cbox_stylized.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/cbox/cbox_stylized.xml) | k=16 (fast iteration) |
| [cbox_stylized_hi.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/cbox/cbox_stylized_hi.xml) | k=256 (sharp cel bands) |

### Run Commands

```bash
./build/lajolla scenes/cbox/cbox_stylized.xml
python3 final_project/sobel_post.py image.exr -o image_outlined.exr
```

---

## Pipeline 3: West's Stylized Path Tracing (Animated Transition)

Extends Pipeline 2 with **object-ID-selective stylization** and a **temporal crossfade**, rendered across 60 frames with a sinusoidal camera orbit.

### Key Additions over Pipeline 2

- **Object-ID dispatch**: `target_object_ids` list → only selected shapes get the k-sample + g_θ treatment; others use cheap 1-sample PBR
- **Temporal crossfade**: `transition_t` ∈ [0,1] blends `lerp(PBR, styled, t)` per pixel
- **Camera orbit**: sinusoidal ±30° horizontal arc over 60 frames

### Source Files

| File | Role |
|------|------|
| [stylized_pt_integrator.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h) | Object-ID check, temporal crossfade, PBR fallback |
| [animate_transition.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/animate_transition.py) | 60-frame orchestrator, XML patching, GIF assembly |
| [cbox_transition.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/cbox/cbox_transition.xml) | Gold + blue pillars, red/green walls |

### Run Commands

```bash
python3 final_project/animate_transition.py \
  --scene scenes/cbox/cbox_transition.xml \
  --frames 60 --fps 15 --orbit 30 \
  --output transition.gif
```

---

## Pipeline 4: Multi-Style Showcase (Per-Object Dispatch + Moving Light)

Extends Pipeline 3 with **three distinct style functions** assignable per-object, two new colour-based g_θ functions from West 2024 (Tie-Dye and ACP), and a **moving area light** animation demonstrating how each style responds to changing illumination in a custom open-air scene.

### Pipeline Diagram

```
animate_gallery.py (orchestrator)
│
│  For each frame i = 0..59:
│    light_pos = semicircular arc(i)
│    │
│    ▼
│  ┌────────────────────────────────────────────┐
│  │  Patch XML:                                │
│  │    <translate x= y= z= />  = light arc    │
│  │  Write XML in scene directory              │
│  │    (mesh paths are relative!)              │
│  └────────┬───────────────────────────────────┘
│           ▼
│  ┌────────────────────────────────────────────┐
│  │  ./build/lajolla frame.xml                 │
│  │                                            │
│  │  stylized_path_tracing() per pixel:        │
│  │    style_id = get_style_for_shape(hit)     │
│  │      0 → 1-sample PBR (non-target)         │
│  │      1 → k-sample ⟨I⟩ → cel g_θ           │
│  │      2 → k-sample ⟨I⟩ → tiedye g_θ        │
│  │      3 → k-sample ⟨I⟩ → acp g_θ           │
│  │    lerp(PBR, styled, transition_t)         │
│  └────────┬───────────────────────────────────┘
│           ▼
│    frame.exr → ffmpeg sRGB → .png
│
▼
ffmpeg palettegen + paletteuse → gallery.gif
```

### Per-Object Style Dispatch

Each shape is checked against three separate ID lists in priority order:

```
get_style_for_shape(scene, shape_id):
  if shape_id in cel_target_ids     → return CEL     (1)
  if shape_id in tiedye_target_ids  → return TIEDYE  (2)
  if shape_id in acp_target_ids     → return ACP     (3)
  // Backward compat with Pipeline 3:
  if shape_id in target_object_ids  → style_type selects (1/2/3)
  return NONE (0)    // standard PBR
```

### Style Functions

#### Cel-Shading g_θ (Pipeline 2–3, unchanged)

```
lum = luminance(⟨I⟩)
if lum >= threshold → albedo × light_color
else               → albedo × shadow_tint
+ ambient
```

#### Tie-Dye Cosine g_θ (West Fig 11) — [stylized_apply_tiedye](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#248-260)

Per-channel cosine waves applied to the physical radiance:

```
result.r = |cos(freq.r × ⟨I⟩.r + phase.r)|
result.g = |cos(freq.g × ⟨I⟩.g + phase.g)|
result.b = |cos(freq.b × ⟨I⟩.b + phase.b)|
```

Parameters: `tie_dye_freq` (Vector3), `tie_dye_phase` (Vector3)

#### ACP Colour Ramp g_θ (West Fig 7) — [stylized_apply_acp](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#269-278)

Maps luminance to a two-stop colour ramp:

```
lum = clamp(luminance(⟨I⟩), 0, 1)
result = lerp(acp_dark_color, acp_bright_color, lum)
```

Parameters: `acp_dark_color` (Vector3), `acp_bright_color` (Vector3)

### Moving Light Animation

The area light sweeps in a semicircular arc across 60 frames:

```python
arc_angle = π × frame / (n_frames - 1)     # 0..π

light_x = -radius × cos(arc_angle)          # left → right
light_y = min_y + (max_y - min_y) × sin()   # low → high → low
light_z = constant                           # behind camera
```

| Frame | Position | Lighting angle |
|-------|----------|----------------|
| 0 | far left, low | grazing from left |
| 30 | centred, high | overhead (top-down) |
| 60 | far right, low | grazing from right |

> [!IMPORTANT]
> **Mesh Path Resolution:** La Jolla resolves OBJ paths relative to the **scene XML's directory**. Temp frame XMLs must be written into the scene directory (not `/tmp/`) for meshes to load.

### XML Parameters

```xml
<integrator type="stylized_pt">
    <integer name="inner_samples"     value="256"/>
    <float   name="transition_t"      value="1.0"/>

    <!-- Per-object style assignment (by shape ID) -->
    <string  name="cel_ids"           value="2,3,8"/>
    <string  name="tiedye_ids"        value="6,7"/>
    <string  name="acp_ids"           value="4,5,9"/>

    <!-- Tie-Dye parameters -->
    <vector  name="tie_dye_freq"      value="12.0, 16.0, 20.0"/>
    <vector  name="tie_dye_phase"     value="0.5, 2.5, 4.5"/>

    <!-- ACP parameters -->
    <vector  name="acp_dark_color"    value="0.06, 0.02, 0.18"/>
    <vector  name="acp_bright_color"  value="1.0, 0.50, 0.15"/>
</integrator>
```

### Source Files

| File | Role |
|------|------|
| [stylized_pt_integrator.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h) | [get_style_for_shape](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#228-246), [stylized_apply_tiedye](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#248-260), [stylized_apply_acp](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h#269-278) |
| [scene.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/scene.h) | `cel_target_ids`, `tiedye_target_ids`, `acp_target_ids`, tie-dye/ACP params in [RenderOptions](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/scene.h#26-70) |
| [parse_scene.cpp](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/parsers/parse_scene.cpp) | Parse `cel_ids`, `tiedye_ids`, `acp_ids`, tie-dye/ACP params |
| [animate_gallery.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/animate_gallery.py) | Moving-light orchestrator, ffmpeg-based GIF assembly |
| [scene.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/gallery/scene.xml) | Sculpture Garden: 5 OBJ meshes + 4 spheres, open-air, per-object styles |

### Sculpture Garden Scene

Custom open-air scene (no Cornell Box):

| Shape ID | Object | Style | Material |
|----------|--------|-------|----------|
| 0 | Area light (invisible) | — | — |
| 1 | Ground plane (60×60) | PBR | Sandy stone |
| 2 | Tall pedestal | Cel | Golden |
| 3 | Sphere on tall pedestal | Cel | Sky blue |
| 4 | Short pedestal | ACP | Terracotta |
| 5 | Sphere on short pedestal | ACP | Coral |
| 6 | Column (32-gon) | Tie-Dye | Emerald |
| 7 | Floating orb near column | Tie-Dye | Lavender |
| 8 | Floating orb (high) | Cel | Pearl |
| 9 | Wide pedestal | ACP | Slate |

### Run Commands

```bash
# Single frame (16 SPP × 256 inner, ~2.8s)
./build/lajolla scenes/gallery/scene.xml

# Full animation (60 frames, moving light, ~3 min)
python3 final_project/animate_gallery.py \
  --scene scenes/gallery/scene.xml \
  --frames 60 --fps 15 --output gallery.gif
```

---

## Comparison

| | Pipeline 1: Skypop | Pipeline 2: West (Static) | Pipeline 3: West (Animated) | Pipeline 4: Multi-Style |
|---|---|---|---|---|
| **Lighting** | Single directional | Full GI (area lights) | Full GI | Full GI + moving light |
| **Shading** | N·L + hard shadow | k-sample MC → cel | k-sample MC → lerp(PBR, cel, t) | k-sample MC → per-object g_θ |
| **Style functions** | Cel only | Cel only | Cel only | Cel, Tie-Dye, ACP |
| **Style dispatch** | Global | Global | Per-target-list | Per-object (3 lists) |
| **Bounces** | 0 (primary only) | Unlimited (RR) | Unlimited (RR) | Unlimited (RR) |
| **Color Bleed** | None | Yes (physical) | Yes (physical) | Yes (physical) |
| **Outlines** | Sobel AOVs | Sobel AOVs | None | None |
| **Scene** | Cornell Box | Cornell Box | Cornell Box | Custom (Sculpture Garden) |
| **Animation** | Static | Static | Camera orbit + t crossfade | Moving light sweep |
| **Cost per pixel** | 1 ray | k × path trace | target: k × PT; other: 1 × PT | target: k × PT; other: 1 × PT |
| **Deterministic** | Yes | No (MC) | No (MC) | No (MC) |
