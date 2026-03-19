// ============================================================================
// screenshot_viewer.cpp — Headless screenshot dumper
// Same rendering as interactive_viewer.cpp but outputs PPM files, no SDL.
// Build: c++ -O2 -std=c++17 -I/opt/homebrew/include -L/opt/homebrew/lib
//        -lembree4 -o build/screenshot_viewer final_project/screenshot_viewer.cpp
// Run:   ./build/screenshot_viewer <output_prefix> [azimuth_deg]
// ============================================================================

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

// ─── Render constants ────────────────────────────────────────────────────────
static constexpr int RENDER_W = 640;
static constexpr int RENDER_H = 480;
static constexpr float GROUND_HALF = 40.f;
static constexpr float FOV_DEG = 70.f;

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
static Vec3 vnorm(Vec3 v) { float l = vlen(v); return v * (1.f / l); }
static float clampf(float v, float lo, float hi) { return std::max(lo, std::min(hi, v)); }

// ─── Lighting / Fog (same as interactive_viewer) ─────────────────────────────
static const Vec3 LIGHT_DIR = vnorm({0.1f, 1.0f, 0.15f});
static constexpr float SHADOW_MULT = 0.60f;
static const Vec3 SKY_COLOR = {0.98f, 0.92f, 0.70f};
static constexpr float FOG_MIN = 35.f;
static constexpr float FOG_MAX = 120.f;

// ─── Meshes ──────────────────────────────────────────────────────────────────
struct Mesh {
  std::vector<float> verts;
  std::vector<uint32_t> tris;
  int nv = 0, nt = 0;
};
struct ObjEntry { Vec3 color; };
static RTCDevice g_device = nullptr;
static RTCScene g_scene = nullptr;
static std::vector<ObjEntry> g_colors;

