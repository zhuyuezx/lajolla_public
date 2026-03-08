#pragma once

// The simplest volumetric renderer: 
// single absorption only homogeneous volume
// only handle directly visible light sources
Spectrum vol_path_tracing_1(const Scene &scene,
                            int x, int y, /* pixel coordinates */
                            pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    Ray ray = sample_primary(scene.camera, screen_pos);
    std::optional<PathVertex> isect_ = intersect(scene, ray);
    if (!isect_) {
        return make_zero_spectrum();
    }
    PathVertex isect = *isect_;

    if (!is_light(scene.shapes[isect.shape_id])) {
        return make_zero_spectrum();
    }
    // get current medium
    bool hit_inside = dot(isect.shading_frame.n, isect.geometric_normal) < 0;
    int medium_id = hit_inside ? isect.interior_medium_id: isect.exterior_medium_id;
    Medium medium = scene.media[medium_id];
    Spectrum sigma_a = get_sigma_a(medium, isect.position);
    Real t_hit = distance(ray.org, isect.position);
    // return transmittance * Le
    return exp(-sigma_a * t_hit) * emission(isect, -ray.dir, scene);
}

// The second simplest volumetric renderer: 
// single monochromatic homogeneous volume with single scattering,
// no need to handle surface lighting, only directly visible light source
Spectrum vol_path_tracing_2(const Scene &scene,
                            int x, int y, /* pixel coordinates */
                            pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    Ray ray = sample_primary(scene.camera, screen_pos);
    std::optional<PathVertex> isect_ = intersect(scene, ray);

    Real t_hit = infinity<Real>();
    Medium medium = scene.media[scene.camera.medium_id];
    PathVertex isect;
    if (isect_) {
        // get current medium and t_hit
        isect = *isect_;
        bool hit_inside = dot(isect.shading_frame.n, isect.geometric_normal) < 0;
        int medium_id = hit_inside ? isect.interior_medium_id: isect.exterior_medium_id;
        medium = scene.media[medium_id];
        t_hit = distance(ray.org, isect.position);
    }

    Spectrum sigma_a = get_sigma_a(medium, make_zero_spectrum());
    Spectrum sigma_s = get_sigma_s(medium, make_zero_spectrum());
    Spectrum sigma_t = sigma_a + sigma_s;

    Real u = next_pcg32_real<Real>(rng);
    Real t = -log(1 - u) / sigma_t[0];

    if (t < t_hit) {
        Vector3 trans_pdf = exp(-sigma_t * t) * sigma_t;
        Vector3 transmittance = exp(-sigma_t * t);

        // compute L_s1 using Monte Carlo sampling
        Vector3 p = ray.org + t * ray.dir;

        // init params
        Vector2 light_uv{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
        Real light_w = next_pcg32_real<Real>(rng);
        Real shape_w = next_pcg32_real<Real>(rng);
        int light_id = sample_light(scene, light_w);
        const Light &light = scene.lights[light_id];
        PointAndNormal point_on_light = sample_point_on_light(light, p, light_uv, shape_w, scene);

        Real G = 0;
        Vector3 dir_light = normalize(point_on_light.position - p);
        Ray shadow_ray{p, dir_light, get_shadow_epsilon(scene), (1 - get_shadow_epsilon(scene)) * distance(p, point_on_light.position)};
        if (!occluded(scene, shadow_ray)) {
            G = max(Real(0), -dot(dir_light, point_on_light.normal)) / distance_squared(p, point_on_light.position);
        }
        Real L_s1_pdf = light_pmf(scene, light_id) * pdf_point_on_light(light, point_on_light, p, scene);

        if (L_s1_pdf <= 0 || G <= 0) {
            return make_zero_spectrum();
        }
        Spectrum rho = eval(get_phase_function(medium), dir_light, -ray.dir);
        Spectrum Le = emission(light, -dir_light, Real(0), point_on_light, scene);
        Spectrum p_t_geq_t_hit = exp(-distance(point_on_light.position, p) * sigma_t);
        Spectrum L_s1_estimate = rho * Le * G * p_t_geq_t_hit;

        return (transmittance / trans_pdf) * sigma_s * (L_s1_estimate / L_s1_pdf);
    } else {
        // hit a surface, account for surface emission
        if (!is_light(scene.shapes[isect.shape_id])) {
            return make_zero_spectrum();
        }
        return emission(isect, -ray.dir, scene);
    }
}

int update_medium(const PathVertex &isect, const Ray &ray, int current_medium_id) {
    int medium_id = current_medium_id;
    if (isect.interior_medium_id != isect.exterior_medium_id) {
        if (dot(ray.dir, isect.geometric_normal) > 0) {
            medium_id = isect.exterior_medium_id;
        } else {
            medium_id = isect.interior_medium_id;
        }
    }
    return medium_id;
}

// The third volumetric renderer (not so simple anymore): 
// multiple monochromatic homogeneous volumes with multiple scattering
// no need to handle surface lighting, only directly visible light source
Spectrum vol_path_tracing_3(const Scene &scene,
                            int x, int y, /* pixel coordinates */
                            pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    Ray ray = sample_primary(scene.camera, screen_pos);

    int current_medium_id = scene.camera.medium_id;
    Spectrum current_path_throughput = make_const_spectrum(1);
    Spectrum radiance = make_zero_spectrum();
    int bounces = 0;

    const int max_depth = scene.options.max_depth;
    const int rr_depth = scene.options.rr_depth;

    while (true) {
        bool scatter = false;
        std::optional<PathVertex> isect_ = intersect(scene, ray);
        Real transmittance = Real(1);
        Real trans_pdf = Real(1);
        Real sigma_s = Real(0);

        if (current_medium_id != -1) {
            const Medium &current_medium = scene.media[current_medium_id];
            Real sigma_a = get_sigma_a(current_medium, ray.org)[0];
            sigma_s = get_sigma_s(current_medium, ray.org)[0];
            Real sigma_t = sigma_a + sigma_s;

            Real u = next_pcg32_real<Real>(rng);
            Real t = -log(1 - u) / sigma_t;
            Real t_hit = infinity<Real>();

            if (isect_) {
                t_hit = distance(ray.org, isect_->position);
            }

            if (t < t_hit) {
                // scatter in the medium
                scatter = true;
                transmittance = exp(-sigma_t * t);
                trans_pdf = exp(-sigma_t * t) * sigma_t;
                ray.org += t * ray.dir;
            } else {
                // hit the surface
                transmittance = exp(-sigma_t * t_hit);
                trans_pdf = exp(-sigma_t * t_hit);
                ray.org += t_hit * (1 + get_shadow_epsilon(scene)) * ray.dir;
            }
        }
        
        current_path_throughput *= transmittance / trans_pdf;

        if (!scatter && isect_ && is_light(scene.shapes[isect_->shape_id])) {
            // reach a surface, include emission
            radiance += current_path_throughput * emission(*isect_, -ray.dir, scene);
        }

        if (bounces == max_depth - 1 && max_depth != -1) {
            // reach maximum bounces
            break;
        }

        if (!scatter && isect_ && isect_->material_id == -1) {
            // index-matching interface, skip through it
            current_medium_id = update_medium(*isect_, ray, current_medium_id);
            bounces++;
            continue;
        }

        // sample next direct & update path throughput
        if (scatter) {
            const PhaseFunction &phase_function = get_phase_function(scene.media[current_medium_id]);
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
            std::optional<Spectrum> next_dir = sample_phase_function(phase_function, -ray.dir, rnd_param);

            current_path_throughput *= eval(phase_function, *next_dir, -ray.dir) /
                pdf_sample_phase(phase_function, -ray.dir, *next_dir) * sigma_s;
            
            ray.dir = *next_dir;
        } else {
            // hit a surface -- don't need to deal with this yet
            break;
        }

        Real rr_prob = Real(1);
        if (bounces >= rr_depth) {
            rr_prob = min(Real(0.95), max(current_path_throughput));
            if (next_pcg32_real<Real>(rng) > rr_prob) {
                break;
            } else {
                current_path_throughput /= rr_prob;
            }
        }
        bounces++;
    }
    return radiance;
}

Spectrum next_event_estimation(
    Ray ray,
    int current_medium_id,
    int bounces,
    pcg32_state &rng,
    const Material *material,
    PathVertex original_isect_,
    const Scene &scene
) {
    // random params preparation
    Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
    Real light_w = next_pcg32_real<Real>(rng);
    Real shape_w = next_pcg32_real<Real>(rng);
    int light_id = sample_light(scene, light_w);
    const Light &light = scene.lights[light_id];
    PointAndNormal point_on_light = sample_point_on_light(light, ray.org, rnd_param, shape_w, scene);
    Vector3 p_prime = point_on_light.position;
    
    Vector3 p = ray.org;
    Spectrum T_light = make_const_spectrum(1);
    int shadow_medium_id = current_medium_id;
    int shadow_bounces = 0;
    Spectrum p_trans_dir = make_const_spectrum(1); // for multiple importance sampling
    Vector3 dir_light = normalize(p_prime - p);

    Vector3 original_p = p;
    Vector3 original_ray_dir = ray.dir;

    while (true) {
        Ray shadow_ray{p, dir_light, get_shadow_epsilon(scene), 
            (1 - get_shadow_epsilon(scene)) * distance(p, p_prime)};
        std::optional<PathVertex> isect_ = intersect(scene, shadow_ray);
        Real next_t = distance(p, p_prime);
        if (isect_) {
            next_t = distance(isect_->position, p); 
        }
        // account for the transmittance to next_t
        if (shadow_medium_id != -1) {
            Medium medium = scene.media[shadow_medium_id];
            Spectrum sigma_a = get_sigma_a(medium, p);
            Spectrum sigma_s = get_sigma_s(medium, p);
            Spectrum sigma_t = sigma_a + sigma_s;
            T_light *= exp(-sigma_t * next_t);
            p_trans_dir *= exp(-sigma_t * next_t);
        }

        if (!isect_) {
            // Nothing is blocking, we're done
            break;
        }
        // something is blocking: is it an opaque surface?
        if (isect_->material_id >= 0) {
            // we're blocked
            return make_zero_spectrum();
        }
        // otherwise, it's an index-matching surface and
        // we want to pass through -- this introduces one extra connection vertex
        shadow_bounces++;
        if (scene.options.max_depth != -1 && bounces + shadow_bounces + 1 >= scene.options.max_depth) {
            // reach the max no. of vertices
            return make_zero_spectrum();
        }

        shadow_medium_id = update_medium(*isect_, shadow_ray, shadow_medium_id);
        p += next_t * dir_light;
    }

    if (T_light[0] > 0 and T_light[1] > 0 and T_light[2] > 0) {
        Vector3 dir_light = normalize(p_prime - original_p);
        Spectrum Le = emission(light, -dir_light, Real(0), point_on_light, scene);
        Real pdf_nee = light_pmf(scene, light_id) * pdf_point_on_light(light, point_on_light, original_p, scene);
        Real G = max(Real(0), -dot(dir_light, point_on_light.normal)) / distance_squared(original_p, p_prime);
        Real pdf_scatter = G * p_trans_dir[0];

        Spectrum rho;
        if (material) {
            // surface vertex, sample BSDF pdf
            pdf_scatter *= pdf_sample_bsdf(*material, -original_ray_dir, dir_light, original_isect_, scene.texture_pool);
            rho = eval(*material, -original_ray_dir, dir_light, original_isect_, scene.texture_pool);
        } else {
            // medium vertex, sample phase function pdf
            PhaseFunction phase_function = get_phase_function(scene.media[current_medium_id]);
            rho = eval(phase_function, -original_ray_dir, dir_light);
            pdf_scatter *= pdf_sample_phase(phase_function, -original_ray_dir, dir_light);
        }
        Spectrum contrib = T_light * rho * Le * G / pdf_nee;
        // power heuristics
        Real w = (pdf_nee * pdf_nee) / (pdf_nee * pdf_nee + pdf_scatter * pdf_scatter);
        return w * contrib;
    }
    return make_zero_spectrum();
} 

// The fourth volumetric renderer: 
// multiple monochromatic homogeneous volumes with multiple scattering
// with MIS between next event estimation and phase function sampling
// still no surface lighting
Spectrum vol_path_tracing_4(const Scene &scene,
                            int x, int y, /* pixel coordinates */
                            pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    Ray ray = sample_primary(scene.camera, screen_pos);
    int current_medium_id = scene.camera.medium_id;

    Spectrum current_path_throughput = make_const_spectrum(1);
    Spectrum radiance = make_zero_spectrum();
    int bounces = 0;
    Real dir_pdf = Real(0); // in solid angle measure
    Vector3 nee_p_cache = make_zero_spectrum();
    Spectrum multi_trans_pdf = make_const_spectrum(1);
    bool never_scatter = true;

    const int max_depth = scene.options.max_depth;
    const int rr_depth = scene.options.rr_depth;

    while (true) {
        bool scatter = false;
        std::optional<PathVertex> isect_ = intersect(scene, ray);
        Spectrum transmittance = make_const_spectrum(1);
        Spectrum trans_pdf = make_const_spectrum(1);
        Spectrum sigma_s = make_const_spectrum(0);

        if (current_medium_id != -1) {
            const Medium &current_medium = scene.media[current_medium_id];
            Spectrum sigma_a = get_sigma_a(current_medium, ray.org);
            sigma_s = get_sigma_s(current_medium, ray.org);
            Spectrum sigma_t = sigma_a + sigma_s;

            Real u = next_pcg32_real<Real>(rng);
            Real t = -log(1 - u) / sigma_t[0];
            Real t_hit = infinity<Real>();

            if (isect_) {
                t_hit = distance(ray.org, isect_->position);
            }

            if (t < t_hit) {
                // scatter in the medium
                scatter = true;
                transmittance = exp(-sigma_t * t);
                trans_pdf = exp(-sigma_t * t) * sigma_t;
                ray.org += t * ray.dir;
            } else {
                // hit the surface
                transmittance = exp(-sigma_t * t_hit);
                trans_pdf = exp(-sigma_t * t_hit);
                ray.org = isect_->position + ray.dir * get_shadow_epsilon(scene);
            }
        } else if (isect_) {
            ray.org = isect_->position + ray.dir * get_shadow_epsilon(scene);
        } else {
            break;
        }
        
        multi_trans_pdf *= trans_pdf;
        current_path_throughput *= transmittance / trans_pdf;

        if (!scatter && isect_ && is_light(scene.shapes[isect_->shape_id])) {
            Spectrum Le = emission(*isect_, -ray.dir, scene);
            if (never_scatter) {
                // this is the only way we can see the light source, so we don't need to do MIS
                radiance += current_path_throughput * Le;
            } else {
                // need to account for next event estimation
                int light_id = get_area_light_id(scene.shapes[isect_->shape_id]);
                const Light &light = scene.lights[light_id];
                PointAndNormal light_point{isect_->position, isect_->geometric_normal};
                Real pdf_nee = pdf_point_on_light(light, light_point, nee_p_cache, scene) * light_pmf(scene, light_id);

                Real G = max(Real(0), -dot(ray.dir, light_point.normal)) / distance_squared(nee_p_cache, light_point.position);
                Spectrum dir_pdf_ = dir_pdf * multi_trans_pdf * G;

                Vector3 w = (dir_pdf_ * dir_pdf_) / (dir_pdf_ * dir_pdf_ + pdf_nee * pdf_nee);
                // current_path_throughput already accounts for transmittance
                radiance += current_path_throughput * Le * w;
            }
        }

        if (bounces == max_depth - 1 && max_depth != -1) {
            // reach maximum bounces
            break;
        }

        if (!scatter && isect_ && isect_->material_id == -1) {
            // index-matching interface, skip through it
            current_medium_id = update_medium(*isect_, ray, current_medium_id);
            bounces++;
            continue;
        }

        // sample next direct & update path throughput
        if (scatter) {
            never_scatter = false;

            Spectrum nee = next_event_estimation(ray, current_medium_id, bounces, rng, nullptr, *isect_, scene);
            radiance += current_path_throughput * nee * sigma_s;

            const PhaseFunction &phase_function = get_phase_function(scene.media[current_medium_id]);
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
            std::optional<Spectrum> next_dir = sample_phase_function(phase_function, -ray.dir, rnd_param);

            nee_p_cache = ray.org;

            current_path_throughput *= eval(phase_function, *next_dir, -ray.dir) /
                pdf_sample_phase(phase_function, -ray.dir, *next_dir) * sigma_s;
            
            ray.dir = *next_dir;
            // reset multi_trans_pdf after scattering event
            multi_trans_pdf = make_const_spectrum(1);
        } else {
            // hit a surface -- don't need to deal with this yet
            break;
        }

        Real rr_prob = Real(1);
        if (bounces >= rr_depth) {
            rr_prob = min(Real(0.95), max(current_path_throughput));
            if (next_pcg32_real<Real>(rng) > rr_prob) {
                break;
            } else {
                current_path_throughput /= rr_prob;
            }
        }
        bounces++;
    }
    return radiance;
}

// The fifth volumetric renderer: 
// multiple monochromatic homogeneous volumes with multiple scattering
// with MIS between next event estimation and phase function sampling
// with surface lighting
Spectrum vol_path_tracing_5(const Scene &scene,
                            int x, int y, /* pixel coordinates */
                            pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    RayDifferential ray_diff = init_ray_differential(Real(0), Real(0));
    Ray ray = sample_primary(scene.camera, screen_pos);
    int current_medium_id = scene.camera.medium_id;

    Spectrum current_path_throughput = make_const_spectrum(1);
    Spectrum radiance = make_zero_spectrum();
    int bounces = 0;
    Real dir_pdf = Real(0);
    Vector3 nee_p_cache = make_zero_spectrum();
    Spectrum multi_trans_pdf = make_const_spectrum(1);
    bool never_scatter = true;
    Real eta_scale = Real(1); // need eta for refraction

    const int max_depth = scene.options.max_depth;
    const int rr_depth = scene.options.rr_depth;

    while (true) {
        bool scatter = false;
        std::optional<PathVertex> isect_ = intersect(scene, ray);
        Spectrum transmittance = make_const_spectrum(1);
        Spectrum trans_pdf = make_const_spectrum(1);
        Spectrum sigma_s = make_const_spectrum(0);

        if (current_medium_id != -1) {
            const Medium &current_medium = scene.media[current_medium_id];
            Spectrum sigma_a = get_sigma_a(current_medium, ray.org);
            sigma_s = get_sigma_s(current_medium, ray.org);
            Spectrum sigma_t = sigma_a + sigma_s;

            Real u = next_pcg32_real<Real>(rng);
            Real t = -log(1 - u) / sigma_t[0];
            Real t_hit = infinity<Real>();

            if (isect_) {
                t_hit = distance(ray.org, isect_->position);
            }

            if (t < t_hit) {
                // scatter in the medium
                scatter = true;
                transmittance = exp(-sigma_t * t);
                trans_pdf = exp(-sigma_t * t) * sigma_t;
                ray.org += t * ray.dir;
            } else {
                // hit the surface
                transmittance = exp(-sigma_t * t_hit);
                trans_pdf = exp(-sigma_t * t_hit);
                ray.org = isect_->position;
            }
        } else if (isect_) {
            ray.org = isect_->position;
        } else {
            break;
        }
        
        multi_trans_pdf *= trans_pdf;
        current_path_throughput *= transmittance / trans_pdf;

        if (!scatter && isect_ && is_light(scene.shapes[isect_->shape_id])) {
            Spectrum Le = emission(*isect_, -ray.dir, scene);
            if (never_scatter) {
                // this is the only way we can see the light source, so we don't need to do MIS
                radiance += current_path_throughput * Le;
            } else {
                // need to account for next event estimation
                int light_id = get_area_light_id(scene.shapes[isect_->shape_id]);
                const Light &light = scene.lights[light_id];
                PointAndNormal light_point{isect_->position, isect_->geometric_normal};
                Real pdf_nee = pdf_point_on_light(light, light_point, nee_p_cache, scene) * light_pmf(scene, light_id);

                Real G = max(Real(0), -dot(ray.dir, light_point.normal)) / distance_squared(nee_p_cache, light_point.position);
                Spectrum dir_pdf_ = dir_pdf * multi_trans_pdf * G;

                Vector3 w = (dir_pdf_ * dir_pdf_) / (dir_pdf_ * dir_pdf_ + pdf_nee * pdf_nee);
                // current_path_throughput already accounts for transmittance
                radiance += current_path_throughput * Le * w;
            }
        }

        if (bounces == max_depth - 1 && max_depth != -1) {
            // reach maximum bounces
            break;
        }

        if (!scatter && isect_ && isect_->material_id == -1) {
            // index-matching interface, skip through it
            current_medium_id = update_medium(*isect_, ray, current_medium_id);
            ray.tnear = get_intersection_epsilon(scene);
            ray.tfar = infinity<Real>();
            bounces++;
            continue;
        }

        if (scatter) {
            never_scatter = false;

            Spectrum nee = next_event_estimation(ray, current_medium_id, bounces, rng, nullptr, *isect_, scene);
            radiance += current_path_throughput * nee * sigma_s;
            
            const PhaseFunction &phase_function = get_phase_function(scene.media[current_medium_id]);
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
            std::optional<Vector3> next_dir = sample_phase_function(phase_function, -ray.dir, rnd_param);
            if (!next_dir) {
                break;
            }

            nee_p_cache = ray.org;
            dir_pdf = pdf_sample_phase(phase_function, -ray.dir, *next_dir);
            if (dir_pdf <= 0) {
                break;
            }

            current_path_throughput *= eval(phase_function, *next_dir, -ray.dir) /
                dir_pdf * sigma_s;
            
            ray = Ray{ray.org, *next_dir, get_intersection_epsilon(scene), infinity<Real>()};
            // reset
            multi_trans_pdf = make_const_spectrum(1);
        } else if (isect_) {
            // add surface lighting
            PathVertex isect = *isect_;
            nee_p_cache = isect.position;
            never_scatter = false;
            
            const Material &material = scene.materials[isect.material_id];
            Spectrum nee = next_event_estimation(ray, current_medium_id, bounces, rng, &material, isect, scene);
            radiance += current_path_throughput * nee;
            Vector3 dir_view = -ray.dir;
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};

            Real bsdf_rnd_param_w = next_pcg32_real<Real>(rng);
            std::optional<BSDFSampleRecord> bsdf_sample_ = sample_bsdf(
                material, dir_view, isect, scene.texture_pool, rnd_param, bsdf_rnd_param_w
            );
            if (!bsdf_sample_) {
                break;
            }

            const BSDFSampleRecord &bsdf_sample = *bsdf_sample_;
            Vector3 dir_bsdf = bsdf_sample.dir_out;
            if (bsdf_sample.eta == 0) {
                // reflective
                ray_diff.spread = reflect(ray_diff, isect.mean_curvature, bsdf_sample.roughness);
            } else {
                // refractive
                ray_diff.spread = refract(ray_diff, isect.mean_curvature, bsdf_sample.eta, bsdf_sample.roughness);
                eta_scale /= bsdf_sample.eta * bsdf_sample.eta;
                current_medium_id = update_medium(isect, ray, current_medium_id);
            }

            Ray bsdf_ray{isect.position, dir_bsdf, get_intersection_epsilon(scene), infinity<Real>()};

            Spectrum f = eval(material, dir_view, dir_bsdf, isect, scene.texture_pool);
            Real p2 = pdf_sample_bsdf(material, dir_view, dir_bsdf, isect, scene.texture_pool);
            
            if (p2 <= 0) {
                break;
            }

            current_path_throughput *= f / p2;
            dir_pdf = p2;
            ray = bsdf_ray;
            multi_trans_pdf = make_const_spectrum(1);
        } else {
            break;
        }

        Real rr_prob = Real(1);
        if (bounces >= rr_depth) {
            // for refraction, we need to account for the change in path throughput due to eta
            rr_prob = min(Real(0.95), max((1 / eta_scale) * current_path_throughput));
            if (next_pcg32_real<Real>(rng) > rr_prob) {
                break;
            } else {
                current_path_throughput /= rr_prob;
            }
        }
        bounces++;
    }
    return radiance;
}

