// ============================================================================
// interactive_viewer.cpp — Unlit Low-Poly Viewer (SDL2 + Embree 4)
// ============================================================================
// Deer-Hunter-II / Sokpop style: perspective camera, unlit flat albedo with
// cast ground shadows, linear distance fog fading to a warm sky.
// No outlines, no anti-aliasing — raw aliased pixels.
//
// Build:  cmake --build build --target interactive_viewer
// Run:    ./build/interactive_viewer scenes/skypop_game/meshes
// ============================================================================

#include <SDL.h>
#include <embree4/rtcore.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

// ─── Render / window constants ───────────────────────────────────────────────
static constexpr int RENDER_W = 400;
static constexpr int RENDER_H = 300;
static constexpr int WINDOW_W = 800;
static constexpr int WINDOW_H = 600;
static constexpr float MOVE_SPEED = 0.35f;
static constexpr float GROUND_HALF = 40.f;
static constexpr float FOV_DEG = 70.f; // perspective field of view

// ─── Vec3 math ───────────────────────────────────────────────────────────────
struct Vec3 {
  float x, y, z;
  Vec3 operator+(Vec3 b) const { return {x + b.x, y + b.y, z + b.z}; }
  Vec3 operator-(Vec3 b) const { return {x - b.x, y - b.y, z - b.z}; }
  Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
  Vec3 operator*(Vec3 b) const { return {x * b.x, y * b.y, z * b.z}; }
  Vec3 operator-() const { return {-x, -y, -z}; }
};
static float dot3(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static Vec3 cross3(Vec3 a, Vec3 b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
static float vlen(Vec3 v) { return sqrtf(dot3(v, v)); }
static Vec3 vnorm(Vec3 v) {
  float l = vlen(v);
  return v * (1.f / l);
}
static float clampf(float v, float lo, float hi) {
  return std::max(lo, std::min(hi, v));
}

// ─── Unlit + Fog settings (Deer Hunter II / Sokpop savanna) ──────────────────
// Sun almost straight down → high noon, minimal lateral shadows
static const Vec3 LIGHT_DIR = vnorm({0.1f, 1.0f, 0.15f});
// HARSHER contrast. Dropping from 0.85 to 0.60 makes shadows much darker,
// selling the "bright sun" illusion.
static constexpr float SHADOW_MULT = 0.60f;
// Blinding, bleached hot-sand sky color
static const Vec3 SKY_COLOR = {0.98f, 0.92f, 0.70f};
// Push the fog way back. This removes the "misty" feel and turns it into
// distant heat haze.
static constexpr float FOG_MIN = 35.f;
static constexpr float FOG_MAX = 120.f;

// ─── Simple mesh ─────────────────────────────────────────────────────────────
struct Mesh {
  std::vector<float> verts;   // x,y,z,pad per vertex (stride 4 floats)
  std::vector<uint32_t> tris; // 3 indices per tri
  int nv = 0, nt = 0;
};

static Mesh load_obj(const std::string &path) {
  Mesh m;
  std::vector<Vec3> pos;
  std::vector<std::array<int, 3>> faces;
  std::ifstream f(path);
  if (!f.is_open()) {
    fprintf(stderr, "Cannot open %s\n", path.c_str());
    return m;
  }
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty() || line[0] == '#')
      continue;
    std::istringstream ss(line);
    std::string tok;
    ss >> tok;
    if (tok == "v") {
      float x, y, z;
      ss >> x >> y >> z;
      pos.push_back({x, y, z});
    } else if (tok == "f") {
      std::vector<int> vi;
      std::string s;
      while (ss >> s)
        vi.push_back(std::atoi(s.c_str()) - 1);
      for (int i = 1; i + 1 < (int)vi.size(); i++)
        faces.push_back({vi[0], vi[i], vi[i + 1]});
    }
  }
  m.nv = (int)pos.size();
  m.nt = (int)faces.size();
  m.verts.resize(m.nv * 4);
  for (int i = 0; i < m.nv; i++) {
    m.verts[i * 4] = pos[i].x;
    m.verts[i * 4 + 1] = pos[i].y;
    m.verts[i * 4 + 2] = pos[i].z;
    m.verts[i * 4 + 3] = 0.f;
  }
  m.tris.resize(m.nt * 3);
  for (int i = 0; i < m.nt; i++) {
    m.tris[i * 3] = faces[i][0];
    m.tris[i * 3 + 1] = faces[i][1];
    m.tris[i * 3 + 2] = faces[i][2];
  }
  return m;
}