static Mesh translate_mesh(const Mesh &src, Vec3 off) {
  Mesh m = src;
  for (int i = 0; i < m.nv; i++) {
    m.verts[i*4] += off.x; m.verts[i*4+1] += off.y; m.verts[i*4+2] += off.z;
  }
  return m;
}
static Mesh make_box(float cx, float cy, float cz, float hx, float hy, float hz) {
  Mesh m; m.nv = 8; m.nt = 12;
  float x0=cx-hx,x1=cx+hx,y0=cy-hy,y1=cy+hy,z0=cz-hz,z1=cz+hz;
  float v[] = {x0,y0,z0,0, x1,y0,z0,0, x1,y0,z1,0, x0,y0,z1,0,
               x0,y1,z0,0, x1,y1,z0,0, x1,y1,z1,0, x0,y1,z1,0};
  uint32_t t[] = {3,2,1,3,1,0, 4,5,6,4,6,7, 7,6,2,7,2,3,
                  5,4,0,5,0,1, 4,7,3,4,3,0, 6,5,1,6,1,2};
  m.verts.assign(v, v+32); m.tris.assign(t, t+36); return m;
}
static Mesh make_ground(float hs, float th) {
  Mesh m; m.nv=8; m.nt=12;
  float v[] = {-hs,0,hs,0, hs,0,hs,0, hs,0,-hs,0, -hs,0,-hs,0,
               -hs,-th,hs,0, hs,-th,hs,0, hs,-th,-hs,0, -hs,-th,-hs,0};
  uint32_t t[] = {0,1,2,0,2,3, 4,6,5,4,7,6, 0,4,5,0,5,1,
                  2,6,7,2,7,3, 0,3,7,0,7,4, 1,5,6,1,6,2};
  m.verts.assign(v,v+32); m.tris.assign(t,t+36); return m;
}
static Mesh make_pond(float cx, float cz, float r, int n, float y_val) {
  Mesh m; m.nv=n+1; m.nt=n; m.verts.resize((n+1)*4); m.tris.resize(n*3);
  m.verts[0]=cx; m.verts[1]=y_val; m.verts[2]=cz; m.verts[3]=0;
  for(int i=0;i<n;i++){float a=6.28318f*i/n;float rr=r*(0.85f+0.15f*sinf(a*3.f+cx));
    int vi=(i+1)*4;m.verts[vi]=cx+rr*cosf(a);m.verts[vi+1]=y_val;m.verts[vi+2]=cz+rr*sinf(a);m.verts[vi+3]=0;}
  for(int i=0;i<n;i++){int j=(i+1)%n;m.tris[i*3]=0;m.tris[i*3+1]=i+1;m.tris[i*3+2]=j+1;}
  return m;
}
static Mesh make_reed(float cx, float cz, float h, float lean_x, float lean_z) {
  float w=0.06f; Mesh m=make_box(cx,h*0.5f,cz,w,h*0.5f,w);
  for(int i=0;i<m.nv;i++){float yf=m.verts[i*4+1]/h;m.verts[i*4]+=lean_x*yf;m.verts[i*4+2]+=lean_z*yf;}
  return m;
}
static Mesh make_rock(float cx, float cz, float sx, float sy, float sz) {
  return make_box(cx, sy*0.5f, cz, sx*0.5f, sy*0.5f, sz*0.5f);
}
static Mesh make_deer(float cx, float cz) {
  Mesh body=make_box(cx,1.1f,cz,0.75f,0.3f,0.25f);
  float lx[]={-0.5f,0.5f,-0.5f,0.5f}, lz[]={-0.15f,-0.15f,0.15f,0.15f};
  Mesh result=body;
  for(int i=0;i<4;i++){Mesh leg=make_box(cx+lx[i],0.45f,cz+lz[i],0.06f,0.45f,0.06f);
    int base=result.nv;for(int j=0;j<leg.nv;j++){result.verts.push_back(leg.verts[j*4]);result.verts.push_back(leg.verts[j*4+1]);result.verts.push_back(leg.verts[j*4+2]);result.verts.push_back(0);}
    for(int j=0;j<leg.nt;j++){result.tris.push_back(leg.tris[j*3]+base);result.tris.push_back(leg.tris[j*3+1]+base);result.tris.push_back(leg.tris[j*3+2]+base);}result.nv+=leg.nv;result.nt+=leg.nt;}
  Mesh neck=make_box(cx+0.75f,1.4f,cz,0.06f,0.25f,0.06f);Mesh head=make_box(cx+0.85f,1.65f,cz,0.15f,0.12f,0.12f);
  for(auto*p:{&neck,&head}){int base=result.nv;for(int i=0;i<p->nv;i++){result.verts.push_back(p->verts[i*4]);result.verts.push_back(p->verts[i*4+1]);result.verts.push_back(p->verts[i*4+2]);result.verts.push_back(0);}
    for(int i=0;i<p->nt;i++){result.tris.push_back(p->tris[i*3]+base);result.tris.push_back(p->tris[i*3+1]+base);result.tris.push_back(p->tris[i*3+2]+base);}result.nv+=p->nv;result.nt+=p->nt;}
  return result;
}
static Mesh make_crow(float cx, float cz, float y_off) {
  Mesh body=make_box(cx,0.1f+y_off,cz,0.16f,0.1f,0.1f);
  Mesh head=make_box(cx+0.20f,0.26f+y_off,cz,0.08f,0.08f,0.08f);
  Mesh beak=make_box(cx+0.32f,0.26f+y_off,cz,0.06f,0.03f,0.03f);
  Mesh result=body;
  for(auto*p:{&head,&beak}){int base=result.nv;for(int i=0;i<p->nv;i++){result.verts.push_back(p->verts[i*4]);result.verts.push_back(p->verts[i*4+1]);result.verts.push_back(p->verts[i*4+2]);result.verts.push_back(0);}
    for(int i=0;i<p->nt;i++){result.tris.push_back(p->tris[i*3]+base);result.tris.push_back(p->tris[i*3+1]+base);result.tris.push_back(p->tris[i*3+2]+base);}result.nv+=p->nv;result.nt+=p->nt;}
  return result;
}
static Mesh make_player_static() {
  Mesh torso=make_box(0,0.7f,0,0.18f,0.22f,0.12f);
  Mesh head=make_box(0,1.15f,0,0.12f,0.12f,0.10f);
  Mesh ll=make_box(-0.10f,0.25f,0,0.06f,0.25f,0.06f);
  Mesh rl=make_box(0.10f,0.25f,0,0.06f,0.25f,0.06f);
  Mesh la=make_box(-0.28f,0.65f,0,0.05f,0.20f,0.05f);
  Mesh ra=make_box(0.28f,0.65f,0,0.05f,0.20f,0.05f);
  Mesh result=torso;
  for(auto*p:{&head,&ll,&rl,&la,&ra}){int base=result.nv;for(int i=0;i<p->nv;i++){result.verts.push_back(p->verts[i*4]);result.verts.push_back(p->verts[i*4+1]);result.verts.push_back(p->verts[i*4+2]);result.verts.push_back(0);}
    for(int i=0;i<p->nt;i++){result.tris.push_back(p->tris[i*3]+base);result.tris.push_back(p->tris[i*3+1]+base);result.tris.push_back(p->tris[i*3+2]+base);}result.nv+=p->nv;result.nt+=p->nt;}
  return result;
}

