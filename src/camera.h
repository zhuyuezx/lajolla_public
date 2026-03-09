#pragma once

#include "lajolla.h"
#include "filter.h"
#include "matrix.h"
#include "vector.h"
#include "ray.h"

/// Currently we support a pinhole perspective camera and an orthographic camera
struct Camera {
    Camera() {}
    Camera(const Matrix4x4 &cam_to_world,
           Real fov, // in degree
           int width, int height,
           const Filter &filter,
           int medium_id);

    /// Orthographic camera constructor.
    /// ortho_scale controls the half-width of the view volume in world units.
    Camera(const Matrix4x4 &cam_to_world,
           int width, int height,
           Real ortho_scale,
           const Filter &filter,
           int medium_id);

    Matrix4x4 sample_to_cam, cam_to_sample;
    Matrix4x4 cam_to_world, world_to_cam;
    int width, height;
    Filter filter;

    bool is_ortho = false;   ///< true => orthographic projection
    Real ortho_scale = Real(5); ///< half-width in world units (orthographic only)

    int medium_id; // for participating media rendering in homework 2
};

/// Given screen position in [0, 1] x [0, 1],
/// generate a camera ray.
Ray sample_primary(const Camera &camera,
                   const Vector2 &screen_pos);
