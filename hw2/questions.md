# Homework 2: Volumetric Path Tracing - Questions

---

## Section 1: Single monochromatic absorption-only homogeneous volume (8%)

### Question 1.1
Change the absorption parameters to zero in `scenes/volpath_test/volpath_test1.xml`. What do you see? Why?

**Answer:** When sigma_a is set to zero, the transmittance becomes exp(-0 * t) = 1 for all distances. This means there is no attenuation at all — light passes through the volume unchanged. The result looks identical to rendering without any volume: the light sources appear at full brightness with no dimming or color shift, as if the medium were vacuum. This is because the absorption coefficient controls how much energy is removed from the light as it travels through the medium, and with it set to zero, no energy is removed.

### Question 1.2
In the homework, we assume the volume being not emissive. If you were tasked to modify the pseudo code above to add volume emission, how would you do it? Briefly describe your approach.

**Answer:** To add volume emission, we would modify the rendering approach in two ways:

1. When sampling a point along the ray (at distance t), in addition to handling surface emission and scattering, we'd also need to evaluate the volumetric emission L_e(p(t)) at that point.

2. The integral becomes: L = ∫_0^t_hit exp(-σ_a * t) * L_e(p(t)) dt + exp(-σ_a * t_hit) * L_surface. We importance-sample the transmittance as before, and when we sample a point at distance t < t_hit, we add the volumetric emission L_e(p(t)) to the contribution (after dividing by the sampling PDF). This emission is additive — we just accumulate it alongside any scattering contribution.

---

## Section 2: Single monochromatic homogeneous volume with single scattering (8%)

### Question 2.1
In the derivation above, how did we get from p(t) ∝ exp(−σ_t * t) to p(t) = σ_t * exp(−σ_t * t)?

**Answer:** We know p(t) ∝ exp(-σ_t * t). To make it a valid probability density, it must integrate to 1 over [0, ∞). We compute:

∫₀^∞ exp(-σ_t * t) dt = 1/σ_t

So the normalization constant is σ_t, giving p(t) = σ_t * exp(-σ_t * t). This is simply the PDF of an exponential distribution with rate parameter σ_t.

### Question 2.2
How was Equation (11) (P(t ≥ t_hit) = exp(−σ_t * t_hit)) incorporated into the pseudo code above? Why is it done this way?

**Answer:** In the pseudo code, when t ≥ t_hit (we hit a surface), the transmittance is exp(-σ_t * t_hit) and the trans_pdf is also exp(-σ_t * t_hit). This is exactly P(t ≥ t_hit) from Equation (11).

The division transmittance/trans_pdf = 1 in this case, so the surface emission contribution is just Le — exactly what we want, since the transmittance to the surface is already accounted for in the probability of reaching the surface. The exponential sampling naturally handles both the volume scattering case (t < t_hit) and the surface hit case (t ≥ t_hit) as a single importance sampling scheme: when we reach the surface, the probability of doing so exactly equals the transmittance, so the Monte Carlo weight becomes 1.

### Question 2.3
Play with the parameters σ_s and σ_a, how do they affect the final image? Why?

- **Increasing σ_a**: The volume becomes more opaque/darker. More light is absorbed as it travels through the medium, reducing brightness overall. The light source behind the volume dims more.
- **Increasing σ_s**: The volume scatters more light. The overall brightness decrease as σ_t increases, but the volume around becomes more visible due to increased scattering.
- **High σ_s, low σ_a**: The volume appears bright and foggy — it scatters a lot of light with little absorption.
- **High σ_a, low σ_s** (low albedo): The volume appears dark and less foggy, and the color around the sphere is much dimmer.

### Question 2.4
Change the phase function from isotropic to Henyey-Greenstein. Play with the parameter g (valid range (-1, 1)). What does g mean? How does the g parameter change the appearance? Why?

The parameter g is the **mean cosine** of the scattering angle, controlling the asymmetry of scattering:
- **g = 0**: Same as the default isotropic phase function.
- **g > 0 (forward scattering)**: Light preferentially scatters in the forward direction. This creates a bright, scattered-spot-like highlights around the center sphere. The cyan color become dominant background color also.
- **g < 0 (backward scattering)**: Light preferentially scatters back toward the source. Overall darker appearance, and purple color becomes dominant background color.
- **|g| close to 1**: Scattering becomes very directional (sharp forward or backward peak).