static uint32_t register_mesh(const Mesh &m) {
  RTCGeometry geom = rtcNewGeometry(g_device, RTC_GEOMETRY_TYPE_TRIANGLE);
  auto *vb = (float*)rtcSetNewGeometryBuffer(geom,RTC_BUFFER_TYPE_VERTEX,0,RTC_FORMAT_FLOAT3,16,m.nv);
  memcpy(vb,m.verts.data(),m.nv*16);
  auto *ib = (uint32_t*)rtcSetNewGeometryBuffer(geom,RTC_BUFFER_TYPE_INDEX,0,RTC_FORMAT_UINT3,12,m.nt);
  memcpy(ib,m.tris.data(),m.nt*12);
  rtcCommitGeometry(geom);
  uint32_t gid=rtcAttachGeometry(g_scene,geom);
  rtcReleaseGeometry(geom);
  return gid;
}

// Same placement tables as interactive_viewer
struct TreePlace { float x, z; int type; };
static const TreePlace TREES[] = {
    {-25,-20,0},{-15,-25,1},{-8,-15,2},{-20,5,0},{-12,12,1},
    {-5,20,2},{-18,-8,0},{-25,15,1},{-30,0,2},{-10,-30,0},
    {5,-18,1},{12,-25,2},{20,-10,0},{15,8,1},{8,20,2},
    {25,-5,0},{18,15,1},{30,-15,2},{10,30,0},{22,22,1},
    {4,-2,0},{-3.5f,-4,1},{3,-6,2},{-6,3,0},{6,4,2}};
static constexpr int N_TREES = 25;
struct PondPlace { float x,z,r; int sides; };
static const PondPlace PONDS[] = {{-10,15,3.5f,9},{18,-8,2.8f,7},{-22,-18,4.0f,11},{8,25,3.0f,8}};
static constexpr int N_PONDS = 4;
struct RockPlace { float x,z,sx,sy,sz; };
static const RockPlace ROCKS[] = {
    {5,5,0.8f,0.4f,0.6f},{-14,8,0.5f,0.3f,0.7f},{22,15,1.0f,0.5f,0.8f},
    {-8,-22,0.6f,0.35f,0.5f},{28,-20,0.7f,0.45f,0.6f},{-30,12,0.9f,0.4f,0.7f},
    {12,12,0.4f,0.25f,0.4f},{-5,-10,0.65f,0.3f,0.55f}};
static constexpr int N_ROCKS = 8;
static const float DEER_POS[][2] = {{-15,10},{10,-15},{25,5},{-8,28}};
static constexpr int N_DEER = 4;
static const float CROW_POS[][2] = {{-3,8},{15,3},{-20,-5},{7,-12},{-12,22},{30,18}};
static constexpr int N_CROW = 6;

