#include "camera.h"
#include "lajolla.h"
#include "transform.h"

#include <cmath>

Camera::Camera(const Matrix4x4 &cam_to_world,
               Real fov,
               int width, int height,
               const Filter &filter,
               int medium_id)
    : cam_to_world(cam_to_world),
      world_to_cam(inverse(cam_to_world)),
      width(width), height(height),
      filter(filter),
      is_ortho(false),
      medium_id(medium_id) {
    Real aspect = (Real)width / (Real)height;
    cam_to_sample = scale(Vector3(-Real(0.5), -Real(0.5) * aspect, Real(1.0))) *
                    translate(Vector3(-Real(1.0), -Real(1.0) / aspect, Real(0.0))) *
                    perspective(fov);
    sample_to_cam = inverse(cam_to_sample);
}

Camera::Camera(const Matrix4x4 &cam_to_world,
               int width, int height,
               Real ortho_scale,
               const Filter &filter,
               int medium_id)
    : cam_to_world(cam_to_world),
      world_to_cam(inverse(cam_to_world)),
      width(width), height(height),
      filter(filter),
      is_ortho(true), ortho_scale(ortho_scale),
      medium_id(medium_id) {
    // For orthographic cameras the projection matrices are unused,
    // but initialize them to identity to avoid undefined values.
    cam_to_sample = Matrix4x4::identity();
    sample_to_cam = Matrix4x4::identity();
}

Ray sample_primary(const Camera &camera,
                   const Vector2 &screen_pos) {
    // screen_pos' domain is [0, 1]^2
    Vector2 pixel_pos{screen_pos.x * camera.width, screen_pos.y * camera.height};

    // Importance sample from the pixel filter (see filter.h for more explanation).
    Real dx = pixel_pos.x - floor(pixel_pos.x);
    Real dy = pixel_pos.y - floor(pixel_pos.y);
    Vector2 offset = sample(camera.filter, Vector2{dx, dy});
    Vector2 remapped_pos{
      (floor(pixel_pos.x) + Real(0.5) + offset.x) / camera.width,
      (floor(pixel_pos.y) + Real(0.5) + offset.y) / camera.height};

    if (camera.is_ortho) {
        // Orthographic: all rays are parallel (forward = +Z in camera space).
        // The ray origin slides across the film plane uniformly.
        Real aspect = Real(camera.width) / Real(camera.height);
        // Map [0,1] UV to [-scale, +scale] x [-scale/aspect, +scale/aspect]
        Real cx = (remapped_pos[0] - Real(0.5)) * Real(2) * camera.ortho_scale;
        Real cy = -(remapped_pos[1] - Real(0.5)) * Real(2) * camera.ortho_scale / aspect;
        Vector3 cam_origin{cx, cy, Real(0)};
        Vector3 cam_dir   {Real(0), Real(0), Real(1)};
        return Ray{xform_point (camera.cam_to_world, cam_origin),
                   normalize(xform_vector(camera.cam_to_world, cam_dir)),
                   Real(0), infinity<Real>()};
    }

    Vector3 pt = xform_point(camera.sample_to_cam,
        Vector3(remapped_pos[0], remapped_pos[1], Real(0)));
    Vector3 dir = normalize(pt);
    return Ray{xform_point(camera.cam_to_world, Vector3{0, 0, 0}),
               normalize(xform_vector(camera.cam_to_world, dir)),
               Real(0), infinity<Real>()};
}