static Mesh translate_mesh(const Mesh &src, Vec3 off) {
  Mesh m = src;
  for (int i = 0; i < m.nv; i++) {
    m.verts[i * 4] += off.x;
    m.verts[i * 4 + 1] += off.y;
    m.verts[i * 4 + 2] += off.z;
  }
  return m;
}

static Mesh make_ground(float hs, float th) {
  Mesh m;
  m.nv = 8;
  m.nt = 12;
  float v[] = {-hs, 0,   hs, 0,   hs,  0,   hs,  0,   hs,  0,  -hs,
               0,   -hs, 0,  -hs, 0,   -hs, -th, hs,  0,   hs, -th,
               hs,  0,   hs, -th, -hs, 0,   -hs, -th, -hs, 0};
  uint32_t t[] = {0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6, 0, 4, 5, 0, 5, 1,
                  2, 6, 7, 2, 7, 3, 0, 3, 7, 0, 7, 4, 1, 5, 6, 1, 6, 2};
  m.verts.assign(v, v + 32);
  m.tris.assign(t, t + 36);
  return m;
}

// Generic axis-aligned box: center (cx,cy,cz), half-extents (hx,hy,hz)
static Mesh make_box(float cx, float cy, float cz, float hx, float hy,
                     float hz) {
  Mesh m;
  m.nv = 8;
  m.nt = 12;
  float x0 = cx - hx, x1 = cx + hx, y0 = cy - hy, y1 = cy + hy, z0 = cz - hz,
        z1 = cz + hz;
  float v[] = {x0, y0, z0, 0, x1, y0, z0, 0, x1, y0, z1, 0, x0, y0, z1, 0,
               x0, y1, z0, 0, x1, y1, z0, 0, x1, y1, z1, 0, x0, y1, z1, 0};
  uint32_t t[] = {3, 2, 1, 3, 1, 0, 4, 5, 6, 4, 6, 7, 7, 6, 2, 7, 2, 3,
                  5, 4, 0, 5, 0, 1, 4, 7, 3, 4, 3, 0, 6, 5, 1, 6, 1, 2};
  m.verts.assign(v, v + 32);
  m.tris.assign(t, t + 36);
  return m;
}

// Flat polygon disc at y_val (for ponds)
static Mesh make_pond(float cx, float cz, float r, int n, float y_val) {
  Mesh m;
  m.nv = n + 1;
  m.nt = n;
  m.verts.resize((n + 1) * 4);
  m.tris.resize(n * 3);
  // Center vertex
  m.verts[0] = cx;
  m.verts[1] = y_val;
  m.verts[2] = cz;
  m.verts[3] = 0;
  for (int i = 0; i < n; i++) {
    float a = 6.28318f * i / n;
    // Irregular radius: slight wobble
    float rr = r * (0.85f + 0.15f * sinf(a * 3.f + cx));
    int vi = (i + 1) * 4;
    m.verts[vi] = cx + rr * cosf(a);
    m.verts[vi + 1] = y_val;
    m.verts[vi + 2] = cz + rr * sinf(a);
    m.verts[vi + 3] = 0;
  }
  for (int i = 0; i < n; i++) {
    int j = (i + 1) % n;
    m.tris[i * 3] = 0;
    m.tris[i * 3 + 1] = i + 1;
    m.tris[i * 3 + 2] = j + 1;
  }
  return m;
}

