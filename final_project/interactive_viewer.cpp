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
static constexpr float FOV_DEG = 70.f;  // perspective field of view

// ─── Vec3 math ───────────────────────────────────────────────────────────────
struct Vec3 {
    float x, y, z;
    Vec3 operator+(Vec3 b) const { return {x+b.x, y+b.y, z+b.z}; }
    Vec3 operator-(Vec3 b) const { return {x-b.x, y-b.y, z-b.z}; }
    Vec3 operator*(float s) const { return {x*s, y*s, z*s}; }
    Vec3 operator*(Vec3 b) const { return {x*b.x, y*b.y, z*b.z}; }
    Vec3 operator-() const { return {-x, -y, -z}; }
};
static float  dot3(Vec3 a, Vec3 b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
static Vec3 cross3(Vec3 a, Vec3 b) {
    return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x};
}
static float  vlen(Vec3 v) { return sqrtf(dot3(v,v)); }
static Vec3  vnorm(Vec3 v) { float l=vlen(v); return v*(1.f/l); }
static float clampf(float v, float lo, float hi) { return std::max(lo, std::min(hi, v)); }

// ─── Unlit + Fog settings (Deer Hunter II / Sokpop style) ────────────────────
static const Vec3 LIGHT_DIR    = vnorm({0.6f, 0.8f, -0.5f}); // for shadow rays
static constexpr float SHADOW_MULT = 0.65f;   // darken factor when in shadow
static const Vec3 SKY_COLOR    = {0.95f, 0.88f, 0.75f};  // pale warm peach sky
static constexpr float FOG_MIN = 15.f;   // fog starts at this distance
static constexpr float FOG_MAX = 70.f;   // fully fogged at this distance

// ─── Simple mesh ─────────────────────────────────────────────────────────────
struct Mesh {
    std::vector<float>    verts; // x,y,z,pad per vertex (stride 4 floats)
    std::vector<uint32_t> tris;  // 3 indices per tri
    int nv=0, nt=0;
};

static Mesh load_obj(const std::string& path) {
    Mesh m;
    std::vector<Vec3> pos;
    std::vector<std::array<int,3>> faces;
    std::ifstream f(path);
    if (!f.is_open()) { fprintf(stderr,"Cannot open %s\n",path.c_str()); return m; }
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty()||line[0]=='#') continue;
        std::istringstream ss(line);
        std::string tok; ss >> tok;
        if (tok=="v") {
            float x,y,z; ss>>x>>y>>z;
            pos.push_back({x,y,z});
        } else if (tok=="f") {
            std::vector<int> vi; std::string s;
            while (ss>>s) vi.push_back(std::atoi(s.c_str())-1);
            for (int i=1;i+1<(int)vi.size();i++)
                faces.push_back({vi[0],vi[i],vi[i+1]});
        }
    }
    m.nv=(int)pos.size(); m.nt=(int)faces.size();
    m.verts.resize(m.nv*4);
    for (int i=0;i<m.nv;i++){
        m.verts[i*4]=pos[i].x; m.verts[i*4+1]=pos[i].y;
        m.verts[i*4+2]=pos[i].z; m.verts[i*4+3]=0.f;
    }
    m.tris.resize(m.nt*3);
    for (int i=0;i<m.nt;i++){
        m.tris[i*3]=faces[i][0]; m.tris[i*3+1]=faces[i][1]; m.tris[i*3+2]=faces[i][2];
    }
    return m;
}

static Mesh translate_mesh(const Mesh& src, Vec3 off) {
    Mesh m=src;
    for (int i=0;i<m.nv;i++){
        m.verts[i*4]+=off.x; m.verts[i*4+1]+=off.y; m.verts[i*4+2]+=off.z;
    }
    return m;
}

static Mesh make_ground(float hs, float th) {
    Mesh m; m.nv=8; m.nt=12;
    float v[]={
        -hs,0,hs,0, hs,0,hs,0, hs,0,-hs,0, -hs,0,-hs,0,
        -hs,-th,hs,0, hs,-th,hs,0, hs,-th,-hs,0, -hs,-th,-hs,0
    };
    uint32_t t[]={
        0,1,2,0,2,3, 4,6,5,4,7,6, 0,4,5,0,5,1,
        2,6,7,2,7,3, 0,3,7,0,7,4, 1,5,6,1,6,2
    };
    m.verts.assign(v,v+32); m.tris.assign(t,t+36);
    return m;
}

// ─── Embree scene ────────────────────────────────────────────────────────────
struct ObjEntry { Vec3 color; };
static RTCDevice g_device = nullptr;
static RTCScene  g_scene  = nullptr;
static std::vector<ObjEntry> g_colors; // indexed by geomID

static uint32_t register_mesh(const Mesh& m) {
    RTCGeometry geom = rtcNewGeometry(g_device, RTC_GEOMETRY_TYPE_TRIANGLE);
    auto* vb = (float*)rtcSetNewGeometryBuffer(
        geom, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3, 16, m.nv);
    memcpy(vb, m.verts.data(), m.nv*16);
    auto* ib = (uint32_t*)rtcSetNewGeometryBuffer(
        geom, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, 12, m.nt);
    memcpy(ib, m.tris.data(), m.nt*12);
    rtcCommitGeometry(geom);
    uint32_t gid = rtcAttachGeometry(g_scene, geom);
    rtcReleaseGeometry(geom);
    return gid;
}