static void build_scene(Vec3 char_pos) {
  if(g_scene) rtcReleaseScene(g_scene);
  g_scene = rtcNewScene(g_device);
  g_colors.clear();
  // Ground
  register_mesh(make_ground(GROUND_HALF, 0.4f));
  g_colors.push_back({{0.96f,0.85f,0.55f}});
  // Trees
  Vec3 trunk_col={0.55f,0.40f,0.28f};
  Vec3 canopy_cols[3]={{0.45f,0.58f,0.38f},{0.50f,0.60f,0.35f},{0.40f,0.55f,0.42f}};
  for(int i=0;i<N_TREES;i++){
    float tx=TREES[i].x,tz=TREES[i].z,th=4.f+(i%5)*0.5f,cr=2.f+(i%3)*0.5f;
    register_mesh(make_box(tx,th*0.5f,tz,0.25f,th*0.5f,0.25f));g_colors.push_back({trunk_col});
    float cy=th+cr*0.4f;
    register_mesh(make_box(tx,cy,tz,cr,cr*0.5f,cr*0.8f));g_colors.push_back({canopy_cols[TREES[i].type%3]});
    register_mesh(make_box(tx,cy+0.4f,tz,cr*0.8f,cr*0.55f,cr));g_colors.push_back({canopy_cols[TREES[i].type%3]});
    register_mesh(make_box(tx,cy-0.3f,tz,cr*0.6f,cr*0.45f,cr*0.6f));g_colors.push_back({canopy_cols[TREES[i].type%3]});
  }
  // Ponds
  Vec3 pond_col={0.4f,0.75f,0.8f};
  for(int i=0;i<N_PONDS;i++){register_mesh(make_pond(PONDS[i].x,PONDS[i].z,PONDS[i].r,PONDS[i].sides,0.02f));g_colors.push_back({pond_col});}
  // Reeds
  Vec3 reed_col={0.3f,0.55f,0.45f};
  for(int i=0;i<N_PONDS;i++){int nr=10+(i*3)%5;for(int j=0;j<nr;j++){
    float a=6.28318f*j/nr,rr=PONDS[i].r*(1.05f+0.15f*sinf(a*2.f));
    register_mesh(make_reed(PONDS[i].x+rr*cosf(a),PONDS[i].z+rr*sinf(a),0.6f+0.4f*sinf(j*1.7f),0.15f*sinf(j*2.3f),0.15f*cosf(j*1.9f)));
    g_colors.push_back({reed_col});}}
  // Rocks
  Vec3 rock_col={0.75f,0.70f,0.65f};
  for(int i=0;i<N_ROCKS;i++){register_mesh(make_rock(ROCKS[i].x,ROCKS[i].z,ROCKS[i].sx,ROCKS[i].sy,ROCKS[i].sz));g_colors.push_back({rock_col});}
  // Deer
  Vec3 deer_col={0.62f,0.38f,0.25f};
  for(int i=0;i<N_DEER;i++){register_mesh(make_deer(DEER_POS[i][0],DEER_POS[i][1]));g_colors.push_back({deer_col});}
  // Crows
  Vec3 crow_col={0.18f,0.18f,0.20f};
  for(int i=0;i<N_CROW;i++){register_mesh(make_crow(CROW_POS[i][0],CROW_POS[i][1],0));g_colors.push_back({crow_col});}
  // Player
  Mesh player=make_player_static();
  player=translate_mesh(player,char_pos);
  register_mesh(player);
  g_colors.push_back({{0.88f,0.72f,0.58f}});
  rtcCommitScene(g_scene);
}

struct Camera { Vec3 origin, right, up, fwd; float half_tan; };
static Camera make_camera(Vec3 char_pos, float azimuth, float altitude, float radius) {
  Camera c;
  Vec3 offset;
  offset.x = radius * cosf(altitude) * sinf(azimuth);
  offset.y = radius * sinf(altitude);
  offset.z = -radius * cosf(altitude) * cosf(azimuth);
  c.origin = char_pos + offset;
  Vec3 target = {char_pos.x, 1.0f, char_pos.z};
  c.fwd = vnorm(target - c.origin);
  c.right = vnorm(cross3(c.fwd, {0,1,0}));
  c.up = cross3(c.right, c.fwd);
  c.half_tan = tanf(FOV_DEG * 3.14159265f / 360.f);
  return c;
}

static inline uint8_t to_byte(float v) {
  v = clampf(v, 0.f, 1.f);
  return (uint8_t)(v * 255.f + 0.5f);
}