// Tall thin leaning reed box
static Mesh make_reed(float cx, float cz, float h, float lean_x, float lean_z) {
  float w = 0.06f;
  Mesh m = make_box(cx, h * 0.5f, cz, w, h * 0.5f, w);
  // Apply lean by shifting top vertices
  for (int i = 0; i < m.nv; i++) {
    float y_frac = (m.verts[i * 4 + 1]) / h;
    m.verts[i * 4] += lean_x * y_frac;
    m.verts[i * 4 + 2] += lean_z * y_frac;
  }
  return m;
}

// Small rock: random-ish squashed box
static Mesh make_rock(float cx, float cz, float sx, float sy, float sz) {
  return make_box(cx, sy * 0.5f, cz, sx * 0.5f, sy * 0.5f, sz * 0.5f);
}

// Deer: body box + 4 legs + head+neck
static Mesh make_deer(float cx, float cz) {
  // Body at y=0.7, horizontal
  Mesh body = make_box(cx, 0.75f, cz, 0.5f, 0.2f, 0.18f);
  // 4 legs
  Mesh legs[4];
  float lx[] = {-0.32f, 0.32f, -0.32f, 0.32f};
  float lz[] = {-0.10f, -0.10f, 0.10f, 0.10f};
  for (int i = 0; i < 4; i++)
    legs[i] = make_box(cx + lx[i], 0.3f, cz + lz[i], 0.04f, 0.3f, 0.04f);
  // Head + neck
  Mesh neck = make_box(cx + 0.5f, 0.9f, cz, 0.04f, 0.15f, 0.04f);
  Mesh head = make_box(cx + 0.55f, 1.05f, cz, 0.1f, 0.08f, 0.08f);
  // Merge all parts into one mesh
  Mesh result = body;
  Mesh parts[] = {legs[0], legs[1], legs[2], legs[3], neck, head};
  for (auto &p : parts) {
    int base = result.nv;
    for (int i = 0; i < p.nv; i++) {
      result.verts.push_back(p.verts[i * 4]);
      result.verts.push_back(p.verts[i * 4 + 1]);
      result.verts.push_back(p.verts[i * 4 + 2]);
      result.verts.push_back(0);
    }
    for (int i = 0; i < p.nt; i++) {
      result.tris.push_back(p.tris[i * 3] + base);
      result.tris.push_back(p.tris[i * 3 + 1] + base);
      result.tris.push_back(p.tris[i * 3 + 2] + base);
    }
    result.nv += p.nv;
    result.nt += p.nt;
  }
  return result;
}

// Crow: tiny dark box on the ground, optionally bobbing
static Mesh make_crow(float cx, float cz, float y_off) {
  // Body
  Mesh body = make_box(cx, 0.12f + y_off, cz, 0.08f, 0.05f, 0.05f);
  // Head (shifted slightly forward and up)
  Mesh head = make_box(cx + 0.10f, 0.18f + y_off, cz, 0.04f, 0.04f, 0.04f);
  // Beak (shifted further forward from the head, thinner)
  Mesh beak = make_box(cx + 0.16f, 0.18f + y_off, cz, 0.03f, 0.015f, 0.015f);

  // Merge parts
  Mesh result = body;
  Mesh parts[] = {head, beak};
  for (auto &p : parts) {
    int base = result.nv;
    for (int i = 0; i < p.nv; i++) {
      result.verts.push_back(p.verts[i * 4]);
      result.verts.push_back(p.verts[i * 4 + 1]);
      result.verts.push_back(p.verts[i * 4 + 2]);
      result.verts.push_back(0);
    }
    for (int i = 0; i < p.nt; i++) {
      result.tris.push_back(p.tris[i * 3] + base);
      result.tris.push_back(p.tris[i * 3 + 1] + base);
      result.tris.push_back(p.tris[i * 3 + 2] + base);
    }
    result.nv += p.nv;
    result.nt += p.nt;
  }
  return result;
}

// ─── Embree scene ────────────────────────────────────────────────────────────
struct ObjEntry {
  Vec3 color;
};
static RTCDevice g_device = nullptr;
static RTCScene g_scene = nullptr;
static std::vector<ObjEntry> g_colors; // indexed by geomID