---

## Section 3: Multiple monochromatic homogeneous volumes with multiple scattering (8%)

### Question 3.1
Play with the parameters σ_s, σ_a of different volumes, and change max_depth. How do they affect the final image? How does increasing/decreasing σ_s and σ_a of medium1 and medium2 affect the appearance, respectively? Why? Do different σ_s and σ_a values affect how high you should set max_depth?

**Answer:** 
- **medium1 (the dense volumetric ball)**: Increasing σ_s makes the ball appear darker, and the overall scene gets more foggy. Increasing σ_a makes the saturation of the ball's color and the whole scene dimmer.
- **medium2 (the ambient/outer medium)**: Increasing its σ_s creates makes the volume more opaque and foggy, while increasing σ_a is kind of similar to increasing σ_s, but it's more like making the volume darker and more uniformly colored.
- **max_depth**: With low max_depth (e.g., 2), only single scattering is captured, so volumes with high albedo (high σ_s / σ_t ratio) will appear artificially dark because the multiply-scattered light is missing. As max_depth increases, the image brightens and converges. High-albedo media require higher max_depth to converge because light bounces many times before being absorbed.
- Yes, different σ_s and σ_a affect how high max_depth should be. Higher albedo (σ_s / σ_t) requires more bounces to converge, because each scattering event preserves most of the energy. For very absorptive media (low albedo), most energy is lost after a few bounces, so low max_depth suffices.

### Question 3.2
Switch to the Henyey-Greenstein phase function again. How does changing the g parameter affect the appearance? Why?

**Answer:** 
- **g > 0 (forward scattering)**: The dense volumetric ball appears brighter and can see highlights at the camera-facing normals. For the ambient foggy medium, it just appears more transparent and less foggy since light travels farther in the forward direction.
- **g < 0 (backward scattering)**: The dense volumetric ball appears dimmer overall, with no highlights. For the ambient medium, it appears slightly more opaque and foggy since light is scattered back toward the source.
- **g = 0**:  No change from the isotropic case.

With multiple scattering, the effect of g is amplified. High forward-scattering g makes the medium appear thinner because light travels farther in the forward direction at each bounce.