// Augmented next event estimation with ratio tracking for heterogeneous media
Spectrum next_event_estimation_het(
    Vector3 scatter_pos,
    Vector3 dir_view,  // -ray.dir at scatter/surface point
    int current_medium_id,
    int bounces,
    pcg32_state &rng,
    const Material *material,
    const PathVertex *isect,  // only used when material != nullptr
    const Scene &scene
) {
    // random params preparation
    Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
    Real light_w = next_pcg32_real<Real>(rng);
    Real shape_w = next_pcg32_real<Real>(rng);
    int light_id = sample_light(scene, light_w);
    const Light &light = scene.lights[light_id];
    PointAndNormal point_on_light = sample_point_on_light(light, scatter_pos, rnd_param, shape_w, scene);
    Vector3 p_prime = point_on_light.position;

    // compute transmittance to light. Skip through index-matching shapes.
    Spectrum T_light = make_const_spectrum(1);
    Spectrum p_trans_nee = make_const_spectrum(1);
    Spectrum p_trans_dir = make_const_spectrum(1);
    Vector3 current_p = scatter_pos;
    int shadow_medium_id = current_medium_id;
    int shadow_bounces = 0;
    Vector3 dir_light = normalize(p_prime - scatter_pos);

    while (true) {
        Ray shadow_ray{current_p, dir_light, get_shadow_epsilon(scene), (1 - get_shadow_epsilon(scene)) * distance(current_p, p_prime)};
        std::optional<PathVertex> isect_ = intersect(scene, shadow_ray);
        Real next_t = distance(current_p, p_prime);
        if (isect_) {
            next_t = distance(current_p, isect_->position);
        }

        // Account for the transmittance to next_t
        if (shadow_medium_id != -1) {
            const Medium &medium = scene.media[shadow_medium_id];
            Spectrum majorant = get_majorant(medium, shadow_ray);

            Real u = next_pcg32_real<Real>(rng);
            int channel = std::clamp(int(u * 3), 0, 2);
            Real accum_t = 0;
            int iteration = 0;

            while (true) {
                if (majorant[channel] <= 0) {
                    break;
                }
                if (iteration >= scene.options.max_null_collisions) {
                    break;
                }

                Real t = -log(1 - next_pcg32_real<Real>(rng)) / majorant[channel];
                Real dt = next_t - accum_t;
                accum_t = min(accum_t + t, next_t);

                if (t < dt) {
                    // didn't hit the surface, so this is a null-scattering event
                    Vector3 pos = current_p + accum_t * dir_light;
                    Spectrum sigma_a = get_sigma_a(medium, pos);
                    Spectrum sigma_s = get_sigma_s(medium, pos);
                    Spectrum sigma_t = sigma_a + sigma_s;
                    Spectrum sigma_n = max(majorant - sigma_t, make_zero_spectrum());
                    
                    Real max_maj = max(majorant);
                    Spectrum exp_term = exp(-majorant * t);
                    T_light *= exp_term * sigma_n / max_maj;
                    p_trans_nee *= exp_term * majorant / max_maj;
                    Spectrum real_prob = sigma_t / majorant;
                    p_trans_dir *= exp_term * majorant * (make_const_spectrum(1) - real_prob) / max_maj;

                    if (max(T_light) <= 0) { // optimization for places where sigma_n = 0
                        break;
                    }
                } else {
                    // hit the surface
                    Spectrum exp_term = exp(-majorant * dt);
                    T_light *= exp_term;
                    p_trans_nee *= exp_term;
                    p_trans_dir *= exp_term;
                    break;
                }
                iteration++;
            }
        }

        if (!isect_) break;
        if (isect_->material_id >= 0) return make_zero_spectrum();

        shadow_bounces++;
        if (scene.options.max_depth != -1 &&
            bounces + shadow_bounces + 1 >= scene.options.max_depth) {
            return make_zero_spectrum();
        }

        shadow_medium_id = update_medium(*isect_, shadow_ray, shadow_medium_id);
        current_p = isect_->position;
    }

    if (T_light[0] > 0 && T_light[1] > 0 && T_light[2] > 0) {
        Real G = max(Real(0), -dot(dir_light, point_on_light.normal)) / distance_squared(scatter_pos, p_prime);
        Spectrum Le = emission(light, -dir_light, Real(0), point_on_light, scene);
        Real pdf_nee = light_pmf(scene, light_id) * pdf_point_on_light(light, point_on_light, scatter_pos, scene);

        if (pdf_nee <= 0) {
            return make_zero_spectrum();
        }

        Spectrum rho;
        Real scatter_pdf;
        if (material) {
            // surface vertex, sample BSDF pdf
            rho = eval(*material, dir_view, dir_light, *isect, scene.texture_pool);
            scatter_pdf = pdf_sample_bsdf(*material, dir_view, dir_light, *isect, scene.texture_pool);
        } else {
            // medium vertex, sample phase function pdf
            PhaseFunction phase_function = get_phase_function(scene.media[current_medium_id]);
            rho = eval(phase_function, dir_view, dir_light);
            scatter_pdf = pdf_sample_phase(phase_function, dir_view, dir_light);
        }

        Real avg_p_trans_dir = average(p_trans_dir);
        Real avg_p_trans_nee = average(p_trans_nee);

        Real pdf_scatter = scatter_pdf * G * avg_p_trans_dir;
        Real w = (pdf_nee * pdf_nee) / (pdf_nee * pdf_nee + pdf_scatter * pdf_scatter);

        Spectrum T_estimate = make_zero_spectrum();
        if (avg_p_trans_nee > 0) {
            T_estimate = T_light / avg_p_trans_nee;
        }

        return T_estimate * rho * Le * G / pdf_nee * w;
    }
    return make_zero_spectrum();
}