static uint32_t register_mesh(const Mesh &m) {
  RTCGeometry geom = rtcNewGeometry(g_device, RTC_GEOMETRY_TYPE_TRIANGLE);
  auto *vb = (float *)rtcSetNewGeometryBuffer(geom, RTC_BUFFER_TYPE_VERTEX, 0,
                                              RTC_FORMAT_FLOAT3, 16, m.nv);
  memcpy(vb, m.verts.data(), m.nv * 16);
  auto *ib = (uint32_t *)rtcSetNewGeometryBuffer(geom, RTC_BUFFER_TYPE_INDEX, 0,
                                                 RTC_FORMAT_UINT3, 12, m.nt);
  memcpy(ib, m.tris.data(), m.nt * 12);
  rtcCommitGeometry(geom);
  uint32_t gid = rtcAttachGeometry(g_scene, geom);
  rtcReleaseGeometry(geom);
  return gid;
}

// Tree placement table
struct TreePlace {
  float x, z;
  int type;
};
static const TreePlace TREES[] = {
    {-25, -20, 0}, {-15, -25, 1},  {-8, -15, 2}, {-20, 5, 0}, {-12, 12, 1},
    {-5, 20, 2},   {-18, -8, 0},   {-25, 15, 1}, {-30, 0, 2}, {-10, -30, 0},
    {5, -18, 1},   {12, -25, 2},   {20, -10, 0}, {15, 8, 1},  {8, 20, 2},
    {25, -5, 0},   {18, 15, 1},    {30, -15, 2}, {10, 30, 0}, {22, 22, 1},
    {4, -2, 0},    {-3.5f, -4, 1}, {3, -6, 2},   {-6, 3, 0},  {6, 4, 2}};
static constexpr int N_TREES = sizeof(TREES) / sizeof(TREES[0]);

static Mesh g_char_template;

// Pond placement
struct PondPlace {
  float x, z, r;
  int sides;
};
static const PondPlace PONDS[] = {{-10, 15, 3.5f, 9},
                                  {18, -8, 2.8f, 7},
                                  {-22, -18, 4.0f, 11},
                                  {8, 25, 3.0f, 8}};
static constexpr int N_PONDS = sizeof(PONDS) / sizeof(PONDS[0]);

// Rock placement
struct RockPlace {
  float x, z, sx, sy, sz;
};
static const RockPlace ROCKS[] = {
    {5, 5, 0.8f, 0.4f, 0.6f},     {-14, 8, 0.5f, 0.3f, 0.7f},
    {22, 15, 1.0f, 0.5f, 0.8f},   {-8, -22, 0.6f, 0.35f, 0.5f},
    {28, -20, 0.7f, 0.45f, 0.6f}, {-30, 12, 0.9f, 0.4f, 0.7f},
    {12, 12, 0.4f, 0.25f, 0.4f},  {-5, -10, 0.65f, 0.3f, 0.55f}};
static constexpr int N_ROCKS = sizeof(ROCKS) / sizeof(ROCKS[0]);

// Deer placement
static const float DEER_POS[][2] = {{-15, 10}, {10, -15}, {25, 5}, {-8, 28}};
static constexpr int N_DEER = sizeof(DEER_POS) / sizeof(DEER_POS[0]);

// Crow placement
static const float CROW_POS[][2] = {{-3, 8},  {15, 3},   {-20, -5},
                                    {7, -12}, {-12, 22}, {30, 18}};
static constexpr int N_CROW = sizeof(CROW_POS) / sizeof(CROW_POS[0]);

