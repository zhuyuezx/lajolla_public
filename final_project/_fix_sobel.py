"""One-shot script: replace run_sobel_pass in sobel_post.py with the updated version."""
import sys, os

TARGET = os.path.join(os.path.dirname(__file__), "sobel_post.py")

NEW_FUNC = '''\
def run_sobel_pass(color_path: str,
                   depth_thresh: float  = 0.10,
                   normal_thresh: float = 0.50,
                   id_thresh: float     = 1e-3,
                   outline_color        = (0.0, 0.0, 0.0),
                   outline_width: int   = 1,
                   output_path: str | None = None,
                   debug_aov: str       = \'none\'):

    stem, ext = os.path.splitext(color_path)
    color    = read_exr(color_path)
    depth    = read_exr(stem + \'_depth\'    + ext)
    normal   = read_exr(stem + \'_normal\'   + ext)
    objectid = read_exr(stem + \'_objectid\' + ext)
    h, w = color.shape[:2]

    # --- DEBUG AOV visualisation ---
    if debug_aov != \'none\':
        if debug_aov == \'depth\':
            d = depth[:, :, 0]
            d_vis = np.where(d >= 0, d, 0.0)
            d_vis = (d_vis / (np.max(d_vis) + 1e-10)).astype(np.float32)
            result = np.stack([d_vis, d_vis, d_vis], axis=-1)
            tag = \'_debug_depth\'
        elif debug_aov == \'normal\':
            result = ((normal + 1.0) * 0.5).clip(0, 1).astype(np.float32)
            tag = \'_debug_normal\'
        elif debug_aov == \'objectid\':
            ids = objectid[:, :, 0]
            unique_ids = sorted(set(ids.ravel().tolist()))
            n = max(len(unique_ids), 1)
            result = np.zeros((h, w, 3), dtype=np.float32)
            for i, uid in enumerate(unique_ids):
                r, g, b = colorsys.hsv_to_rgb(
                    i / n,
                    0.0 if uid < 0 else 0.75,
                    0.15 if uid < 0 else 0.95)
                result[ids == uid] = [r, g, b]
            tag = \'_debug_objectid\'
        else:
            tag = \'_debug_unknown\'
            result = color.copy()
        out = output_path or (stem + tag + ext)
        write_exr(out, result)
        print(f\'[sobel_post] Debug AOV ({debug_aov}) written -> {out}\')
        return result

    # valid-pixel mask (depth >= 0 means the ray hit geometry)
    valid  = (depth[:, :, 0] >= 0)
    fvalid = valid.astype(np.float32)

    # --- Depth edges (normalised to [0,1] so threshold is scale-invariant) ---
    depth_masked = depth[:, :, 0] * fvalid
    depth_norm   = depth_masked / (np.max(depth_masked) + 1e-10)
    edge_depth   = (_sobel(depth_norm) > depth_thresh)

    # --- Normal edges (Euclidean magnitude across 3 channels) ---
    normal_valid = normal * valid[:, :, np.newaxis].astype(np.float32)
    norm_mag = np.sqrt(sum(_sobel(normal_valid[:, :, c]) ** 2 for c in range(3)))
    edge_norm = (norm_mag > normal_thresh) & valid

    # --- Object-ID edges (tiny threshold catches any integer boundary) ---
    id_valid  = objectid[:, :, 0] * fvalid
    edge_id   = (_sobel(id_valid) > id_thresh) & valid

    print(f\'[sobel_post]  depth  edges: {int(edge_depth.sum()):>7}  ({100*edge_depth.mean():.2f}%)\')
    print(f\'[sobel_post]  normal edges: {int(edge_norm.sum()):>7}  ({100*edge_norm.mean():.2f}%)\')
    print(f\'[sobel_post]  id     edges: {int(edge_id.sum()):>7}  ({100*edge_id.mean():.2f}%)\')

    combined = edge_depth | edge_norm | edge_id
    if outline_width > 1:
        combined = edge_mask(
            np.stack([combined.astype(np.float32)] * 3, axis=-1),
            0.5, dilate=outline_width - 1)

    print(f\'[sobel_post]  total  edges: {int(combined.sum()):>7}  ({100*combined.mean():.2f}%)\')

    result = color.copy()
    result[combined] = np.array(outline_color, dtype=np.float32)

    if output_path is None:
        output_path = stem + \'_outlined\' + ext
    write_exr(output_path, result)
    print(f\'[sobel_post] Wrote outlined image -> {output_path}\')
    return result

'''

with open(TARGET, encoding='utf-8') as f:
    src = f.read()

# Find the old function start
START_MARKER = 'def run_sobel_pass('
CLI_MARKER   = '\n# ---------------------------------------------------------------------------\n# CLI'

start_idx = src.index(START_MARKER)
end_idx   = src.index(CLI_MARKER, start_idx)

new_src = src[:start_idx] + NEW_FUNC + src[end_idx:]

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(new_src)

print(f"Replaced run_sobel_pass in {TARGET}")
print(f"  old function was {end_idx - start_idx} chars, new is {len(NEW_FUNC)} chars")
