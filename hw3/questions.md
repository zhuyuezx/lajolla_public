# Homework 3: Real-time and Production Rendering

This homework explores Unreal Engine and its rendering implementation. No coding component — answers go on Gradescope. An in-person demo/interview is required at office hours.

---

## Section 1: Materials

### Question 1 (6.66%): Create your own material
Create a material and assign it to an object in Unreal Engine. Open an empty games project, drop an object into the scene (e.g., `SM_MatPreviewMesh_01` from engine meshes), and play with its material. Can use the default material system or the newer Substrate material. Requirements:
- Material should have **spatially varying properties** other than just base color.
- Material should have **at least two "layers"** (see Layered Materials documentation for standard materials, or Substrate's documentation for Substrate).
- Free to use procedural textures, engine-provided textures, or downloaded textures (e.g., from Fab).

**Deliverables:** Record a video walkthrough looking around the object. Take screenshots of the material/shader graph.

Basically, I want to create a material that blends metal surface and rust. Where I used "T_Metal_Steel" and "T_Metal_Rust" inside StarterContent. 

For the metal component, I use the interpolated metal texture & normals with linear interpolation plus setting metalic attribute to 1.0. 
For the rust component, I processed texture with fuzzy shading, and add linear interpolation for  roughness.

Then, I use perlin noise plus smoothstep to make shape alpha transition, as the alpha value for matlayerblend_standard to create the illustrated material effects.

### Question 2 (6.66%): Explain material graph design
Briefly explain your design of the material graph. How does the material graph help you design the material? What advantages (or disadvantages) does it have compared to the more fixed function design in lajolla?

**Answer:**

My material graph has two main branches feeding into a `MatLayerBlend_Standard` node:

1. **Metal layer**: Uses `T_Metal_Steel` texture sampled for base color and normals, with linear interpolation (Lerp) applied to blend the textures smoothly. Metallic is set to 1.0 to get a fully metallic look.
2. **Rust layer**: Uses `T_Metal_Rust` texture, processed with a fuzzy shading node to give it a soft, powdery appearance. A Lerp node blends the roughness to make the rust areas rougher than the metal.
3. **Blending**: A Perlin noise function is piped through a SmoothStep node to create an organic, spatially varying alpha mask. This alpha drives the `MatLayerBlend_Standard` node, which blends between the metal and rust layers.

**How the material graph helps:**
- It provides a visual, node-based workflow where you can see the data flow from textures → processing → final output. You can preview intermediate results at any node, making iteration fast.
- It's easy to swap out textures, change blend modes, or add new processing steps without rewriting code.
- The layering system (`MatLayerBlend_Standard`) encapsulates each material layer as a reusable function, promoting modularity.

**Advantages over lajolla's fixed-function design:**
- **Flexibility**: In lajolla, each material (Lambertian, RoughPlastic, DisneyBSDF, etc.) is a hard-coded C++ struct with fixed parameters. Adding a new material requires modifying source code, adding a variant type, and implementing `eval`/`sample_bsdf`/`pdf_sample_bsdf`. In UE's shader graph, you can combine arbitrary operations without touching engine code.
- **Spatial variation**: In lajolla, spatial variation is limited to what the `Texture<T>` parameters support. In UE, you can procedurally generate any spatial pattern (noise, masks, etc.) and route it to any parameter.
- **Artist-friendly**: Non-programmers can create complex materials visually.

**Disadvantages:**
- **Physical accuracy**: The shader graph prioritizes real-time performance and artistic control over physical correctness. Layering in UE is alpha-blending of shading model outputs, not a physically based multi-layer BSDF simulation. Lajolla's fixed-function materials (e.g., RoughPlastic with a dielectric coating over diffuse) have clearer physical semantics.
- **Debugging**: Complex shader graphs can become hard to follow ("spaghetti nodes"), whereas lajolla's explicit C++ code is easier to reason about mathematically.
- **Performance constraints**: Shader graphs must compile to GPU-efficient code, limiting the complexity of light transport (e.g., no inter-layer multiple scattering).

### Question 3 (6.66%): Layered Materials vs. layered BSDFs
Are the *Layered Materials* in UE the same as the layered BSDFs discussed in class? If they are different, what are the differences?

**Answer:**

No, they are fundamentally different.

**Layered BSDFs (from class):** These model physically stacked layers of materials (e.g., a dielectric coating on top of a diffuse substrate, as in lajolla's `RoughPlastic`). Light interacts with each layer according to physics: it may reflect off the top layer, transmit into the next layer via Fresnel equations, scatter internally, and bounce between layers multiple times. The resulting BSDF is the combined effect of all these inter-layer light transport events. This is physically based but computationally expensive (especially with multiple scattering between layers).

**Layered Materials (UE):** These are an **artist-driven blending system**, not a physical simulation of stacked layers. `MatLayerBlend_Standard` (and similar nodes) take two complete material layers and blend their final shading attributes (base color, roughness, metallic, normals, etc.) using an alpha mask. This is essentially a per-pixel linear interpolation: `output = lerp(layer_A, layer_B, alpha)`. There is no simulation of light bouncing between layers — it's a flat blend of surface properties.

**Key differences:**
1. **No inter-layer light transport**: UE's layered materials don't simulate Fresnel-dependent reflection/transmission between layers. A physically layered BSDF would show view-angle-dependent layer visibility (e.g., more coating reflection at grazing angles).
2. **Alpha blending vs. physical stacking**: UE blends attributes; physical layering composes BSDFs. For example, a clear coat over paint in UE might use alpha blending, while a physical model would add a specular lobe on top of the diffuse lobe with energy conservation between them.
3. **Performance**: UE's approach is GPU-friendly (just interpolation), while physical multi-layer BSDFs require iterative evaluation or precomputed lookup tables.
4. **Energy conservation**: Physical layered BSDFs maintain energy conservation by construction (light reflected by the top layer is not available to the bottom layer). UE's alpha blending does not enforce this — it's up to the artist to set reasonable values.

### Question 4 (6.66%): UE5 BSDFs — DefaultLitBxDF
Read the Unreal Engine 5 source code and figure out what kind of BSDFs they used.
We will focus on the standard materials for the following questions. They are defined in IntegrateBxDF() in
UnrealEngine/Engine/Shaders/Private/ShadingModels.ush1. Read the DefaultLitBxDF()routine and explain
what they do. A high-level explanation is suﬃcient, no need to go to the nitty-gritty details. Ignore the
clearcoat, subsurface, hair, cloth, and eye materials for now.

**Answer:**

**BSDFs used in UE5 (`IntegrateBxDF()` dispatch):**

`IntegrateBxDF()` dispatches to different BxDF routines based on the shading model ID stored in the GBuffer. The shading models (each with their own BxDF) include:
- **Default Lit** (`DefaultLitBxDF`) — standard PBR (diffuse + GGX specular), the main workhorse
- **Subsurface** (`SubsurfaceBxDF`) — adds transmission/subsurface scattering
- **Preintegrated Skin** (`SubsurfaceBxDF` variant) — skin-specific subsurface
- **Clear Coat** (`ClearCoatBxDF`) — adds a second specular lobe for clear coat layer
- **Hair** (`HairBxDF`) — Marschner-based hair fiber scattering (covered in Q5)
- **Cloth** (`ClothBxDF`) — fabric-specific shading with sheen
- **Eye** (`EyeBxDF`) — specialized eye shading with iris refraction
- **Subsurface Profile** (`SubsurfaceProfileBxDF`) — profile-based subsurface scattering
- **Two Sided Foliage** (`DefaultLitBxDF` + transmission) — thin translucent vegetation
- **Single Layer Water** — water surface shading
- **Thin Translucent** — thin translucent surfaces

**`DefaultLitBxDF()` explanation:**

`DefaultLitBxDF()` returns an `FDirectLighting` struct with three independent channels (`Diffuse`, `Specular`, `Transmission`) — they are not combined inside the function.

If `NoL <= 0` (light below horizon), all outputs stay zero and the struct is returned early. Otherwise:

1. **Context setup**: Initializes geometric dot products (NoV, VoH, NoH) from N, V, L. Supports anisotropic materials (adds tangent/bitangent) and adjusts for spherical area lights via `SphereMaxNoH()`.

2. **Diffuse**: `Diffuse_Lambert()` by default, or `Diffuse_GGX_Rough()` when `MATERIAL_ROUGHDIFFUSE` is enabled. Scaled by `FalloffColor * Falloff * NoL`.

3. **Specular**: GGX microfacet via `SpecularGGX()`, with three paths — anisotropic GGX, `RectGGXApproxLTC` for rect area lights, or standard isotropic GGX. Scaled by the same attenuation.

4. **Energy corrections**: `ComputeEnergyPreservation()` attenuates diffuse for energy already reflected by specular; `ComputeEnergyConservation()` boosts specular to recover energy lost to microfacet multi-scattering.

5. **Transmission**: Always 0 for default lit.

### Question 5 (6.66%): HairBxDF
Continue on above, read the HairBxDF routine (which will lead you to the HairShading routine in `UnrealEngine/Engine/Shaders/Private/HairBsdf.ush`) and explain what it does. Again, a high-level explanation is good enough.

If you are interested, you can continue reading on other materials including Clearcoat and Cloth, but we do not grade them.

**Answer:**

`HairBxDF` in `ShadingModels.ush` calls `HairShading()` and puts the entire result into `Lighting.Transmission` (with `Diffuse` and `Specular` set to 0), since hair scattering doesn't decompose neatly into conventional diffuse/specular.

`HairShading()` in `HairBsdf.ush` implements an approximation of the **Marschner hair model** ([Marschner et al. 2003] and [Pekelis et al. 2015]). It models a hair fiber as a dielectric cylinder (IOR n=1.55) and sums three scattering lobes:

1. **R (Reflection)**: Specular reflection off the cuticle surface. Computed as `Mp * Np * Fp`, where `Mp` is a Gaussian longitudinal distribution (`Hair_g`), `Np = 0.25 * CosHalfPhi` (simplified azimuthal), and `Fp` is Schlick Fresnel. The cuticle tilt shift `Alpha[0] = -2*Shift` offsets the highlight toward the hair root.

2. **TT (Transmission-Transmission)**: Light enters the fiber, is absorbed by pigment, and exits the other side. Uses `Fp = (1-f)²` for double Fresnel transmission, and `Tp = exp(-AbsorptionColor * ...)` for Beer's law absorption through the fiber interior (derived from `BaseColor`). The azimuthal term `Np = exp(-3.65*CosPhi - 3.98)` is a fitted approximation concentrating light in the forward direction. Responsible for the backlit glow effect.

3. **TRT (Transmission-Reflection-Transmission)**: Light enters, reflects internally, and exits. Uses `Fp = (1-f)² * f` and stronger absorption `Tp = pow(BaseColor, 0.8/CosThetaD)`. The azimuthal `Np = exp(17*CosPhi - 16.78)` produces a secondary colored highlight (the hair "glint").

Each lobe has its own roughness: `B[0] = roughness²`, `B[1] = roughness²/2` (sharper TT), `B[2] = roughness²*2` (broader TRT).

Finally, if multi-scattering is enabled, the result is wrapped with `EvaluateHairMultipleScattering()` (global/local scattering approximation) and a Kajiya-Kay diffuse term is added for soft fill lighting.

**Virtual Texturing context:** In modern real-time rendering, textures are often computed on-the-fly and cached as needed. Read the [virtual texturing](https://dev.epicgames.com/documentation/en-us/unreal-engine/virtual-texturing-in-unreal-engine), [runtime virtual texturing](https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine), and [streaming virtual texturing](https://dev.epicgames.com/documentation/en-us/unreal-engine/streaming-virtual-texturing-in-unreal-engine) documentation pages. Also see [Ben Cloward's video](https://www.youtube.com/watch?v=SxQ1oOaaoT8).

### Question 6 (6.66%): Runtime virtual texturing
Turn on runtime virtual texturing for your material. Show the performance difference by pressing `` ` `` and input `stat unit`. For the virtual texturing statistics, you can press `` ` `` and input `stat virtualtexturing`.

**Bonus (ungraded):** Modify your scene and materials until runtime virtual texturing gives an observable difference in the performance (you may need to significantly increase the complexity of the shaders and/or to assign materials to the terrain as well). Did you observe performance difference after turning runtime virtual texturing on? Why or why not? When do you expect runtime virtual texturing to bring performance gain?

**Answer:** *[EXPERIMENT REQUIRED: Need to turn on RVT in UE5 editor, capture `stat unit` and `stat virtualtexturing` screenshots with and without RVT enabled, and compare performance numbers.]*

Expected observations: For a simple scene with just one object and a few textures, runtime virtual texturing is unlikely to show a meaningful performance improvement — it may even add slight overhead due to the virtualization bookkeeping. RVT shines in complex scenes with many expensive material layers blended on large surfaces (e.g., terrain with 10+ texture layers). In those cases, RVT caches the final composited result into a virtual texture, so the GPU only evaluates the expensive material graph once per visible texel rather than every frame. You would expect RVT to bring performance gain when:
- Materials have many layers and complex blending operations
- Large surfaces (terrain) with many overlapping material layers
- The camera is relatively stationary (cached tiles remain valid)

### Question 7 (6.66%): Streaming vs. runtime virtual texturing
What are the differences between streaming virtual texturing and runtime virtual texturing? For what kind of textures/materials would you use runtime virtual texturing, and for what kind would you use streaming virtual texturing?

**Answer:**

**Streaming Virtual Texturing (SVT):**
- Deals with **loading texture data from disk to GPU memory on demand**. Instead of loading all texture mip levels into VRAM, only the tiles (pages) that are actually visible at the needed resolution are streamed in.
- The key problem it solves is **memory**: a large open world may have hundreds of GB of texture data, but only a fraction is visible at any time. SVT virtualizes the texture memory so only needed tiles reside in VRAM.
- The textures are **pre-authored** assets stored on disk (e.g., baked lightmaps, photographed textures, pre-composited terrain textures).

**Runtime Virtual Texturing (RVT):**
- Deals with **caching the results of expensive material evaluation** into a virtual texture at runtime. Instead of re-evaluating a complex material shader every frame, the result is rendered into cached VT pages.
- The key problem it solves is **shader cost**: when a material has many layers and complex blending, evaluating it every pixel every frame is expensive. RVT evaluates the material once per visible texel and caches it.
- The textures are **generated at runtime** by the GPU, not pre-existing on disk.

**When to use each:**
- **SVT**: For large pre-authored textures that don't fit in VRAM — e.g., uniquely painted textures across a large world, baked lightmaps, mega-textures, high-res photogrammetry textures.
- **RVT**: For materials with many blended layers computed at runtime — e.g., terrain with 8-16 landscape layers (grass, dirt, rock, snow) blended together with height-based blending, or any surface where the final appearance is procedurally composed from multiple inputs. The material evaluation is expensive but the result changes infrequently.

### Question 8 (6.66%): Implementing streaming virtual texturing in lajolla
If you were to implement streaming virtual texturing inside lajolla (on CPUs), how would you do it? A high-level plan is sufficient.

**Answer:**

High-level plan for CPU-based streaming virtual texturing in lajolla:

1. **Tile all mip levels**: Pre-process each texture's entire mipmap pyramid into fixed-size tiles (e.g., 128×128). Every mip level — from the full-resolution mip 0 down to the 1×1 coarsest level — is subdivided into tiles. Mip 0 has the most tiles; coarser mips have fewer. Store all tiles on disk in a format allowing random access by (mip level, tile x, tile y).

2. **Page table**: Maintain a page table that maps virtual tile coordinates (mip level, tile x, tile y) → physical memory location. This is the core indirection: texture lookups go through the page table rather than accessing a monolithic texture array.

3. **Mip level selection via ray differentials**: When a ray hits a surface, use ray differentials to compute the texture footprint and determine the appropriate mip level. This decides which mip's tiles need to be loaded — coarse footprint → coarse mip (fewer, smaller tiles), fine footprint → fine mip (more tiles but only for visible regions).

4. **On-demand tile loading**: When a texture lookup requires a tile not yet in memory, load it from disk and update the page table. If memory is limited, evict least-recently-used tiles. If a fine-mip tile isn't available yet, fall back to a coarser-mip tile (which covers the same region with fewer pixels) — since all mip levels are tiled, there's always a coarser tile to fall back on.

The key idea is that by tiling every mip level independently, we only need to load the specific tiles at the specific mip levels that are actually accessed during rendering, rather than loading entire textures into memory.

---

## Section 2: Temporal Antialiasing and Upscaling

**Setup:** Build a dynamic scene with complex edges. Download free tree models from Fab (e.g., "Trees Red Oak Tree" for UE5 using `SM_Northern_Red_Oak_12`, or "European Hornbeam" for UE4 using `SM_EuropeanHornBeam_Field_01`). Tune up wind speed in materials.

**Experiment:** Click play, inspect moving trees, press `` ` `` for console. Try combinations of:
- `r.screenPercentage`: values 100, 75, 50, 25
- `r.AntiAliasingMethod` (UE5): values 0, 2, 4
- `r.DefaultFeature.AntiAliasing` (UE4): values 0, 2

### Question 9 (6.66%): r.screenPercentage
Explain what `r.screenPercentage` does. In UE5, you can hover to the command
with your mouse cursor to inspect. In UE4, you can to go to Windows → Developer Tools → Output Log
and turn on the console output. Then type `r.screenPercentage ?` to see the explanation of the command. If
you were tasked to implement `r.screenPercentage 50` in lajolla (without temporal antialiasing), how would
you do it? A brief explanation is fine.

**Answer:**

`r.screenPercentage` controls the internal rendering resolution as a percentage of the final display resolution. At 100, the scene renders at full resolution. At 50, the scene renders at 50% width and 50% height (i.e., 25% total pixels), and the result is upscaled to fill the display. This reduces GPU workload at the cost of image sharpness.

To implement `r.screenPercentage 50` in lajolla: render the image at half the camera width and height (i.e., set `w = scene.camera.width / 2`, `h = scene.camera.height / 2`), trace rays at this lower resolution, then upscale the resulting image to the original resolution using bilinear interpolation (or nearest-neighbor for simplicity) before saving. No temporal accumulation is involved — just render fewer pixels and scale up.

### Question 10 (6.66%): AntiAliasingMethod values
Explain what `r.AntiAliasingMethod` (or `r.DefaultFeature.AntiAliasing`) does for different parameter values. Try using value 3. Did the output change? Why or why not?

**Answer:**

`r.AntiAliasingMethod` selects the anti-aliasing algorithm:
- **0**: None — no anti-aliasing. Raw aliased edges visible.
- **1**: FXAA (Fast Approximate Anti-Aliasing) — a post-process filter that detects and smooths edges in screen space. Cheap but can blur fine detail.
- **2**: TAA (Temporal Anti-Aliasing) — jitters the camera sub-pixel position each frame and blends with previous frames using motion vectors. Good quality, handles sub-pixel detail, but can introduce ghosting on fast motion.
- **3**: MSAA (Multi-Sample Anti-Aliasing) — not supported in UE5's deferred rendering pipeline (only works with forward rendering). *[EXPERIMENT REQUIRED: Confirm whether setting value 3 changes the output or is silently ignored/falls back.]*
- **4**: TSR (Temporal Super Resolution, UE5 only) — UE5's built-in temporal upscaler. Similar to TAA but designed to also upscale from lower internal resolution, producing higher quality results at reduced screen percentages.

Setting value 3 (MSAA) likely produces no change because UE5 uses deferred shading by default, and MSAA is only available with the forward rendering path. The engine silently ignores or falls back to another method.

### Question 11 (6.66%): Visual differences
Describe the visual differences between different settings. Which setting do you prefer the most? Why?

**Answer:** *[EXPERIMENT REQUIRED: Need to observe and describe visual differences across the combinations of r.screenPercentage (100/75/50/25) and r.AntiAliasingMethod (0/2/4) in UE5.]*

Expected observations:
- **No AA (0) + 100%**: Sharp but jagged edges, visible staircase aliasing on tree branches and leaves.
- **No AA (0) + lower screen %**: Same aliasing plus blurriness from upscaling. Very poor quality.
- **TAA (2) + 100%**: Smooth edges, good quality, but possible slight ghosting/blurring on fast-moving leaves.
- **TAA (2) + lower screen %**: Increasing blur as screen percentage drops. TAA tries to recover detail but can't fully compensate for the reduced resolution.
- **TSR (4) + 100%**: Similar to TAA but slightly sharper.
- **TSR (4) + lower screen %**: Noticeably better than TAA at low screen percentages — TSR is designed for temporal upscaling, so it recovers more detail. At 50% it may look nearly as good as TAA at 100%.

Preferred: TSR (4) at 75-100% screen percentage — best balance of quality and performance. TSR maintains sharp detail even at reduced resolution, with fewer ghosting artifacts than TAA.

### Question 12a (6.66%) — UE4 only: Motion vector visualization
Turn on motion vector visualization: `ShowFlag.VisualizeMotionBlur 1`. Move camera around. Turn off with `ShowFlag.VisualizeMotionBlur 2` (or 0). How were these motion vectors used in temporal antialiasing? If you got blurry results earlier, does this visualization explain them? Why?

**Answer:**

Motion vectors store per-pixel screen-space displacement between the current and previous frame. TAA uses them to **reproject** — for each pixel in the current frame, the motion vector tells TAA where that pixel was in the previous frame, so it can blend the current sample with the correct historical sample.

If earlier results were blurry, the motion vector visualization can explain it: large motion vectors (bright colors) indicate fast movement. When motion vectors are large or inaccurate (e.g., on thin geometry like tree branches where motion estimation is unreliable), TAA blends with wrong historical pixels, causing ghosting and blur. Areas with small/zero motion vectors (dark regions) should appear sharp.

### Question 12b (6.66%) — UE5 only: Motion vector & reprojection visualization
Turn on `ShowFlag.VisualizeMotionBlur 1` and move camera around. Turn off with value 2 or 0. Also turn on `ShowFlag.VisualizeReprojection 1` and move camera around. Explain what `VisualizeReprojection` is visualizing and how it differs from motion vector visualization. If you wanted to tweak your TAA algorithm, how would you use these two visualizations?

**Answer:** *[EXPERIMENT REQUIRED: Need to enable both visualizations in UE5 and observe.]*

- **VisualizeMotionBlur** shows per-pixel **motion vectors** — the screen-space displacement of each pixel between frames. It visualizes *how much* and *in what direction* each pixel moved. Bright = large motion, dark = static.

- **VisualizeReprojection** shows the **reprojection confidence/error** — how successfully the temporal upscaler was able to find and reuse historical data for each pixel. According to UE5 documentation, it visualizes areas where reprojection failed or was unreliable (e.g., disoccluded regions that were hidden last frame, or areas where motion vectors are inaccurate). Red/bright areas = reprojection failed (new data needed), dark/green = successful reuse.

**Key difference**: Motion vectors show *raw pixel movement*, while reprojection shows the *outcome* of using those motion vectors — whether the historical data lookup actually succeeded.

**How to use for TAA tuning**:
- **Motion vectors**: Identify regions with large or erratic motion — these need aggressive neighborhood clamping or rejection to avoid ghosting.
- **Reprojection**: Identify where the algorithm is failing to reuse history. If large areas are red (failed reprojection), the current frame must fill in those pixels without temporal data, requiring better fallback strategies (e.g., spatial filters, wider jitter patterns).

---

## Section 3: (Dynamic) Global Illumination

**Setup:** For UE4, disable static lighting (Edit → Project Setting, uncheck Allow Static Lighting; in World Setting turn on Force No Precomputed Lighting). Change GI method via Edit → Project Setting → search "global illumination". Create a scene where indirect illumination effect is significant.

### Question 13 (6.66%): Screen-space GI vs. Lumen — disappearing indirect illumination
The handout shows 4 renderings comparing screen-space GI and Lumen. In the close-up views, indirect illumination disappears in screen-space GI but not in Lumen. Why?

**Answer:**

Screen-space GI (SSGI) can only compute indirect illumination from surfaces that are **visible on screen**. It works by tracing rays in the screen-space depth buffer — if a surface isn't rendered in the current frame (off-screen, occluded, or behind the camera), SSGI has no information about it and cannot bounce light from it.

In the close-up views, the camera has moved closer, causing the light-emitting surfaces (walls, floor, etc.) that were producing indirect illumination to move **off-screen**. Since SSGI can't see them anymore, their indirect light contribution vanishes entirely.

Lumen does not have this limitation because it uses **world-space data structures** (signed distance fields, surface cache, voxel lighting) to represent scene geometry and lighting. Even when a surface is off-screen, Lumen still knows it exists and can bounce light from it. The indirect illumination is computed in 3D world space, not limited to what the camera currently sees.

### Question 14 (6.66%): SSGI noise vs. Lumen
In the far views, SSGI's rendering appears noisier than Lumen. What could be the reason? (Open question — make your best guess.)

**Answer:**

Possible reasons SSGI is noisier:

1. **Limited sample count**: SSGI traces rays in screen space per frame with a small number of samples per pixel (for real-time performance). Each sample may hit or miss relevant surfaces stochastically, producing noisy estimates of indirect illumination. Lumen, by contrast, caches indirect lighting in persistent world-space data structures (surface cache, radiance cache) that accumulate over multiple frames, effectively averaging out noise over time.

2. **Screen-space depth buffer limitations**: SSGI rays march through a 2.5D depth buffer, which is an incomplete representation of the scene. Rays can miss surfaces due to self-occlusion, thin features, or surfaces at grazing angles, causing inconsistent hit/miss results across neighboring pixels — manifesting as spatial noise.

3. **No temporal caching of indirect light**: While SSGI may use some temporal filtering, it fundamentally recomputes indirect lighting from the current frame's screen data each time. Lumen maintains a persistent radiance cache and surface cache that smooth out temporal variations, producing more stable (less noisy) results.

### Question 15 (6.67%): Break the GI algorithm!
Create a scene that makes the dynamic GI algorithm produce undesirable artifacts. For UE4, use Light Propagation Volume. For UE5, use Lumen. Anything you don't like counts as undesirable (even if physically correct). Take a screenshot (or video for temporal artifacts). Explain what is wrong and guess why the artifacts are produced.

**Answer:** *[EXPERIMENT REQUIRED: Need to create a scene in UE5 that produces Lumen artifacts and take screenshots.]*

Suggested approaches to break Lumen (try one or more):

1. **Small emissive details / thin geometry**: Place small bright emissive objects or very thin walls. Lumen uses mesh distance fields and a surface cache with limited resolution — small or thin objects may be poorly represented, causing light leaking through thin walls or missing indirect illumination from small emitters.

2. **Fast-moving light source**: Move a point light quickly through the scene. Lumen's radiance cache updates asynchronously over several frames. Fast light changes cause visible temporal lag — the indirect illumination "ghosts" behind the light position, taking noticeable time to catch up.

3. **Light leaking through walls**: Place a very bright light on one side of a thin wall. Lumen's SDF representation may not fully capture the wall's thickness, causing indirect light to bleed through to the other side.

4. **Concave corners / small cavities**: Create a scene with many small concavities. Lumen's probe/voxel resolution may be too coarse to resolve the indirect illumination correctly in tight spaces, producing dark splotches or incorrect color bleeding.

For the answer, describe: what the artifact looks like, and a guess for why (e.g., "light leaks through the thin wall because Lumen's SDF approximation smooths out the thin geometry, allowing rays to pass through").