### Question 3.3
Propose a phase function yourself (don't have to describe the exact mathematical form). How would you design the shape of the phase function? What parameter would you set to control it?

**Answer:** I would propose a **dual-lobe phase function** that combines a forward-scattering lobe and a backward-scattering lobe, similar to how materials like biological tissue scatter light. The design:

- Two Henyey-Greenstein lobes: one with g_forward > 0 (forward) and one with g_backward < 0 (backward), blended by a weight parameter w ∈ [0, 1]:
  ρ(θ) = w * HG(θ, g_forward) + (1 - w) * HG(θ, g_backward)

Parameters:
- **g_forward** (e.g., 0.8): controls the sharpness of the forward peak
- **g_backward** (e.g., -0.3): controls the backward lobe
- **w** (e.g., 0.7): controls the balance between forward and backward scattering

This is actually the **double Henyey-Greenstein** phase function commonly used in subsurface scattering and cloud rendering. It provides more flexibility than a single HG lobe and can better approximate measured scattering data from real materials.

---

## Section 4: Multiple scattering with NEE + MIS, no surface lighting (8%)

### Question 4.1
When will next event estimation be more efficient than phase function sampling? In our test scenes, which one is more efficient? Why?

**Answer:** NEE is more efficient when:
- **The light source is small**: Phase function sampling has a very low probability of randomly scattering in the exact direction toward a small light, so most samples contribute nothing. NEE directly connects to the light, producing non-zero contributions consistently.
- **The volume is optically thin**: The transmittance to the light is non-negligible, so NEE shadow rays frequently reach the light.

Phase function sampling is more efficient when:
- **The light source is large or surrounds the medium**: Phase function sampling naturally hits the light from many directions.
- **The medium is optically thick**: NEE shadow rays are heavily attenuated, contributing very little.

In our test scenes (volpath_test4.xml), the light source is small, so NEE is significantly more efficient than phase function sampling alone. This is why vol_path_tracing_4 with MIS converges much faster than vol_path_tracing_3, which only uses phase function sampling.

### Question 4.2
In `scenes/volpath_test/volpath_test4_2.xml`, we render a scene with an object composed of dense volume. How does it compare to rendering the object directly with a Lambertian material? Why are they alike or different?

**Answer:** *[EXPERIMENT REQUIRED: Render volpath_test4_2.xml and compare with a Lambertian sphere.]*

Expected: A dense homogeneous volume with high albedo (σ_s ≫ σ_a) looks very similar to a Lambertian diffuse surface. This is because:

- **Similarity**: In a very dense, high-albedo volume, light entering the surface scatters many times within a thin skin layer and exits with a roughly Lambertian angular distribution. This is essentially what the diffusion approximation predicts — for optically thick volumes, the exiting radiance approaches a cosine-weighted distribution, just like a Lambertian surface.
- **Difference**: The volumetric sphere has softer edges and may exhibit slight translucency (subsurface scattering visible at silhouettes). A true Lambertian surface has a sharp boundary. The volumetric sphere may also have a slightly different color saturation because multiply-scattered light undergoes more wavelength-dependent absorption.

This observation is the physical basis for Jim Kajiya's prediction that all rendering could be volume rendering.

### Question 4.3
Jim Kajiya famously has predicted in 1991 that "in 10 years, all rendering will be volume rendering". What do you think that makes him think so? Why hasn't it happened yet?

**Answer:** Kajiya's reasoning was likely:
- Volumes can represent all types of geometry: surfaces are just the limit of infinitely dense volumes. A sufficiently dense volume looks like a solid surface (as shown in Q4.2).
- A single volumetric rendering framework could unify surface rendering, subsurface scattering, atmospheric effects, clouds, fire, etc., eliminating the need for separate algorithms.
- It's physically more accurate — real objects are all 3D, not infinitely thin surfaces.

Why it hasn't fully happened:
1. **Computational cost**: Volume rendering is far more expensive than surface rendering. Delta tracking through dense volumes requires many null-scattering events. Surface rendering with BSDFs is a highly optimized special case.
2. **Hardware acceleration**: GPUs and ray-tracing hardware (e.g., RTX) are optimized for surface intersection, not volumetric sampling.
3. **Memory**: Representing objects as dense volumes requires vastly more memory than triangle meshes.
4. **Convergence**: Volume rendering with multiple scattering needs many more samples to converge than surface-only rendering.

In practice, hybrid approaches dominate: surface rendering for solid objects with volumetric rendering for participating media effects.

---

## Section 5: Multiple scattering with NEE + MIS, with surface lighting (8%)

### Question 5.1
Play with the index of refraction parameter of the dielectric interface in `scenes/volpath_test/volpath_test5_2.xml`. How does that affect appearance? Why?

**Answer:** 
Expected behavior:
- **IOR = 1.0**: The highligh area in the middle disappeared, and the overall sphere becomes brighter and more consistent in color.
- **IOR = 1.33**: Highlight appears at the center with the remaining parts of the sphere slightly darker.
- **IOR >= 1.5**: Even stronger highlight at the center, and the rest of the sphere becomes darker.

Higher IOR increases the Fresnel reflectance, making the center of the sphere (where the ray hits the surface head-on) reflect more light, creating a bright highlight. The rest of the sphere becomes darker because more light is reflected at the surface instead of entering the volume, reducing the amount of light that can scatter inside and exit toward the camera. With IOR = 1.0, there is no reflection at the surface, so all light enters the volume, resulting in a more uniformly bright appearance without a highlight.

### Question 5.2
In the scene `scenes/volpath_test/vol_cbox_teapot.xml`, we model the glass teapot as a transparent glass with blue homogeneous medium inside. What is the difference in terms of appearance between this approach and just making the color of the glass blue without any medium inside?

**Answer:** Key differences:
- **With medium inside**: The blue color depends on **path length** through the volume (Beer's law: exp(-σ_a * t)). Thicker parts of the teapot (body) appear deeper blue, while thinner parts (handle, spout edges) appear lighter/more transparent. The blue color is volumetric — it accumulates with distance. There is also scattering inside, creating soft internal caustics and a glowing quality.
- **Without medium (surface coloring only)**: The blue color is applied uniformly at the surface, regardless of thickness. The teapot body and handle both have the same blue tint. No scattering occurs inside, so the appearance is purely dielectric.

The volumetric approach is physically more accurate for colored glass. Real colored glass gets its color from absorption by dissolved ions/particles, which is inherently a volumetric effect. Thin glass edges should be less saturated than thick glass bodies, and only the medium-based approach captures this.

---

## Section 6: Multiple chromatic heterogeneous volumes (8%)

### Question 6.1
For heterogeneous volumes, what kind of distribution of the volume density makes the null scattering efficient/inefficient? Can you think of a way to improve our current sampling scheme in the inefficient case?

**Answer:** 
- **Efficient case**: When the volume density is relatively **uniform/constant** throughout the domain. In this case, σ_t ≈ σ_m (the majorant) everywhere, so σ_n = σ_m - σ_t ≈ 0. Almost every sampled collision is a real particle, and we rarely waste iterations on null collisions. The extreme case is a homogeneous volume, where null scattering introduces zero overhead.

- **Inefficient case**: When the volume density is **sparse/concentrated** — high density in a small region with near-zero density elsewhere (e.g., a thin wisp of smoke in a large bounding box). The majorant must be set to the maximum density, but most of the volume has σ_t ≪ σ_m. This means σ_n ≈ σ_m almost everywhere, and nearly every collision is null — we waste many iterations stepping through empty space before hitting a real particle.

**Improvement**: Use **spatially varying majorants** instead of a single global majorant. Divide the volume into a spatial acceleration structure (e.g., a grid or octree). Each cell stores a local majorant (the max σ_t within that cell). When delta tracking enters a cell with low density, it uses a small local majorant and takes larger steps. This is called **superimposition** or **residual tracking**. Modern production renderers use this approach (e.g., "brick maps" of majorants) to handle very sparse, high-dynamic-range volumes efficiently.

### Question 6.2
How do we make the null-scattering work for emissive volumes? Briefly describe a solution.

**Answer:** For emissive volumes, the radiative transfer equation has an additional emission term L_e(p(t)):

dL/dt = -σ_t * L + σ_s * ∫ ρ L dω' + L_e

After homogenization with majorant σ_m:

dL/dt = -σ_m * L + σ_n * L + σ_s * ∫ ρ L dω' + L_e

When we delta-track using the majorant, at each sampled collision point, three things can happen:
1. **Real scattering** (prob σ_t/σ_m): Scatter the ray as before, but also add the local emission contribution L_e(p) / σ_m.
2. **Null collision** (prob σ_n/σ_m): Continue in the same direction.
3. At each collision (real or null), we also accumulate the **emission contribution** weighted by the transmittance.

Practically, at each sampled collision point before deciding real/null, we add:
```
radiance += path_throughput * L_e(p) * (transmittance / avg(trans_dir_pdf))
```
Then proceed with the real/null decision. The emission is sampled at every delta-tracking step along the ray, similar to how volume emission is handled in ray marching, but unbiased.

### Question 6.3
Why is it important to have an unbiased solution for volume rendering? Would it be sensible to have something that is biased but faster? How would you do it?

**Answer:** 
**Why unbiased matters:**
- An unbiased estimator converges to the correct answer as samples increase. With biased methods, adding more samples converges to a **wrong** answer (the bias persists). This is especially problematic for reference rendering, validation, and production quality where artifacts from bias can be hard to distinguish from noise.
- In volume rendering specifically, biased transmittance estimation (e.g., from ray marching with finite step size) can cause systematic energy loss or gain, leading to volumes that are consistently too dark or too bright.

**Biased but faster alternatives:**
- **Ray marching** with fixed step size: Evaluate the transmittance by numerical integration (Riemann sum) along the ray. This is biased because the finite step size introduces discretization error, but it's very fast and trivially parallelizable on GPUs. The bias decreases as step size → 0, but never reaches zero for a fixed step size.
- **Track-length estimator**: Estimate the optical depth using a single random sample, then exponentiate it. This is faster (single sample) but biased because E[exp(-X)] ≠ exp(-E[X]).
- **Regular tracking with max iteration cap**: Our current implementation with `max_null_collisions` is technically slightly biased when the cap is hit, but it's a negligible bias in practice.

For real-time or interactive applications, biased ray marching is standard (used in games, medical imaging, etc.). For offline production rendering, unbiased methods are preferred because they allow reliable convergence testing.