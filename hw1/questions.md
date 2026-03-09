# Homework 1: Disney Principled BSDF - Questions

Answer these questions on Gradescope. As long as you say something plausible, you will get full scores. Some questions do not have a single correct answer. Do think hard about the questions though - the goal is to understand the high-level concepts.

---

## 1. Diffuse (7%)

### Question 1.1
Compare the two BRDFs `f_baseDiffuse` and `f_subsurface` with a Lambertian BRDF (try to render images with all three BRDFs): what differences do you see? Why?

**Answer:** First, for the fundemental Lambertian BRDF, its color remain consistent in the center of the sphere while the slightly get darker at the rim, which resembles the cosine property of the Lambertian BRDF. 

Then, for the base diffuse BRDF, its color is more consistent than the fundemental Lambertian BRDF, and brighter at the rim than the lambertian BRDF. I think this is because two schlick terms multiplied on the lambertian BRDF, making the BRDF diffused at the rim.

For the subsurface BRDF, it is slightly darker at the central part and brighter at the rim than the lambertian and base diffuse BRDFs. This difference is because of the lommel-seeliger term in the subsurface BRDF.


### Question 1.2
Play with the roughness parameter: how does it affect the appearance?

**Answer:** The higher the roughness, the brighter the surface appears in the rim, and slightly darker at the center.


### Question 1.3
Compare the base diffuse BRDF (`f_baseDiffuse`) with the subsurface BRDF (`f_subsurface`) by playing with the subsurface parameter. What differences do you see? Why? In what lighting condition does the base diffuse BRDF differ the most from the subsurface BRDF? (Play with the light position in `simple_sphere.xml` for your experimentation)

**Answer:** When subsurface gradually increases, the sphere become dimmer at the center and brighter at the rim. This is caused by the mixing two BRDFs, one has subsurface property and the other has base diffuse property. When subsurface is 0, the sphere is pure base diffuse. When subsurface is 1, the sphere is pure subsurface.

For the lighting condition, two BRDFs differ most under grazing lighting angles. While f_baseDiffuse (especially at lower roughness) tends to darken at grazing angles due to the Fresnel factor (simulating a "Fresnel shadow"), f_subsurface exhibits a "much stronger Fresnel peak" and maintains brightness at the edges


### Question 1.4 (Optional, bonus 3%)
Another popular option for modeling diffuse surfaces is the Oren-Nayar BRDF, which is used in the Autodesk's Standard Surface BSDF. What is the difference between the Oren-Nayar BRDF and the Disney diffuse BRDF? What are the pros and cons? What is your preference?

**Answer:** 
1. Oren-Nayar is based on geometry/physics. Disney Diffuse is a heuristic designed to match artist intuition and measured data.
2. Since Oren-Nayar assumes microfacets are little lambertian surfaces, it's more suitable for rough matte surfaces. For Disney Diffuse, while it's less physics-based, it's more artist-friendly and can simulate a wider range of materials.

Oren-Nayar Pros:
- Physically correct for specific material types

Oren-Nayar Cons:
- Less artist-friendly
- Less suitable for smooth surfaces


---

## 2. Metal (7%)

### Question 2.1
Compare `DisneyMetal` with the `roughplastic` material (try to render images with both BRDFs). What differences do you see? Why?

**Answer:** DisneyMetal is completely specular while roughplastic is not. When using DisneyMental as texture for simple sphere, only highlight part of the sphere is visible and other parts are completely dark. For roughplastic, the highlight is obvious, but other parts are evenly lit. I think this is because DisneyMetal has no diffuse component. For roughplastic, it seems to be dielectric coating a diffuse base, so it has both specular and diffuse components. 


### Question 2.2
Change the roughness parameters. Apart from how specular the surface is, do you observe any other differences?

**Answer:** With lower roughness, the highlight is more centered and brighter. With higher roughness, the highlight is more spread out and dimmer. When the roughness is over 0.5, the highlight is not that obvious and the whole sphere is all visible. Also, the spreading of highlight from 0 to 1 is not linear, and it's greatly spreaded out when roughness is close to 1.