static void build_scene(Vec3 char_pos, float anim_time, bool is_moving) {
  if (g_scene)
    rtcReleaseScene(g_scene);
  g_scene = rtcNewScene(g_device);
  rtcSetSceneBuildQuality(g_scene, RTC_BUILD_QUALITY_LOW);
  rtcSetSceneFlags(g_scene, RTC_SCENE_FLAG_DYNAMIC);
  g_colors.clear();

  // Ground
  Mesh ground = make_ground(GROUND_HALF, 0.4f);
  register_mesh(ground);
  g_colors.push_back({{0.96f, 0.85f, 0.55f}});

  // Trees — fully procedural (no OBJ loading)
  Vec3 trunk_col = {0.55f, 0.40f, 0.28f};
  Vec3 canopy_cols[3] = {
      {0.45f, 0.58f, 0.38f}, {0.50f, 0.60f, 0.35f}, {0.40f, 0.55f, 0.42f}};
  for (int i = 0; i < N_TREES; i++) {
    float tx = TREES[i].x, tz = TREES[i].z;
    // Vary trunk height (8–12) and canopy radius (4–6) per tree
    float th = 8.f + (i % 5) * 1.0f;
    float cr = 4.f + (i % 3) * 1.0f;
    // Trunk: tall thin box
    Mesh trunk = make_box(tx, th * 0.5f, tz, 0.4f, th * 0.5f, 0.4f);
    register_mesh(trunk);
    g_colors.push_back({trunk_col});
    // Canopy: 3 overlapping massive boxes at top of trunk
    float cy = th + cr * 0.4f;
    Mesh c1 = make_box(tx, cy, tz, cr, cr * 0.5f, cr * 0.8f);
    register_mesh(c1);
    g_colors.push_back({canopy_cols[TREES[i].type % 3]});
    Mesh c2 = make_box(tx, cy + 0.4f, tz, cr * 0.8f, cr * 0.55f, cr);
    register_mesh(c2);
    g_colors.push_back({canopy_cols[TREES[i].type % 3]});
    Mesh c3 = make_box(tx, cy - 0.3f, tz, cr * 0.6f, cr * 0.45f, cr * 0.6f);
    register_mesh(c3);
    g_colors.push_back({canopy_cols[TREES[i].type % 3]});
  }

  // Ponds
  Vec3 pond_col = {0.4f, 0.75f, 0.8f};
  for (int i = 0; i < N_PONDS; i++) {
    Mesh p =
        make_pond(PONDS[i].x, PONDS[i].z, PONDS[i].r, PONDS[i].sides, 0.02f);
    register_mesh(p);
    g_colors.push_back({pond_col});
  }

  // Reeds around ponds
  Vec3 reed_col = {0.3f, 0.55f, 0.45f};
  for (int i = 0; i < N_PONDS; i++) {
    int n_reeds = 10 + (i * 3) % 5;
    for (int j = 0; j < n_reeds; j++) {
      float a = 6.28318f * j / n_reeds;
      float rr = PONDS[i].r * (1.05f + 0.15f * sinf(a * 2.f));
      float rx = PONDS[i].x + rr * cosf(a);
      float rz = PONDS[i].z + rr * sinf(a);
      float h = 0.6f + 0.4f * sinf(j * 1.7f);
      float lx = 0.15f * sinf(j * 2.3f);
      float lz = 0.15f * cosf(j * 1.9f);
      Mesh reed = make_reed(rx, rz, h, lx, lz);
      register_mesh(reed);
      g_colors.push_back({reed_col});
    }
  }

  // Rocks
  Vec3 rock_col = {0.75f, 0.70f, 0.65f};
  for (int i = 0; i < N_ROCKS; i++) {
    Mesh r = make_rock(ROCKS[i].x, ROCKS[i].z, ROCKS[i].sx, ROCKS[i].sy,
                       ROCKS[i].sz);
    register_mesh(r);
    g_colors.push_back({rock_col});
  }

  // Deer
  Vec3 deer_col = {0.62f, 0.38f, 0.25f};
  for (int i = 0; i < N_DEER; i++) {
    Mesh d = make_deer(DEER_POS[i][0], DEER_POS[i][1]);
    register_mesh(d);
    g_colors.push_back({deer_col});
  }

  // Crows (with gentle bobbing)
  Vec3 crow_col = {0.18f, 0.18f, 0.20f};
  for (int i = 0; i < N_CROW; i++) {
    float bob = fabsf(sinf(anim_time * 2.f + i * 1.5f)) * 0.05f;
    Mesh c = make_crow(CROW_POS[i][0], CROW_POS[i][1], bob);
    register_mesh(c);
    g_colors.push_back({crow_col});
  }

  // Character with bob & wobble
  Mesh cm = g_char_template;
  if (is_moving) {
    float bob_y = fabsf(sinf(anim_time * 12.f)) * 0.08f;
    float roll = sinf(anim_time * 12.f) * 0.06f; // subtle Z-roll
    for (int i = 0; i < cm.nv; i++) {
      float y = cm.verts[i * 4 + 1];
      float x = cm.verts[i * 4];
      // Apply roll rotation around character center
      cm.verts[i * 4] = x * cosf(roll) - y * sinf(roll);
      cm.verts[i * 4 + 1] = x * sinf(roll) + y * cosf(roll) + bob_y;
    }
  }
  cm = translate_mesh(cm, char_pos);
  register_mesh(cm);
  g_colors.push_back({{0.88f, 0.72f, 0.58f}});

  rtcCommitScene(g_scene);
}

