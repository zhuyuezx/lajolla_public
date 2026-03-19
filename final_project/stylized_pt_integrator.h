#pragma once
// =============================================================================
//  Stylized Path Tracing Integrator — West 2024
//  "Stylized Rendering as a Function of Expectation"
//
//  Biased Direct Application estimator + First-Hit Only parameterization.
//  At depth 0 (camera ray), computes a k-sample inner MC estimate ⟨I⟩ of
//  physically-based radiance, then applies a non-linear style function g_θ
//  (cel-shading step) to produce the final pixel colour.
//
//  Indirect bounces (depth > 0) use standard unstylized path tracing.
//
//  NOTE ON MOLLIFICATION: Applying a hard step function to a Monte Carlo
//  estimate produces blurred / soft edges at shadow boundaries. This is the
//  expected bias of the direct-application estimator.  Increasing inner_samples
//  sharpens the boundary toward the true step.
// =============================================================================

#include "camera.h"
#include "image.h"
#include "intersection.h"
#include "light.h"
#include "material.h"
#include "parallel.h"
#include "pcg.h"
#include "progress_reporter.h"
#include "ray.h"
#include "scene.h"
#include "spectrum.h"
#include "texture.h"

// ---------------------------------------------------------------------------
// Inner physical path tracing from a given surface vertex.
//
// This spawns a full physically-based path from `vertex` and accumulates
// the global illumination contribution (NEE + BSDF sampling with MIS),
// identical to the standard path tracer but starting from an existing
// surface intersection rather than the camera.
// ---------------------------------------------------------------------------
static Spectrum stylized_inner_trace(const Scene &scene,
                                     const PathVertex &start_vertex,
                                     const Vector3 &dir_view,
                                     const RayDifferential &start_ray_diff,
                                     pcg32_state &rng) {
    Spectrum radiance = make_zero_spectrum();
    Spectrum current_path_throughput = fromRGB(Vector3{1, 1, 1});
    Real eta_scale = Real(1);

    PathVertex vertex = start_vertex;
    Ray ray;
    ray.org = start_vertex.position;
    ray.dir = -dir_view;  // will be overwritten below
    ray.tnear = 0;
    ray.tfar = infinity<Real>();
    RayDifferential ray_diff = start_ray_diff;

    // If the first hit is itself a light, account for its emission
    if (is_light(scene.shapes[vertex.shape_id])) {
        radiance += current_path_throughput *
            emission(vertex, dir_view, scene);
    }

    int max_depth = scene.options.max_depth;
    for (int num_vertices = 3; max_depth == -1 || num_vertices <= max_depth + 1; num_vertices++) {
        const Material &mat = scene.materials[vertex.material_id];

        // ---- Next Event Estimation (light sampling) ----
        Vector2 light_uv{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
        Real light_w = next_pcg32_real<Real>(rng);
        Real shape_w = next_pcg32_real<Real>(rng);
        int light_id = sample_light(scene, light_w);
        const Light &light = scene.lights[light_id];
        PointAndNormal point_on_light =
            sample_point_on_light(light, vertex.position, light_uv, shape_w, scene);

        Spectrum C1 = make_zero_spectrum();
        Real w1 = 0;
        {
            Real G = 0;
            Vector3 dir_light;
            if (!is_envmap(light)) {
                dir_light = normalize(point_on_light.position - vertex.position);
                Ray shadow_ray{vertex.position, dir_light,
                               get_shadow_epsilon(scene),
                               (1 - get_shadow_epsilon(scene)) *
                                   distance(point_on_light.position, vertex.position)};
                if (!occluded(scene, shadow_ray)) {
                    G = max(-dot(dir_light, point_on_light.normal), Real(0)) /
                        distance_squared(point_on_light.position, vertex.position);
                }
            } else {
                dir_light = -point_on_light.normal;
                Ray shadow_ray{vertex.position, dir_light,
                               get_shadow_epsilon(scene),
                               infinity<Real>()};
                if (!occluded(scene, shadow_ray)) {
                    G = 1;
                }
            }

            Real p1 = light_pmf(scene, light_id) *
                pdf_point_on_light(light, point_on_light, vertex.position, scene);

            if (G > 0 && p1 > 0) {
                Vector3 dv = -ray.dir;
                Spectrum f = eval(mat, dv, dir_light, vertex, scene.texture_pool);
                Spectrum L = emission(light, -dir_light, Real(0), point_on_light, scene);
                C1 = G * f * L;
                Real p2 = pdf_sample_bsdf(mat, dv, dir_light, vertex, scene.texture_pool);
                p2 *= G;
                w1 = (p1*p1) / (p1*p1 + p2*p2);
                C1 /= p1;
            }
        }
        radiance += current_path_throughput * C1 * w1;

        // ---- BSDF sampling ----
        Vector3 dv = -ray.dir;
        Vector2 bsdf_rnd_param_uv{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
        Real bsdf_rnd_param_w = next_pcg32_real<Real>(rng);
        std::optional<BSDFSampleRecord> bsdf_sample_ =
            sample_bsdf(mat, dv, vertex, scene.texture_pool,
                         bsdf_rnd_param_uv, bsdf_rnd_param_w);
        if (!bsdf_sample_) break;
        const BSDFSampleRecord &bsdf_sample = *bsdf_sample_;
        Vector3 dir_bsdf = bsdf_sample.dir_out;

        if (bsdf_sample.eta == 0) {
            ray_diff.spread = reflect(ray_diff, vertex.mean_curvature, bsdf_sample.roughness);
        } else {
            ray_diff.spread = refract(ray_diff, vertex.mean_curvature, bsdf_sample.eta, bsdf_sample.roughness);
            eta_scale /= (bsdf_sample.eta * bsdf_sample.eta);
        }

        Ray bsdf_ray{vertex.position, dir_bsdf, get_intersection_epsilon(scene), infinity<Real>()};
        std::optional<PathVertex> bsdf_vertex = intersect(scene, bsdf_ray);

        Real G;
        if (bsdf_vertex) {
            G = fabs(dot(dir_bsdf, bsdf_vertex->geometric_normal)) /
                distance_squared(bsdf_vertex->position, vertex.position);
        } else {
            G = 1;
        }

        Spectrum f = eval(mat, dv, dir_bsdf, vertex, scene.texture_pool);
        Real p2 = pdf_sample_bsdf(mat, dv, dir_bsdf, vertex, scene.texture_pool);
        if (p2 <= 0) break;
        p2 *= G;

        if (bsdf_vertex && is_light(scene.shapes[bsdf_vertex->shape_id])) {
            Spectrum L = emission(*bsdf_vertex, -dir_bsdf, scene);
            Spectrum C2 = G * f * L;
            int lid = get_area_light_id(scene.shapes[bsdf_vertex->shape_id]);
            assert(lid >= 0);
            const Light &lt = scene.lights[lid];
            PointAndNormal lp{bsdf_vertex->position, bsdf_vertex->geometric_normal};
            Real p1 = light_pmf(scene, lid) *
                pdf_point_on_light(lt, lp, vertex.position, scene);
            Real w2 = (p2*p2) / (p1*p1 + p2*p2);
            C2 /= p2;
            radiance += current_path_throughput * C2 * w2;
        } else if (!bsdf_vertex && has_envmap(scene)) {
            const Light &lt = get_envmap(scene);
            Spectrum L = emission(lt, -dir_bsdf, ray_diff.spread,
                                  PointAndNormal{}, scene);
            Spectrum C2 = G * f * L;
            PointAndNormal lp{Vector3{0, 0, 0}, -dir_bsdf};
            Real p1 = light_pmf(scene, scene.envmap_light_id) *
                      pdf_point_on_light(lt, lp, vertex.position, scene);
            Real w2 = (p2*p2) / (p1*p1 + p2*p2);
            C2 /= p2;
            radiance += current_path_throughput * C2 * w2;
        }

        if (!bsdf_vertex) break;

        // Russian roulette
        Real rr_prob = 1;
        if (num_vertices - 1 >= scene.options.rr_depth) {
            rr_prob = min(max((1 / eta_scale) * current_path_throughput), Real(0.95));
            if (next_pcg32_real<Real>(rng) > rr_prob) break;
        }

        ray = bsdf_ray;
        vertex = *bsdf_vertex;
        current_path_throughput = current_path_throughput * (G * f) / (p2 * rr_prob);
    }
    return radiance;
}

// ---------------------------------------------------------------------------
// Style function g_θ: cel-shading step applied to averaged inner estimate.
//
// Replicates the NPR cel-shading logic from the Skypop integrator:
//   if luminance(averaged) >= threshold → lit colour
//   else → shadow tint
// ---------------------------------------------------------------------------
static Spectrum stylized_apply_g_theta(const Scene &scene,
                                       const Spectrum &albedo,
                                       const Spectrum &averaged_radiance) {
    const RenderOptions &opt = scene.options;
    Real lum = luminance(averaged_radiance);

    Spectrum result;
    if (lum >= opt.npr_cel_threshold) {
        // Lit region: albedo × light colour
        result = albedo * opt.npr_light_color;
    } else {
        // Shadow region: albedo × shadow tint
        result = albedo * opt.npr_shadow_tint;
    }
    // Add flat ambient
    result = result + albedo * opt.npr_ambient;
    return result;
}

// ---------------------------------------------------------------------------
// Helpers: check if shape_id is in a per-style target list
// ---------------------------------------------------------------------------
static bool is_in_list(const std::vector<int> &ids, int shape_id) {
    for (int id : ids) {
        if (id == shape_id) return true;
    }
    return false;
}

// Returns 0=none, 1=cel, 2=tiedye, 3=acp
static int get_style_for_shape(const Scene &scene, int shape_id) {
    const auto &opt = scene.options;
    // Per-style lists take priority
    if (is_in_list(opt.cel_target_ids, shape_id))    return 1;
    if (is_in_list(opt.tiedye_target_ids, shape_id)) return 2;
    if (is_in_list(opt.acp_target_ids, shape_id))    return 3;
    // Backward compat: old target_object_ids + style_type
    if (is_in_list(opt.target_object_ids, shape_id)) {
        if (opt.style_type == "tiedye") return 2;
        if (opt.style_type == "acp")    return 3;
        return 1; // default cel
    }
    return 0; // non-target
}

static bool is_any_target(const Scene &scene, int shape_id) {
    return get_style_for_shape(scene, shape_id) != 0;
}

// ---------------------------------------------------------------------------
// Style function g_θ: "Tie-Dye" cosine effect (West Fig 11).
//
// Applies per-channel cosine waves to the physical radiance, creating
// psychedelic colour shifts that depend on luminance and frequency.
// Purely colour-based — no occlusion/shadow logic needed.
// ---------------------------------------------------------------------------
static Spectrum stylized_apply_tiedye(const Scene &scene,
                                      const Spectrum &averaged_radiance) {
    const auto &opt = scene.options;
    Spectrum result;
    result[0] = std::abs(std::cos(opt.tie_dye_freq.x * averaged_radiance[0] + opt.tie_dye_phase.x));
    result[1] = std::abs(std::cos(opt.tie_dye_freq.y * averaged_radiance[1] + opt.tie_dye_phase.y));
    result[2] = std::abs(std::cos(opt.tie_dye_freq.z * averaged_radiance[2] + opt.tie_dye_phase.z));
    return result;
}

// ---------------------------------------------------------------------------
// Style function g_θ: Artistic Color Palette / ACP (West Fig 7).
//
// Maps physical luminance → a two-stop colour ramp (dark ↔ bright).
// Purely colour-based — no occlusion/shadow logic needed.
// ---------------------------------------------------------------------------
static Spectrum stylized_apply_acp(const Scene &scene,
                                   const Spectrum &averaged_radiance) {
    const auto &opt = scene.options;
    Real lum = luminance(averaged_radiance);
    lum = std::max(Real(0), std::min(Real(1), lum));  // clamp [0,1]
    Spectrum dark   = fromRGB(opt.acp_dark_color);
    Spectrum bright = fromRGB(opt.acp_bright_color);
    return dark * (Real(1) - lum) + bright * lum;
}

// ---------------------------------------------------------------------------
// Main per-pixel stylized path tracing function.
//
// Per-object style dispatch:
//   - cel_target_ids    → k-sample ⟨I⟩ + cel g_θ
//   - tiedye_target_ids → k-sample ⟨I⟩ + tiedye g_θ
//   - acp_target_ids    → k-sample ⟨I⟩ + acp g_θ
//   - all other shapes  → 1-sample PBR (cheap fallback)
// All styles use the same transition_t crossfade.
// ---------------------------------------------------------------------------
static Spectrum stylized_path_tracing(const Scene &scene,
                                      int x, int y,
                                      pcg32_state &rng) {
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos((x + next_pcg32_real<Real>(rng)) / w,
                       (y + next_pcg32_real<Real>(rng)) / h);
    Ray ray = sample_primary(scene.camera, screen_pos);
    RayDifferential ray_diff = init_ray_differential(w, h);

    std::optional<PathVertex> vertex_ = intersect(scene, ray, ray_diff);
    if (!vertex_) {
        if (has_envmap(scene)) {
            return emission(get_envmap(scene), -ray.dir, ray_diff.spread,
                            PointAndNormal{}, scene);
        }
        return fromRGB(scene.options.npr_background_color);
    }
    PathVertex vertex = *vertex_;
    Vector3 dir_view = -ray.dir;

    // --- Check which style this object gets ---
    int style_id = get_style_for_shape(scene, vertex.shape_id);

    // Non-target: standard single-sample PBR
    if (style_id == 0) {
        return stylized_inner_trace(scene, vertex, dir_view, ray_diff, rng);
    }

    // --- Target object: k-sample inner estimate ⟨I⟩ ---
    Spectrum albedo = make_const_spectrum(Real(0.8));
    if (vertex.material_id >= 0) {
        const Material &mat = scene.materials[vertex.material_id];
        TextureSpectrum tex = get_texture(mat);
        albedo = eval(tex, vertex.uv, vertex.uv_screen_size, scene.texture_pool);
    }

    int k = scene.options.stylized_inner_samples;
    Spectrum inner_sum = make_zero_spectrum();
    for (int s = 0; s < k; s++) {
        Spectrum sample_rad = stylized_inner_trace(
            scene, vertex, dir_view, ray_diff, rng);
        if (isfinite(sample_rad)) {
            inner_sum += sample_rad;
        }
    }
    Spectrum averaged_radiance = inner_sum / Real(k);

    // --- Apply the per-object style function g_θ ---
    auto apply_style = [&](const Spectrum &avg_rad) -> Spectrum {
        switch (style_id) {
            case 2:  return stylized_apply_tiedye(scene, avg_rad);
            case 3:  return stylized_apply_acp(scene, avg_rad);
            default: return stylized_apply_g_theta(scene, albedo, avg_rad);
        }
    };

    // --- Temporal crossfade: t blends uniformly between PBR and styled ---
    Real t = scene.options.transition_t;

    if (t >= Real(1)) {
        return apply_style(averaged_radiance);
    }
    if (t <= Real(0)) {
        return averaged_radiance;
    }

    Spectrum pbr_color = averaged_radiance;
    Spectrum styled_color = apply_style(averaged_radiance);
    return pbr_color * (Real(1) - t) + styled_color * t;
}

// ---------------------------------------------------------------------------
// Tiled parallel render function — same pattern as path_render()
// Now also outputs AOVs (depth, normal, object_id) for Sobel outlines.
// ---------------------------------------------------------------------------
static Image3 stylized_pt_render(const Scene &scene, NprAovs &aovs) {
    int w = scene.camera.width, h = scene.camera.height;
    Image3 img(w, h);
    aovs.depth     = Image3(w, h);
    aovs.normal    = Image3(w, h);
    aovs.object_id = Image3(w, h);

    constexpr int tile_size = 16;
    int num_tiles_x = (w + tile_size - 1) / tile_size;
    int num_tiles_y = (h + tile_size - 1) / tile_size;

    ProgressReporter reporter(num_tiles_x * num_tiles_y);
    parallel_for([&](const Vector2i &tile) {
        pcg32_state rng = init_pcg32(tile[1] * num_tiles_x + tile[0]);
        int x0 = tile[0] * tile_size;
        int x1 = min(x0 + tile_size, w);
        int y0 = tile[1] * tile_size;
        int y1 = min(y0 + tile_size, h);
        for (int y = y0; y < y1; y++) {
            for (int x = x0; x < x1; x++) {
                // --- AOV pass: single deterministic ray (no jitter) ---
                Ray aov_ray = sample_primary(
                    scene.camera,
                    Vector2(Real(x + 0.5) / w, Real(y + 0.5) / h));
                RayDifferential aov_diff = init_ray_differential(w, h);
                if (std::optional<PathVertex> v_ = intersect(scene, aov_ray, aov_diff)) {
                    const PathVertex &v = *v_;
                    Real depth_val = dot(v.position - aov_ray.org, aov_ray.dir);
                    aovs.depth(x, y) = Vector3{depth_val, depth_val, depth_val};

                    // Camera-facing normal flip (prevents false edges from
                    // counter-wound polygons — same logic as NPR integrator)
                    Vector3 N = normalize(v.geometric_normal);
                    if (std::abs(N[0]) < Real(1e-6)) N[0] = Real(0);
                    if (std::abs(N[1]) < Real(1e-6)) N[1] = Real(0);
                    if (std::abs(N[2]) < Real(1e-6)) N[2] = Real(0);
                    if (dot(N, -aov_ray.dir) < Real(0)) N = -N;
                    aovs.normal(x, y) = N;

                    Real id = Real(v.shape_id);
                    aovs.object_id(x, y) = Vector3{id, id, id};
                } else {
                    aovs.depth(x, y)     = Vector3{Real(-1), Real(-1), Real(-1)};
                    aovs.normal(x, y)    = Vector3{Real(0),  Real(0),  Real(0)};
                    aovs.object_id(x, y) = Vector3{Real(-1), Real(-1), Real(-1)};
                }

                // --- Colour pass: SPP × stylized path tracing ---
                Spectrum radiance = make_zero_spectrum();
                int spp = scene.options.samples_per_pixel;
                for (int s = 0; s < spp; s++) {
                    radiance += stylized_path_tracing(scene, x, y, rng);
                }
                img(x, y) = radiance / Real(spp);
            }
        }
        reporter.update(1);
    }, Vector2i(num_tiles_x, num_tiles_y));
    reporter.done();
    return img;
}

