#pragma once
// =============================================================================
//  Non-Photorealistic Rendering (NPR) integrator — Skypop Collective style
//  flat shading · orthographic camera · cel quantization · outline AOVs
//
//  Included by src/render.cpp.  All La Jolla headers are reachable because
//  the build already adds src/ to the include path.
// =============================================================================

#include "camera.h"
#include "image.h"
#include "intersection.h"
#include "material.h"
#include "parallel.h"
#include "progress_reporter.h"
#include "ray.h"
#include "scene.h"
#include "texture.h"
#include "vector.h"

#include <filesystem>
#include <string>

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// AOV bundle filled per-pixel during the NPR render pass
// ---------------------------------------------------------------------------
struct NprAovs {
    Image3 depth;      // (d, d, d) — raw ray-hit distance; -1 on miss
    Image3 normal;     // flat geometric normal (RGB = XYZ)
    Image3 object_id;  // (id, id, id) — shape_id cast to Real; -1 on miss
};

// ---------------------------------------------------------------------------
// Helper: extract "base" albedo from any material type
// ---------------------------------------------------------------------------
static Spectrum npr_get_albedo(const Scene &scene, const PathVertex &v) {
    if (v.material_id < 0) {
        return make_const_spectrum(Real(0.8));
    }
    const Material &mat = scene.materials[v.material_id];
    TextureSpectrum tex = get_texture(mat);
    return eval(tex, v.uv, v.uv_screen_size, scene.texture_pool);
}

// ---------------------------------------------------------------------------
// Core per-pixel NPR shade function
//
// Implements:
//   1. Flat shading  — vertex.geometric_normal, no barycentric interpolation
//   2. Directional light — single infinite light from npr_light_dir
//   3. Quantized cel shading — hard step at npr_cel_threshold
//   4. Flat ambient — constant additive term
// ---------------------------------------------------------------------------
static Spectrum npr_shade_pixel(const Scene &scene,
                                const PathVertex &v,
                                const Vector3 &ray_dir) {
    const RenderOptions &opt = scene.options;

    // --- flat geometric normal, always facing the camera ---
    Vector3 N = v.geometric_normal;
    if (dot(N, -ray_dir) < Real(0)) {
        N = -N;
    }

    // --- diffuse albedo from scene material ---
    Spectrum albedo = npr_get_albedo(scene, v);

    // --- directional light shading ---
    Vector3 L = normalize(opt.npr_light_dir);
    Real NdotL = dot(N, L);

    // quantized / cel step function  ─────────────────────────────────
    //   lit   : N·L > threshold  →  albedo * light_color
    //   shadow: N·L ≤ threshold  →  albedo * cool shadow tint
    Spectrum diffuse;
    if (NdotL > opt.npr_cel_threshold) {
        diffuse = albedo * opt.npr_light_color;
    } else {
        diffuse = albedo * opt.npr_shadow_tint;
    }

    // flat ambient (prevents fully-black shadows)
    Spectrum ambient = albedo * opt.npr_ambient;

    return diffuse + ambient;
}

// ---------------------------------------------------------------------------
// NPR render pass — parallel tile loop
//
// Returns the colour image and populates `aovs` (depth / normal / objectID).
// All four images are written to disk by the caller.
// ---------------------------------------------------------------------------
Image3 npr_render(const Scene &scene, NprAovs &aovs) {
    int w = scene.camera.width;
    int h = scene.camera.height;

    Image3 img(w, h);
    aovs.depth     = Image3(w, h);
    aovs.normal    = Image3(w, h);
    aovs.object_id = Image3(w, h);

    constexpr int tile_size = 16;
    int num_tiles_x = (w + tile_size - 1) / tile_size;
    int num_tiles_y = (h + tile_size - 1) / tile_size;

    ProgressReporter reporter(num_tiles_x * num_tiles_y);

    parallel_for([&](const Vector2i &tile) {
        int x0 = tile[0] * tile_size;  int x1 = min(x0 + tile_size, w);
        int y0 = tile[1] * tile_size;  int y1 = min(y0 + tile_size, h);

        for (int y = y0; y < y1; y++) {
            for (int x = x0; x < x1; x++) {
                // One ray per pixel — NPR is deterministic (no Monte Carlo)
                Ray ray = sample_primary(
                    scene.camera,
                    Vector2(Real(x + 0.5) / w, Real(y + 0.5) / h));
                RayDifferential ray_diff = init_ray_differential(w, h);

                if (std::optional<PathVertex> vertex_ = intersect(scene, ray, ray_diff)) {
                    const PathVertex &v = *vertex_;

                    // --- colour ---
                    img(x, y) = npr_shade_pixel(scene, v, ray.dir);

                    // --- AOVs ---
                    Real depth_val = length(v.position - ray.org);
                    aovs.depth(x, y)     = Vector3{depth_val, depth_val, depth_val};
                    aovs.normal(x, y)    = v.geometric_normal;  // [-1,1] range
                    Real id = Real(v.shape_id);
                    aovs.object_id(x, y) = Vector3{id, id, id};
                } else {
                    img(x, y)            = scene.options.npr_background_color;
                    aovs.depth(x, y)     = Vector3{Real(-1), Real(-1), Real(-1)};
                    aovs.normal(x, y)    = Vector3{Real(0),  Real(0),  Real(0)};
                    aovs.object_id(x, y) = Vector3{Real(-1), Real(-1), Real(-1)};
                }
            }
        }
        reporter.update(1);
    }, Vector2i(num_tiles_x, num_tiles_y));

    reporter.done();
    return img;
}