// ─── Camera (Cinematic Third-Person) ──────────────────────────────────────
struct Camera {
  Vec3 origin, right, up, fwd;
  float half_tan;
};

static Camera make_camera(Vec3 char_pos, float azimuth, float altitude,
                          float radius) {
  Camera c;
  // Spherical → Cartesian offset from player
  Vec3 offset;
  offset.x = radius * cosf(altitude) * sinf(azimuth);
  offset.y = radius * sinf(altitude);
  offset.z = -radius * cosf(altitude) * cosf(azimuth);
  c.origin = char_pos + offset;
  Vec3 target = {char_pos.x, 1.0f, char_pos.z};
  c.fwd = vnorm(target - c.origin);
  c.right = vnorm(cross3(c.fwd, {0, 1, 0}));
  c.up = cross3(c.right, c.fwd);
  c.half_tan = tanf(FOV_DEG * 3.14159265f / 360.f);
  return c;
}

// ─── Unlit Render with Distance Fog ──────────────────────────────────────────
static inline uint8_t to_byte(float v) {
  v = clampf(v, 0.f, 1.f);
  // No gamma — raw unlit values straight to framebuffer (matches Sokpop look)
  return (uint8_t)(v * 255.f + 0.5f);
}

static void render_frame(const Camera &cam, uint32_t *fb) {
  float aspect = (float)RENDER_W / (float)RENDER_H;
  for (int y = 0; y < RENDER_H; y++) {
    for (int x = 0; x < RENDER_W; x++) {
      // ── Task 1: Perspective (pinhole) ray — no AA, no jitter ──
      // Pixel center only — integer + 0.5, no sub-pixel sampling
      float px = ((float)x + 0.5f) / RENDER_W * 2.f - 1.f;
      float py = -(((float)y + 0.5f) / RENDER_H * 2.f - 1.f);
      px *= cam.half_tan * aspect; // scale by FOV and aspect
      py *= cam.half_tan;
      // Ray direction in world space (all rays originate from camera)
      Vec3 rd = vnorm(cam.right * px + cam.up * py + cam.fwd);
      Vec3 ro = cam.origin;

      RTCRayHit rh = {};
      rh.ray.org_x = ro.x;
      rh.ray.org_y = ro.y;
      rh.ray.org_z = ro.z;
      rh.ray.dir_x = rd.x;
      rh.ray.dir_y = rd.y;
      rh.ray.dir_z = rd.z;
      rh.ray.tnear = 1e-3f;
      rh.ray.tfar = 1e9f;
      rh.ray.mask = 0xFFFFFFFF;
      rh.ray.flags = 0;
      rh.hit.geomID = RTC_INVALID_GEOMETRY_ID;
      rh.hit.instID[0] = RTC_INVALID_GEOMETRY_ID;

      rtcIntersect1(g_scene, &rh);

      Vec3 color;
      if (rh.hit.geomID != RTC_INVALID_GEOMETRY_ID) {
        // ── TRUE UNLIT: pure albedo, no N·L, no diffuse gradient ──
        Vec3 albedo = g_colors[rh.hit.geomID].color;

        // Cast shadow ray toward light
        Vec3 hp = ro + rd * rh.ray.tfar;
        Vec3 N = vnorm({rh.hit.Ng_x, rh.hit.Ng_y, rh.hit.Ng_z});
        Vec3 so = hp + N * 0.01f; // bias along geometric normal
        RTCRay sr = {};
        sr.org_x = so.x;
        sr.org_y = so.y;
        sr.org_z = so.z;
        sr.dir_x = LIGHT_DIR.x;
        sr.dir_y = LIGHT_DIR.y;
        sr.dir_z = LIGHT_DIR.z;
        sr.tnear = 1e-4f;
        sr.tfar = 1e9f;
        sr.mask = 0xFFFFFFFF;
        sr.flags = 0;
        rtcOccluded1(g_scene, &sr);
        bool in_shadow = (sr.tfar < 0);

        color = in_shadow ? albedo * SHADOW_MULT : albedo;

        // ── Task 4: Linear distance fog ──
        float t = rh.ray.tfar;
        float fog = clampf((t - FOG_MIN) / (FOG_MAX - FOG_MIN), 0.f, 1.f);
        color = color * (1.f - fog) + SKY_COLOR * fog;
      } else {
        // Ray missed — pure sky
        color = SKY_COLOR;
      }
      fb[y * RENDER_W + x] = (255u << 24) | (to_byte(color.x) << 16) |
                             (to_byte(color.y) << 8) | to_byte(color.z);
    }
  }
}

