# NPR Pipeline — Command Reference

All commands are run from the **workspace root** (`lajolla_public/`) unless noted.

---

## Build

```bash
# Configure (first time only)
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Build renderer
cmake --build build --parallel
```

---

## Render a single frame

```bash
# Produces: image.exr  image_depth.exr  image_normal.exr  image_objectid.exr
build/lajolla scenes/npr_cbox/scene.xml
```

Override the output filename with `-o`:

```bash
build/lajolla -o my_output.exr scenes/npr_cbox/scene.xml
```

---

## Sobel edge-detection post-process

```bash
# Apply outlines to the latest render (default thresholds)
python3 final_project/sobel_post.py image.exr
# → image_outlined.exr

# Custom thresholds
python3 final_project/sobel_post.py image.exr \
    --depth_thresh 0.05 --normal_thresh 0.40

# Debug AOV views (depth | normal | objectid)
python3 final_project/sobel_post.py image.exr --debug-aov depth
python3 final_project/sobel_post.py image.exr --debug-aov normal
python3 final_project/sobel_post.py image.exr --debug-aov objectid
```

---

## Orbit animation (camera demo)

```bash
# Full 360° orbit — 36 frames, 12 fps  →  animation.gif
python3 final_project/animate_npr.py

# Options
python3 final_project/animate_npr.py \
    --scene       scenes/npr_cbox/scene.xml \
    --frames      60       \   # frame count
    --orbit       360      \   # arc in degrees
    --fps         15       \   # GIF playback speed
    --output      animation.gif \
    --frames-dir  /tmp/npr_frames \
    --depth-thresh  0.10   \
    --normal-thresh 0.50   \
    --gamma       2.2

# Skip outline pass (raw colour only)
python3 final_project/animate_npr.py --no-outline
```

---

## Convert EXR outputs to PNG (for reports / figures)

```bash
python3 final_project/_convert_pngs.py
# Writes into final_project/:
#   render_color.png
#   render_outlined.png
#   render_depth.png
#   render_normal.png
#   render_objectid.png
```

---

## Diagnostics

```bash
# Check normal stability per object ID
python3 final_project/_diag_normals.py

# Check per-shape colour values in latest render
python3 final_project/_diag_color.py

# Inspect AOV neighbour differences (edge detection debug)
python3 final_project/_diag_aov.py
```

---

## Run tests

```bash
cd build && ctest --output-on-failure
```