// The final volumetric renderer: 
// multiple chromatic heterogeneous volumes with multiple scattering
// with MIS between next event estimation and phase function sampling
// with surface lighting
Spectrum vol_path_tracing(const Scene &scene,
                          int x, int y, /* pixel coordinates */
                          pcg32_state &rng) {
    // Homework 2: implememt this!
    int w = scene.camera.width, h = scene.camera.height;
    Vector2 screen_pos{(x + next_pcg32_real<Real>(rng)) / w, (y + next_pcg32_real<Real>(rng)) / h};
    RayDifferential ray_diff = init_ray_differential(Real(0), Real(0));
    Ray ray = sample_primary(scene.camera, screen_pos);
    int current_medium_id = scene.camera.medium_id;

    Spectrum current_path_throughput = make_const_spectrum(1);
    Spectrum radiance = make_zero_spectrum();
    int bounces = 0;
    Real dir_pdf = Real(0);
    Vector3 nee_p_cache = make_zero_spectrum();
    Spectrum multi_trans_dir_pdf = make_const_spectrum(1);
    bool never_scatter = true;
    Real eta_scale = Real(1);

    const int max_depth = scene.options.max_depth;
    const int rr_depth = scene.options.rr_depth;

    while (true) {
        bool scatter = false;
        std::optional<PathVertex> isect_ = intersect(scene, ray);
        Spectrum transmittance = make_const_spectrum(1);
        Spectrum trans_dir_pdf = make_const_spectrum(1);
        Spectrum trans_nee_pdf = make_const_spectrum(1);
        Spectrum sigma_s_scatter = make_zero_spectrum();

        if (current_medium_id != -1) {
            const Medium &current_medium = scene.media[current_medium_id];
            Spectrum majorant = get_majorant(current_medium, ray);

            Real u = next_pcg32_real<Real>(rng);
            int channel = std::clamp(int(u * 3), 0, 2);
            Real accum_t = 0;
            int iteration = 0;

            Real t_hit = infinity<Real>();
            if (isect_) {
                t_hit = distance(ray.org, isect_->position);
            }

            while (true) {
                if (majorant[channel] <= 0) {
                    break;
                }
                if (iteration >= scene.options.max_null_collisions) {
                    break;
                }

                Real t = -log(1 - next_pcg32_real<Real>(rng)) / majorant[channel];
                Real dt = t_hit - accum_t;
                accum_t = min(accum_t + t, t_hit);

                if (t < dt) {
                    // didn't hit the surface, so this is a null-scattering event
                    Vector3 pos = ray.org + accum_t * ray.dir;
                    Spectrum sigma_a = get_sigma_a(current_medium, pos);
                    Spectrum sigma_s = get_sigma_s(current_medium, pos);
                    Spectrum sigma_t = sigma_a + sigma_s;
                    Spectrum sigma_n = max(majorant - sigma_t, make_zero_spectrum());
                    Real max_maj = max(majorant);
                    Spectrum exp_term = exp(-majorant * t);
                    Spectrum real_prob = sigma_t / majorant;

                    if (next_pcg32_real<Real>(rng) < real_prob[channel]) {
                        // hit a "real" particle
                        scatter = true;
                        transmittance *= exp_term / max_maj;
                        trans_dir_pdf *= exp_term * majorant * real_prob / max_maj;
                        // don't update trans_nee_pdf since we scatter
                        sigma_s_scatter = sigma_s;
                        ray.org = pos;
                        break;
                    } else {
                        // hit a "fake" particle
                        transmittance *= exp_term * sigma_n / max_maj;
                        trans_dir_pdf *= exp_term * majorant * (make_const_spectrum(1) - real_prob) / max_maj;
                        trans_nee_pdf *= exp_term * majorant / max_maj;
                    }
                } else {
                    // Reached the surface
                    Spectrum exp_term = exp(-majorant * dt);
                    transmittance *= exp_term;
                    trans_dir_pdf *= exp_term;
                    trans_nee_pdf *= exp_term;
                    break;
                }
                iteration++;
            }
        }

        // Update throughput
        Real avg_td = average(trans_dir_pdf);
        if (avg_td > 0) {
            current_path_throughput *= transmittance / avg_td;
        }
        multi_trans_dir_pdf *= trans_dir_pdf;

        // Set ray origin for surface hit
        if (!scatter && isect_) {
            ray.org = isect_->position;
        }
        if (!scatter && !isect_) {
            break;
        }

        // Surface lighting
        if (!scatter && isect_ && is_light(scene.shapes[isect_->shape_id])) {
            Spectrum Le = emission(*isect_, -ray.dir, scene);
            if (never_scatter) {
                // this is the only way we can see the light source, so we don't need to do MIS
                radiance += current_path_throughput * Le;
            } else {
                // need to account for next event estimation
                int light_id = get_area_light_id(scene.shapes[isect_->shape_id]);
                const Light &light = scene.lights[light_id];
                PointAndNormal light_point{isect_->position, isect_->geometric_normal};
                Real pdf_nee = pdf_point_on_light(light, light_point, nee_p_cache, scene) * light_pmf(scene, light_id);

                Real G = max(Real(0), -dot(ray.dir, light_point.normal)) / distance_squared(nee_p_cache, light_point.position);
                Spectrum dir_pdf_ = dir_pdf * multi_trans_dir_pdf * G;

                Spectrum w = (dir_pdf_ * dir_pdf_) / (dir_pdf_ * dir_pdf_ + pdf_nee * pdf_nee);
                radiance += current_path_throughput * Le * w;
            }
        }

        // Max depth
        if (bounces == max_depth - 1 && max_depth != -1) {
            break;
        }

        // Index-matching surface
        if (!scatter && isect_ && isect_->material_id == -1) {
            current_medium_id = update_medium(*isect_, ray, current_medium_id);
            ray.tnear = get_intersection_epsilon(scene);
            ray.tfar = infinity<Real>();
            bounces++;
            continue;
        }

        if (scatter) {
            // Medium scattering
            never_scatter = false;
            Spectrum nee = next_event_estimation_het(ray.org, -ray.dir, current_medium_id, 
                bounces, rng, nullptr, nullptr, scene);
            radiance += current_path_throughput * nee * sigma_s_scatter;

            // Phase function sampling
            const PhaseFunction &phase_function = get_phase_function(scene.media[current_medium_id]);
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
            std::optional<Vector3> next_dir = sample_phase_function(phase_function, -ray.dir, rnd_param);
            if (!next_dir) {
                break;
            }

            nee_p_cache = ray.org;
            dir_pdf = pdf_sample_phase(phase_function, -ray.dir, *next_dir);
            if (dir_pdf <= 0) {
                break;
            }

            current_path_throughput *= eval(phase_function, *next_dir, -ray.dir) / dir_pdf * sigma_s_scatter;

            ray = Ray{ray.org, *next_dir, get_intersection_epsilon(scene), infinity<Real>()};
            multi_trans_dir_pdf = make_const_spectrum(1);
        } else if (isect_) {
            // Surface interaction
            PathVertex isect = *isect_;
            nee_p_cache = isect.position;
            never_scatter = false;
            const Material &material = scene.materials[isect.material_id];

            // NEE with ratio tracking
            Spectrum nee = next_event_estimation_het(isect.position, -ray.dir, current_medium_id,
                bounces, rng, &material, &isect, scene);
            radiance += current_path_throughput * nee;

            // BSDF sampling
            Vector3 dir_view = -ray.dir;
            Vector2 rnd_param{next_pcg32_real<Real>(rng), next_pcg32_real<Real>(rng)};
            Real bsdf_rnd_param_w = next_pcg32_real<Real>(rng);
            std::optional<BSDFSampleRecord> bsdf_sample_ = sample_bsdf(material, dir_view, isect, scene.texture_pool,
                rnd_param, bsdf_rnd_param_w);
            if (!bsdf_sample_) {
                break;
            }

            const BSDFSampleRecord &bsdf_sample = *bsdf_sample_;
            Vector3 dir_bsdf = bsdf_sample.dir_out;
            if (bsdf_sample.eta == 0) {
                // reflective
                ray_diff.spread = reflect(ray_diff, isect.mean_curvature, bsdf_sample.roughness);
            } else {
                // refractive
                ray_diff.spread = refract(ray_diff, isect.mean_curvature, bsdf_sample.eta, bsdf_sample.roughness);
                eta_scale /= bsdf_sample.eta * bsdf_sample.eta;
                current_medium_id = update_medium(isect, ray, current_medium_id);
            }

            Spectrum f = eval(material, dir_view, dir_bsdf, isect, scene.texture_pool);
            Real p2 = pdf_sample_bsdf(material, dir_view, dir_bsdf, isect, scene.texture_pool);
            if (p2 <= 0) {
                break;
            }

            current_path_throughput *= f / p2;
            dir_pdf = p2;
            ray = Ray{isect.position, dir_bsdf, get_intersection_epsilon(scene), infinity<Real>()};
            multi_trans_dir_pdf = make_const_spectrum(1);
        } else {
            break;
        }

        Real rr_prob = Real(1);
        if (bounces >= rr_depth) {
            rr_prob = min(Real(0.95), max((1 / eta_scale) * current_path_throughput));
            if (next_pcg32_real<Real>(rng) > rr_prob) {
                break;
            }
            current_path_throughput /= rr_prob;
        }
        bounces++;
    }
    return radiance;
}
