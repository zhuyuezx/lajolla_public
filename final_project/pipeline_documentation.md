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
# Fast iteration (k=16)
./build/lajolla scenes/cbox/cbox_stylized.xml
python3 final_project/sobel_post.py image.exr -o image_outlined.exr

# High quality (k=256, sharp cel bands)
./build/lajolla scenes/cbox/cbox_stylized_hi.xml
python3 final_project/sobel_post.py image.exr -o image_outlined.exr
```

---

## Pipeline 3: West's Stylized Path Tracing (Animated Transition)

Extends Pipeline 2 with **object-ID-selective stylization** and a **temporal crossfade**, rendered across 60 frames with a sinusoidal camera orbit. Demonstrates that the stylization is fully integrated into the 3D renderer, not a 2D post-process.

### Pipeline Diagram

```
animate_transition.py (orchestrator)
│
│  For each frame i = 0..59:
│    t = i / 59              (0.0 → 1.0)
│    camera = sin_orbit(i)   (±30° wave)
│    │
│    ▼
│  ┌──────────────────────────────────────────┐
│  │  Patch XML:                              │
│  │    transition_t = t                      │
│  │    <lookAt origin=.../>  = orbit pos     │
│  │    <string name="filename" .../>  = exr  │
│  └────────┬─────────────────────────────────┘
│           ▼
│  ┌──────────────────────────────────────────┐
│  │  ./build/lajolla frame_NNNN.xml          │
│  │                                          │
│  │  stylized_path_tracing() per pixel:      │
│  │    hit shape_id ∈ target_ids?            │
│  │      NO  → 1-sample PBR (fast)           │
│  │      YES → k-sample ⟨I⟩ then:           │
│  │        final = lerp(PBR, Cel, t)         │
│  └────────┬─────────────────────────────────┘
│           ▼
│    frame_NNNN.exr  →  gamma correct  →  uint8
│
▼
Assemble all frames → transition.gif (imageio)
```

### Object-ID Selective Stylization

```
Camera ray → intersect → shape_id

if target_object_ids is non-empty AND shape_id NOT in target_object_ids:
  → return stylized_inner_trace(vertex)     // single-sample PBR
  → SKIP the k-sample loop entirely         // ~30% faster

else (target object):
  → run k-sample inner estimate ⟨I⟩
  → compute pbr_color = ⟨I⟩
  → compute cel_color = g_θ(albedo, ⟨I⟩)
  → return lerp(pbr_color, cel_color, transition_t)
```

### Camera Orbit

Sinusoidal horizontal wave around the Cornell Box center:

```python
phase = 2π × frame / n_frames
azimuth = base_azimuth + orbit_deg × sin(phase)

origin.x = target.x + radius × sin(azimuth)
origin.z = target.z - radius × cos(azimuth)
origin.y = constant (same height)
```

Default: ±30° arc, one full sin cycle over 60 frames.

### XML Parameters

```xml
<integrator type="stylized_pt">
    <integer name="inner_samples"  value="64"/>
    <float   name="transition_t"   value="0.0"/>     <!-- patched per frame -->
    <string  name="target_ids"     value="6,7"/>     <!-- pillar shape IDs -->
    <float   name="cel_threshold"  value="0.10"/>
    ...
</integrator>
```

### Source Files

| File | Role |
|------|------|
| [stylized_pt_integrator.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/stylized_pt_integrator.h) | Object-ID check, temporal crossfade, PBR fallback |
| [scene.h](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/scene.h) | [transition_t](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/animate_transition.py#91-98), `target_object_ids` in [RenderOptions](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/scene.h#26-50) |
| [parse_scene.cpp](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/src/parsers/parse_scene.cpp) | Parse [transition_t](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/animate_transition.py#91-98), `target_ids` |
| [animate_transition.py](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/final_project/animate_transition.py) | 60-frame orchestrator, XML patching, GIF assembly |
| [cbox_transition.xml](file:///Users/zhuyuezx/Documents/UCSD/Winter_2025/CSE272/lajolla_public/scenes/cbox/cbox_transition.xml) | Colorful scene: gold + blue pillars, red/green walls |

### Run Commands

```bash
# Full 60-frame animation with camera orbit
python3 final_project/animate_transition.py \
  --scene scenes/cbox/cbox_transition.xml \
  --frames 60 --fps 15 --orbit 30 \
  --output transition.gif

# Single test frame (t=0, static camera)
./build/lajolla scenes/cbox/cbox_transition.xml
```

---

## Comparison

| | Pipeline 1: Skypop | Pipeline 2: West (Static) | Pipeline 3: West (Animated) |
|---|---|---|---|
| **Lighting** | Single directional | Full GI (area lights, indirect) | Full GI |
| **Shading** | N·L + hard shadow | k-sample MC → cel step | k-sample MC → lerp(PBR, cel, t) |
| **Bounces** | 0 (primary only) | Unlimited (Russian Roulette) | Unlimited |
| **Color Bleed** | None | Yes (physical) | Yes (physical) |
| **Outlines** | Sobel AOVs | Sobel AOVs | None (raw color) |
| **Cost per pixel** | 1 ray | k × full path trace | target: k × PT; other: 1 × PT |
| **Deterministic** | Yes | No (MC) | No (MC) |