// Tree placement table
struct TreePlace { float x,z; int type; };
static const TreePlace TREES[] = {
    {-25,-20,0},{-15,-25,1},{-8,-15,2},{-20,5,0},{-12,12,1},
    {-5,20,2},{-18,-8,0},{-25,15,1},{-30,0,2},{-10,-30,0},
    {5,-18,1},{12,-25,2},{20,-10,0},{15,8,1},{8,20,2},
    {25,-5,0},{18,15,1},{30,-15,2},{10,30,0},{22,22,1},
    {4,-2,0},{-3.5f,-4,1},{3,-6,2},{-6,3,0},{6,4,2}
};
static constexpr int N_TREES = sizeof(TREES)/sizeof(TREES[0]);

static Mesh g_tree_templates[3];
static Mesh g_char_template;

static void build_scene(Vec3 char_pos) {
    if (g_scene) rtcReleaseScene(g_scene);
    g_scene = rtcNewScene(g_device);
    rtcSetSceneBuildQuality(g_scene, RTC_BUILD_QUALITY_LOW);
    rtcSetSceneFlags(g_scene, RTC_SCENE_FLAG_DYNAMIC);
    g_colors.clear();

    // Ground
    Mesh ground = make_ground(GROUND_HALF, 0.4f);
    register_mesh(ground);
    g_colors.push_back({{0.76f, 0.68f, 0.48f}});

    // Trees
    Vec3 tcols[3] = {{0.30f,0.62f,0.32f},{0.48f,0.65f,0.28f},{0.25f,0.58f,0.52f}};
    for (int i = 0; i < N_TREES; i++) {
        Mesh tm = translate_mesh(g_tree_templates[TREES[i].type],
                                 {TREES[i].x, 0, TREES[i].z});
        register_mesh(tm);
        g_colors.push_back({tcols[TREES[i].type]});
    }

    // Character
    Mesh cm = translate_mesh(g_char_template, char_pos);
    register_mesh(cm);
    g_colors.push_back({{0.88f, 0.72f, 0.58f}});

    rtcCommitScene(g_scene);
}

// ─── Camera (Perspective / Pinhole) ──────────────────────────────────────────
struct Camera { Vec3 origin, right, up, fwd; float half_tan; };

static Camera make_camera(Vec3 char_pos) {
    Camera c;
    // Third-person offset: behind and slightly above the character
    Vec3 target = {char_pos.x, 1.4f, char_pos.z};
    c.origin = target + Vec3{-5.f, 4.f, -5.f};
    c.fwd   = vnorm(target - c.origin);
    c.right = vnorm(cross3(c.fwd, {0,1,0}));
    c.up    = cross3(c.right, c.fwd);
    c.half_tan = tanf(FOV_DEG * 3.14159265f / 360.f); // tan(fov/2)
    return c;
}

// ─── Unlit Render with Distance Fog ──────────────────────────────────────────
static inline uint8_t to_byte(float v) {
    v = clampf(v, 0.f, 1.f);
    // No gamma — raw unlit values straight to framebuffer (matches Sokpop look)
    return (uint8_t)(v*255.f+0.5f);
}

static void render_frame(const Camera& cam, uint32_t* fb) {
    float aspect = (float)RENDER_W / (float)RENDER_H;
    for (int y = 0; y < RENDER_H; y++) {
        for (int x = 0; x < RENDER_W; x++) {
            // ── Task 1: Perspective (pinhole) ray — no AA, no jitter ──
            // Pixel center only — integer + 0.5, no sub-pixel sampling
            float px = ((float)x + 0.5f) / RENDER_W * 2.f - 1.f;
            float py = -(((float)y + 0.5f) / RENDER_H * 2.f - 1.f);
            px *= cam.half_tan * aspect;  // scale by FOV and aspect
            py *= cam.half_tan;
            // Ray direction in world space (all rays originate from camera)
            Vec3 rd = vnorm(cam.right*px + cam.up*py + cam.fwd);
            Vec3 ro = cam.origin;

            RTCRayHit rh;
            rh.ray.org_x=ro.x; rh.ray.org_y=ro.y; rh.ray.org_z=ro.z;
            rh.ray.dir_x=rd.x; rh.ray.dir_y=rd.y; rh.ray.dir_z=rd.z;
            rh.ray.tnear=1e-3f; rh.ray.tfar=1e9f;
            rh.ray.mask=0xFFFFFFFF; rh.ray.flags=0;
            rh.hit.geomID=RTC_INVALID_GEOMETRY_ID;
            rh.hit.instID[0]=RTC_INVALID_GEOMETRY_ID;

            rtcIntersect1(g_scene, &rh);

            Vec3 color;
            if (rh.hit.geomID != RTC_INVALID_GEOMETRY_ID) {
                // ── Task 3: Unlit shading — pure albedo + shadow ──
                Vec3 N = vnorm({rh.hit.Ng_x, rh.hit.Ng_y, rh.hit.Ng_z});
                if (dot3(N, rd*-1.f) < 0) N = -N;
                Vec3 albedo = g_colors[rh.hit.geomID].color;

                // Cast shadow ray toward light — only purpose is ground shadows
                Vec3 hp = ro + rd * rh.ray.tfar;
                Vec3 so = hp + N * 2e-3f;
                RTCRay sr;
                sr.org_x=so.x; sr.org_y=so.y; sr.org_z=so.z;
                sr.dir_x=LIGHT_DIR.x; sr.dir_y=LIGHT_DIR.y; sr.dir_z=LIGHT_DIR.z;
                sr.tnear=0; sr.tfar=1e9f; sr.mask=0xFFFFFFFF; sr.flags=0;
                rtcOccluded1(g_scene, &sr);
                bool in_shadow = (sr.tfar < 0);

                color = in_shadow ? albedo * SHADOW_MULT : albedo;

                // ── Task 4: Linear distance fog ──
                float t = rh.ray.tfar;
                float fog = clampf((t - FOG_MIN) / (FOG_MAX - FOG_MIN), 0.f, 1.f);
                color = color*(1.f - fog) + SKY_COLOR*fog;
            } else {
                // Ray missed — pure sky
                color = SKY_COLOR;
            }
            fb[y*RENDER_W+x] = (255u<<24)|(to_byte(color.x)<<16)
                               |(to_byte(color.y)<<8)|to_byte(color.z);
        }
    }
}