static void render_frame(const Camera &cam, std::vector<uint8_t> &rgb) {
  float aspect = (float)RENDER_W / (float)RENDER_H;
  rgb.resize(RENDER_W * RENDER_H * 3);
  for (int y = 0; y < RENDER_H; y++) {
    for (int x = 0; x < RENDER_W; x++) {
      float px = ((float)x + 0.5f) / RENDER_W * 2.f - 1.f;
      float py = -(((float)y + 0.5f) / RENDER_H * 2.f - 1.f);
      px *= cam.half_tan * aspect;
      py *= cam.half_tan;
      Vec3 rd = vnorm(cam.right * px + cam.up * py + cam.fwd);
      Vec3 ro = cam.origin;
      RTCRayHit rh = {};
      rh.ray.org_x=ro.x; rh.ray.org_y=ro.y; rh.ray.org_z=ro.z;
      rh.ray.dir_x=rd.x; rh.ray.dir_y=rd.y; rh.ray.dir_z=rd.z;
      rh.ray.tnear=1e-3f; rh.ray.tfar=1e9f; rh.ray.mask=0xFFFFFFFF; rh.ray.flags=0;
      rh.hit.geomID=RTC_INVALID_GEOMETRY_ID; rh.hit.instID[0]=RTC_INVALID_GEOMETRY_ID;
      rtcIntersect1(g_scene, &rh);
      Vec3 color;
      if (rh.hit.geomID != RTC_INVALID_GEOMETRY_ID) {
        Vec3 albedo = g_colors[rh.hit.geomID].color;
        Vec3 hp = ro + rd * rh.ray.tfar;
        Vec3 N = vnorm({rh.hit.Ng_x, rh.hit.Ng_y, rh.hit.Ng_z});
        Vec3 so = hp + N * 0.01f;
        RTCRay sr = {};
        sr.org_x=so.x; sr.org_y=so.y; sr.org_z=so.z;
        sr.dir_x=LIGHT_DIR.x; sr.dir_y=LIGHT_DIR.y; sr.dir_z=LIGHT_DIR.z;
        sr.tnear=1e-4f; sr.tfar=1e9f; sr.mask=0xFFFFFFFF; sr.flags=0;
        rtcOccluded1(g_scene, &sr);
        bool in_shadow = (sr.tfar < 0);
        color = in_shadow ? albedo * SHADOW_MULT : albedo;
        float t = rh.ray.tfar;
        float fog = clampf((t - FOG_MIN) / (FOG_MAX - FOG_MIN), 0.f, 1.f);
        color = color * (1.f - fog) + SKY_COLOR * fog;
      } else {
        color = SKY_COLOR;
      }
      int idx = (y * RENDER_W + x) * 3;
      rgb[idx] = to_byte(color.x);
      rgb[idx+1] = to_byte(color.y);
      rgb[idx+2] = to_byte(color.z);
    }
  }
}

static void save_ppm(const std::string &path, const std::vector<uint8_t> &rgb) {
  FILE *f = fopen(path.c_str(), "wb");
  fprintf(f, "P6\n%d %d\n255\n", RENDER_W, RENDER_H);
  fwrite(rgb.data(), 1, rgb.size(), f);
  fclose(f);
}

int main(int argc, char **argv) {
  std::string prefix = "final_project/imgs/p1_viewer";
  if (argc > 1) prefix = argv[1];

  g_device = rtcNewDevice(nullptr);
  if (!g_device) { fprintf(stderr, "Embree init failed\n"); return 1; }

  Vec3 char_pos = {0, 0, 0};
  build_scene(char_pos);

  std::vector<uint8_t> rgb;

  // 3 angles matching interactive_viewer defaults
  struct ViewAngle { const char* name; float azimuth; float altitude; float radius; };
  ViewAngle angles[] = {
    {"front",  0.0f,    0.7f,  7.8f},   // default view
    {"side",   1.2f,    0.6f,  8.5f},   // side view (~69 deg)
    {"close",  0.4f,    0.5f,  5.0f},   // close-up (~23 deg)
  };

  for (auto &a : angles) {
    Camera cam = make_camera(char_pos, a.azimuth, a.altitude, a.radius);
    render_frame(cam, rgb);
    std::string path = prefix + "_" + a.name + ".ppm";
    save_ppm(path, rgb);
    printf("Saved %s\n", path.c_str());
  }

  rtcReleaseScene(g_scene);
  rtcReleaseDevice(g_device);
  printf("Done!\n");
  return 0;
}