// ─── Main ────────────────────────────────────────────────────────────────────
int main(int argc, char **argv) {
  std::string mesh_dir = "scenes/skypop_game/meshes";
  if (argc > 1)
    mesh_dir = argv[1];

  g_char_template = load_obj(mesh_dir + "/character.obj");
  // Trees are now fully procedural — no OBJ loading needed
  printf("Loaded meshes from %s\n", mesh_dir.c_str());

  // Init Embree
  g_device = rtcNewDevice(nullptr);
  if (!g_device) {
    fprintf(stderr, "Embree init failed\n");
    return 1;
  }

  // Init SDL2
  if (SDL_Init(SDL_INIT_VIDEO) < 0) {
    fprintf(stderr, "SDL init failed: %s\n", SDL_GetError());
    return 1;
  }
  SDL_Window *win = SDL_CreateWindow(
      "Unlit Fog Viewer — Arrow keys / ESC", SDL_WINDOWPOS_CENTERED,
      SDL_WINDOWPOS_CENTERED, WINDOW_W, WINDOW_H, 0);
  // SDL_RENDERER_ACCELERATED with nearest-neighbor scaling for crisp pixels
  SDL_Renderer *ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED);
  SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0"); // nearest-neighbor (no AA)
  SDL_Texture *tex =
      SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                        SDL_TEXTUREACCESS_STREAMING, RENDER_W, RENDER_H);

  std::vector<uint32_t> fb(RENDER_W * RENDER_H);
  Vec3 char_pos = {0, 0, 0};

  // Camera orbit state (spherical coordinates)
  float cam_azimuth = 0.0f;
  float cam_altitude = 0.7f; // ~40 degrees
  float cam_radius = 7.8f;
  const float CAM_SPEED = 0.03f;

  // Initial build + render
  float anim_time = 0.f;
  bool is_moving = false;
  build_scene(char_pos, anim_time, false);
  Camera cam = make_camera(char_pos, cam_azimuth, cam_altitude, cam_radius);
  render_frame(cam, fb.data());
  bool needs_render = false;

  bool running = true;
  Uint32 last_tick = SDL_GetTicks();

  while (running) {
    SDL_Event ev;
    while (SDL_PollEvent(&ev)) {
      if (ev.type == SDL_QUIT)
        running = false;
      if (ev.type == SDL_KEYDOWN && ev.key.keysym.sym == SDLK_ESCAPE)
        running = false;
    }

    const Uint8 *keys = SDL_GetKeyboardState(nullptr);

    // WASD: orbit camera
    if (keys[SDL_SCANCODE_A]) {
      cam_azimuth -= CAM_SPEED;
      needs_render = true;
    }
    if (keys[SDL_SCANCODE_D]) {
      cam_azimuth += CAM_SPEED;
      needs_render = true;
    }
    if (keys[SDL_SCANCODE_W]) {
      cam_altitude += CAM_SPEED;
      needs_render = true;
    }
    if (keys[SDL_SCANCODE_S]) {
      cam_altitude -= CAM_SPEED;
      needs_render = true;
    }
    // Clamp altitude so camera can't flip or go underground
    cam_altitude = clampf(cam_altitude, 0.1f, 1.5f);

    // Dynamic movement vectors: recalculate from azimuth each frame
    Vec3 move_fwd = {-sinf(cam_azimuth), 0.f, cosf(cam_azimuth)};
    Vec3 move_right = {cosf(cam_azimuth), 0.f, sinf(cam_azimuth)};

    // Arrow keys: move character relative to camera direction
    Vec3 old_pos = char_pos;
    if (keys[SDL_SCANCODE_RIGHT]) {
      char_pos = char_pos + move_right * MOVE_SPEED;
    }
    if (keys[SDL_SCANCODE_LEFT]) {
      char_pos = char_pos - move_right * MOVE_SPEED;
    }
    if (keys[SDL_SCANCODE_UP]) {
      char_pos = char_pos + move_fwd * MOVE_SPEED;
    }
    if (keys[SDL_SCANCODE_DOWN]) {
      char_pos = char_pos - move_fwd * MOVE_SPEED;
    }

    // Clamp to ground bounds
    float lim = GROUND_HALF - 2.f;
    char_pos.x = std::max(-lim, std::min(lim, char_pos.x));
    char_pos.z = std::max(-lim, std::min(lim, char_pos.z));

    is_moving = (char_pos.x != old_pos.x || char_pos.z != old_pos.z);
    if (is_moving)
      needs_render = true;

    // Advance animation time (for crow bobbing + player bob)
    anim_time += 0.016f; // ~60fps tick
    // Re-render whenever moving or periodically for crow animation
    static int anim_tick = 0;
    if (++anim_tick >= 8) {
      anim_tick = 0;
      needs_render = true;
    }

    if (needs_render) {
      build_scene(char_pos, anim_time, is_moving);
      cam = make_camera(char_pos, cam_azimuth, cam_altitude, cam_radius);
      render_frame(cam, fb.data());
      needs_render = false;
    }

    SDL_UpdateTexture(tex, nullptr, fb.data(), RENDER_W * 4);
    SDL_RenderClear(ren);
    SDL_RenderCopy(ren, tex, nullptr, nullptr);
    SDL_RenderPresent(ren);

    // FPS display in title
    Uint32 now = SDL_GetTicks();
    if (now - last_tick >= 500) {
      float fps = 1000.f / std::max(1u, now - last_tick);
      char title[128];
      snprintf(title, sizeof(title),
               "Unlit Fog — pos(%.1f,%.1f) az=%.1f° — %.0f FPS — WASD orbit / "
               "Arrows move",
               char_pos.x, char_pos.z, cam_azimuth * 57.3f, fps);
      SDL_SetWindowTitle(win, title);
      last_tick = now;
    }

    SDL_Delay(16); // ~60 Hz poll rate
  }

  rtcReleaseScene(g_scene);
  rtcReleaseDevice(g_device);
  SDL_DestroyTexture(tex);
  SDL_DestroyRenderer(ren);
  SDL_DestroyWindow(win);
  SDL_Quit();
  return 0;
}