### Question 2.3
A popular alternative over the Trowbridge-Reitz normal distribution function is the Beckmann distribution (a Gaussian distribution on the slopes h_z^l/h_x^l and h_z^l/h_y^l of the normals). What are the differences between Trowbridge-Reitz and Beckmann? Why did Disney folks choose to use Trowbridge-Reitz instead of Beckmann? (You might want to read the awesome article [Slope Space in BRDF Theory](https://www.reedbeta.com/blog/slope-space-in-brdf-theory/) from Nathan Reed.)

**Answer:** The Beckmann distribution assumes the microfacet slopes follow a Gaussian distribution, whereas the Trowbridge-Reitz (GGX) distribution follows a Student-t distribution.

This is because GGX resembles the real world more, and real world normal distributions are more long-tailed than student-t distributions.


### Question 2.4 (Optional, bonus 3%)
What are the pros and cons of the Schlick approximation compared to the actual Fresnel equation? What is your preference? (You may want to read/watch the Naty Hoffman presentation mentioned in the handout.)

**Answer:** 
Pros:
- Original Fresnel equation requires several steps of trigonometric operations, which is expensive, and Schlick's approximation is much faster and an accurate approximation in most cases.
Cons:
- Schlick's approximation is not accurate when the angle is close to 90 degrees, where eta/eta_t is close to 1.

Preference: Just use Schlick's approximation in most cases, and when it's necessary to use the original Fresnel equation, use it. Also, we can use Schlick's approximation as default, and when there any problem identified, we can switch to the original Fresnel equation.


---

## 3. Clearcoat (7%)

### Question 3.1
Compare `DisneyClearcoat` with `DisneyMetal` using similar roughness. What differences do you see? Where do the differences come from?

**Answer:** I'm not sure how to make the roughness similar as clearcoat only depends on clearcoat_gloss, so I just set roughness of metal to 0.25 since clearcoat has fixed roughness in Gc for 0.25.

In this case, the clearcoat's highlight is more centered but dimmer than metal's highlight. Also, the clearcoat's highlight appears to be a soft glow around the center, while the metal's highlight appears to be a strip-like highlight.

I think the difference come from the more long-tailed distribution of GGX, so it spreads the light more with less intensity in the center. Also, due to eqaution difference, the overall brightness of clearcoat is lower than metal.


### Question 3.2
For coating, Autodesk Standard Surface uses a standard Trowbridge-Reitz microfacet distribution, instead of the modified normal distribution function proposed by Burley. What are the pros and cons? What is your preference?

**Answer:** Standard GGX Pros:
- It is a physically-based model derived from a clear geometric definition (ellipsoid microfacets). It allows for robust sampling techniques, such as visible normal sampling
Cons:
- It fails to capture the "heavy tail" look observed in certain real-world measured materials

My Preference: I am more inclined to the visual representation quality, and also for many cases being realistic is not the sole standard of rendering, Burley's modification that makes presentation easier is more preferable for me.


### Question 3.3
Why do Burley limit the clearcoat BRDF to be isotropic?

**Answer:**
I've come up with two points:
1. Physical Intuition: The clearcoat component represents a "glass-like coating on the surface" (e.g., varnish, lacquer, or water). In the real world, these liquid-applied top coats naturally self-level due to surface tension, resulting in a smooth, isotropic surface, even if the material underneath (like carbon fiber or brushed metal) is anisotropic.
2. Parameter Reduction: The Disney BSDF design principle is to be "artist-friendly" with intuitive parameters. Since the underlying layers (Metal/Diffuse) already support anisotropy, adding anisotropy to the secondary clearcoat lobe would add complexity with diminishing visual returns for most common materials.

---

## 4. Glass (7%)

### Question 4.1
Why do we take a square root of `baseColor` in the refractive case?

**Answer:** We take the square root because light transmitting through a solid glass object typically passes through two interfaces. If the artist specifies baseColor as the desired transmission color of the object, the system assumes this is the result of the light passing through both surfaces. Therefore, the attenuation at each individual interface must be sqrt(baseColor) so that the total attenuation becomes sqrt(baseColor) * sqrt(baseColor) = baseColor.


### Question 4.2
Play with the index of refraction parameter η (the physically plausible range is [1, 2]). How does it affect appearance?

**Answer:**
1. Increasing η increases the bending of light (Snell's Law). A high η will cause the background seen through the object to be more distorted and the rays to be more concentrated, whereas an η near 1 will result in little to no distortion, and it will just act as a transparent object.
2. Increasing η increases the surface reflectivity. High η results in a shinier, more "metallic-looking" reflection at normal incidence, while η close to 1 has almost no reflection at normal incidence


### Question 4.3
If a refractive object is not a closed object and we assign it to be a glass BSDF, will everything still work properly? Why? Propose a solution if it will not work properly (hint: you may want to read the thin-surface BSDF in Burley's note).

**Answer:**
I think it won't work correctly. This is because disney glass BSDF assumes that there's a clear definition of outside and inside, but for a non-closed object, it's not clear where the inside and outside are. The ray will refract upon entering but never refracted back out.

One solution I've found is to use a thin-surface BSDF. It computes the aggregate reflection and transmission but passes the transmitted ray through in a straight line to simulate a thin sheet without requiring closed geometry.

### Question 4.4 (Optional, 3%)
Replace the dielectric Fresnel equation with a Schlick approximation (see Burley's course notes on the fix to the Schlick approximation to make it work for η < 1). Do you observe any differences when η=1.5? What about η=1.01?

**Answer:**
- η=1.5: There's no distinguishable difference. The Schlick approximation was designed to fit standard dielectrics like glass well, it should be visually similar to the full Fresnel equation.
- η=1.01: There's an obvious difference. The Burley notes highlight that Schlick's approximation fails catastrophically when the Index of Refraction (IOR) ratio is close to 1 (e.g., ice in water, or very subtle transitions). At η≈1, Schlick's approximation predicts a specular highlight that can be "nearly 40 times too bright" compared to the physically correct Fresnel equation.

---

## 5. Sheen (7%)

### Question 5.1
Render the `simple_sphere` scene with the sheen BRDF. What do you see? Why? What happens if you change the position of the light source?

**Answer:**
When placing the light source at the same axis of the camera (which is the default setting), I can hardly see the object and the whole screen is dark. 

Then, when moving the light source to the top or bottom of the camera, I can see the object and the sheen effect is visible. 
I see a soft, glowing highlight primarily at the grazing angles (edges/rim) of the sphere, appearing like a "halo" or "fuzz". The center of the lit area appears darker compared to the edges. This creates a "velvet-like" cloth appearance.


### Question 5.2
Play with the parameter `sheenTint`, how does it affect the appearance? Why?

**Answer:**
I noticed that sheenTint controls the color of the grazing sheen highlight.
- When sheenTint is 0, the sheen highlight is white, regardless of the material's base color.
- When sheenTint is 1, the sheen highlight takes on the hue and saturation of the material's baseColor

Physically, simple specular reflection from dielectrics is usually white. However, the sheen component models retro-reflection from the mesostructure of cloth (fibers and weaves). As light bounces between these colored fibers, it picks up the material's color. The sheenTint parameter allows artists to fake this complex volumetric scattering effect: enabling a transition from a "dusty" white fuzz (tint=0) to a "rich" colored velvet (tint=1)


### Question 5.3
In Autodesk Standard Surface, the sheen is modeled by a microfacet BRDF. What are the pros and cons between the Autodesk approach and the Disney approach? What is your preference?

**Answer:**
Pros: It is physically based, using a specific microfacet distribution designed for grazing effects. This likely ensures better energy conservation and consistency with the rest of the physically based rendering pipeline.
Cons: It is computationally more expensive to evaluate and sample than a simple analytic approximation.

Preference: Personally speaking, I prefer the Disney approach. The sheen is usually a subtle secondary effect. The visual difference is often negligible compared to the performance savings and ease of control provided by the simple Fresnel hack.

---

## 6. Putting Everything Together (7%)

### Question 6.1
What are the differences between the `specular` and `metallic` parameters? How do they affect the appearance?

**Answer:**
Metallic: This parameter controls the type of material being simulated. It acts as a linear blend weight between a dielectric (plastic/wood) model and a conductor (metal) model.
- Appearance: Increasing metallic from 0 to 1 removes the diffuse component entirely and changes the specular highlight from achromatic (white) to chromatic (tinted by the baseColor). At 1.0, the object looks like solid metal; at 0.0, it looks like plastic or ceramic.

Specular: This parameter is strictly for dielectrics (non-metals). It scales the intensity of the specular highlight by modifying the Fresnel term (C0) for the non-metallic component.
- Appearance: It changes the brightness of the reflection on dielectric surfaces. Increasing it makes the shiny spot on a plastic ball brighter.


### Question 6.2
What are the differences between the `roughness` and `clearcoat_gloss` parameters? How do they affect the appearance?

**Answer:**
Roughness: This controls the geometric roughness of the base material, affecting Diffuse, Metal, and Glass layers.
- Appearance: Increasing roughness makes the base reflections blurrier and spreads them out. It also affects the diffuse shading at grazing angles.

Clearcoat_gloss: This controls the roughness of the secondary clearcoat layer only. The mapping is inverted compared to standard roughness.
- Mapping: α_g=(1−clearcoatGloss)⋅0.1+clearcoatGloss⋅0.001
- Appearance: Increasing clearcoat_gloss makes the clearcoat highlight sharper and smaller. Decreasing it makes the clearcoat highlight wider and hazier.

### Question 6.3
Play with the `specularTint` parameter. How does it affect the appearance?

**Answer:**
Effect: specularTint allows the dielectric specular highlight (which is physically usually white/achromatic) to be tinted towards the material's baseColor

Appearance: Image there's a red plastic ball, the specular highlight is normally white. Increasing specularTint turns that white highlight red. This is an artistic control to simulate complex material mixtures or "artistic" shading that deviates from strict Fresnel physics for pure dielectrics.


### Question 6.4
The `roughness` parameter affects many components of the BSDFs at once (e.g., both the diffuse and metal BRDF use the roughness parameter). How do you feel about this? If you are an artist using the Disney BSDF, would you want to have a separate roughness parameter for each component?

**Answer:**
I think this is kind of reasonable. Since the roughness is determined by the microfacet geometry, and the microfacet geometry is determined by the material itself, it makes sense that the roughness parameter affects all components of the BSDFs.

Then, from an artist's perspective, I would want to have a separate roughness parameter for each component. This is because different components of the material may have different roughness values. For example, the base material may have a different roughness value than the clearcoat layer. Since I'm already using Disney BSDF, which aims at simplicity and ease of use, I would prefer to have a separate roughness parameter for each component. This would help to better control the appearance with more degrees of freedom.

---

## Notes

- Total: 42% from questions (7% × 6 sections)
- Optional bonus questions can earn up to 9% additional credit
- Reference materials mentioned in questions can be found in Burley's course notes and presentations