// ─── Main ────────────────────────────────────────────────────────────────────
int main(int argc, char** argv) {
    std::string mesh_dir = "scenes/skypop_game/meshes";
    if (argc > 1) mesh_dir = argv[1];

    // Load mesh templates
    g_tree_templates[0] = load_obj(mesh_dir + "/tree_a.obj");
    g_tree_templates[1] = load_obj(mesh_dir + "/tree_b.obj");
    g_tree_templates[2] = load_obj(mesh_dir + "/tree_c.obj");
    g_char_template     = load_obj(mesh_dir + "/character.obj");
    printf("Loaded meshes from %s\n", mesh_dir.c_str());

    // Init Embree
    g_device = rtcNewDevice(nullptr);
    if (!g_device) { fprintf(stderr,"Embree init failed\n"); return 1; }

    // Init SDL2
    if (SDL_Init(SDL_INIT_VIDEO) < 0) {
        fprintf(stderr,"SDL init failed: %s\n",SDL_GetError()); return 1;
    }
    SDL_Window* win = SDL_CreateWindow(
        "Unlit Fog Viewer — Arrow keys / ESC",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, WINDOW_W, WINDOW_H, 0);
    // SDL_RENDERER_ACCELERATED with nearest-neighbor scaling for crisp pixels
    SDL_Renderer* ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0"); // nearest-neighbor (no AA)
    SDL_Texture* tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
        SDL_TEXTUREACCESS_STREAMING, RENDER_W, RENDER_H);

    std::vector<uint32_t> fb(RENDER_W * RENDER_H);
    Vec3 char_pos = {0, 0, 0};

    // Movement directions: camera-relative, projected to ground (XZ)
    Camera cam0 = make_camera({0,0,0});
    Vec3 move_fwd   = vnorm({cam0.fwd.x,   0, cam0.fwd.z});   // forward on ground
    Vec3 move_right = vnorm({cam0.right.x, 0, cam0.right.z});

    // Initial build + render
    build_scene(char_pos);
    Camera cam = make_camera(char_pos);
    render_frame(cam, fb.data());
    bool needs_render = false;

    bool running = true;
    Uint32 last_tick = SDL_GetTicks();

    while (running) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_QUIT) running = false;
            if (ev.type == SDL_KEYDOWN && ev.key.keysym.sym == SDLK_ESCAPE)
                running = false;
        }

        // Continuous movement from held keys
        const Uint8* keys = SDL_GetKeyboardState(nullptr);
        Vec3 old_pos = char_pos;
        if (keys[SDL_SCANCODE_RIGHT]) { char_pos = char_pos + move_right * MOVE_SPEED; }
        if (keys[SDL_SCANCODE_LEFT])  { char_pos = char_pos - move_right * MOVE_SPEED; }
        if (keys[SDL_SCANCODE_UP])    { char_pos = char_pos + move_fwd   * MOVE_SPEED; }
        if (keys[SDL_SCANCODE_DOWN])  { char_pos = char_pos - move_fwd   * MOVE_SPEED; }

        // Clamp to ground bounds
        float lim = GROUND_HALF - 2.f;
        char_pos.x = std::max(-lim, std::min(lim, char_pos.x));
        char_pos.z = std::max(-lim, std::min(lim, char_pos.z));

        if (char_pos.x != old_pos.x || char_pos.z != old_pos.z)
            needs_render = true;

        if (needs_render) {
            build_scene(char_pos);
            cam = make_camera(char_pos);
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
                "Unlit Fog — pos(%.1f, %.1f) — %.0f FPS — Arrow keys / ESC",
                char_pos.x, char_pos.z, fps);
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
