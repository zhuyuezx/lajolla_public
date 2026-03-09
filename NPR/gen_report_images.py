"""
Generate 3 side-by-side NPR comparison images for the checkpoint report.
Run from the NPR/ directory.
"""
import sys, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

POST_PROC = os.path.join(os.getcwd(), 'post_processing')
sys.path.insert(0, POST_PROC)
from image_io import read_image, tone_map

for sub in ['one_bit', 'toon_shading', 'painterly']:
    p = os.path.join(POST_PROC, sub)
    if p not in sys.path:
        sys.path.append(p)

from obra_dinn import obra_dinn_effect
from toon import toon_shading_effect
from painterly import painterly_effect

IMG_DIR = 'images/New-to_UCSD'
OUT_DIR = '../final_project'

def save_compare(original, result, left_title, right_title, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    axes[0].imshow(np.clip(original, 0, 1))
    axes[0].set_title(left_title, fontsize=13, fontweight='bold')
    axes[0].axis('off')
    axes[1].imshow(np.clip(result, 0, 1))
    axes[1].set_title(right_title, fontsize=13, fontweight='bold')
    axes[1].axis('off')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'Saved {out_path}')

# 1. Obra Dinn — Geisel Library
img = read_image(os.path.join(IMG_DIR, 'geisel.jpg'))
result = obra_dinn_effect(img, tone_map_method='clamp', palette='obra_dinn',
                          bayer_size=3, edge_threshold=0.08, contrast=1.2)
save_compare(img, result, 'Original — Geisel Library',
             'Obra Dinn 1-bit dithering', os.path.join(OUT_DIR, 'npr_obra_dinn.png'))

# 2. Toon Shading — Beach View
img = read_image(os.path.join(IMG_DIR, 'beach_view.jpg'))
result = toon_shading_effect(img, tone_map_method='clamp', num_bands=4,
                             edge_threshold=0.06, edge_thickness=1)
save_compare(img, result, 'Original — Beach View',
             'Toon shading (4 bands)', os.path.join(OUT_DIR, 'npr_toon.png'))

# 3. Painterly — Campus Rainbow
img = read_image(os.path.join(IMG_DIR, 'campus_rainbow.jpg'))
result = painterly_effect(img, tone_map_method='clamp', style='oil',
                          kuwahara_radius=4, num_colors=20)
save_compare(img, result, 'Original — Campus Rainbow',
             'Painterly (Kuwahara oil)', os.path.join(OUT_DIR, 'npr_painterly.png'))

print('Done!')
