#!/usr/bin/env python3
"""Patch cells 14, 15, 16 in npr_demo.ipynb with Litwinowicz comparisons."""
import json

nb_path = 'NPR/npr_demo.ipynb'
with open(nb_path) as f:
    nb = json.load(f)

new_sources = {
    'c9d0712d': [
        "# Litwinowicz '97 stroke-based rendering: vary grid spacing & stroke length\n",
        "img = loaded['Campus Rainbow']\n",
        "\n",
        "results = [\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=3, stroke_length=8,  brush_radius=1),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=12, brush_radius=2),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=6, stroke_length=18, brush_radius=3),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=8, stroke_length=25, brush_radius=4),\n",
        "]\n",
        "titles = ['Fine (3px grid)', 'Medium (4px grid)', 'Coarse (6px grid)', 'Heavy (8px grid)']\n",
        "show_compare(img, results, titles, figsize=(22, 6))",
    ],
    'd41e8a78': [
        "# Litwinowicz: edge clipping ON/OFF and saturation boost comparison\n",
        "img = loaded['Geisel Library']\n",
        "\n",
        "results = [\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=12, brush_radius=2,\n",
        "                     edge_clip=True, saturation_boost=0.0),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=12, brush_radius=2,\n",
        "                     edge_clip=False, saturation_boost=0.0),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=12, brush_radius=2,\n",
        "                     edge_clip=True, saturation_boost=0.3),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=12, brush_radius=2,\n",
        "                     edge_clip=True, saturation_boost=0.6),\n",
        "]\n",
        "titles = ['Edge clip ON', 'Edge clip OFF', 'Sat boost +0.3', 'Sat boost +0.6']\n",
        "show_compare(img, results, titles, figsize=(22, 6))",
    ],
    'e8c4018b': [
        "# Litwinowicz: stroke length and jitter variation on Beach View\n",
        "img = loaded['Beach View']\n",
        "\n",
        "results = [\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=10, brush_radius=2, jitter=0.8),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=20, brush_radius=2, jitter=0.8),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=10, brush_radius=2, jitter=0.2),\n",
        "    painterly_effect(img, tone_map_method='clamp', style='litwinowicz',\n",
        "                     grid_spacing=4, stroke_length=20, brush_radius=3, jitter=0.2,\n",
        "                     saturation_boost=0.4),\n",
        "]\n",
        "titles = ['Default', 'Long strokes', 'Low jitter', 'Long + low jitter + vivid']\n",
        "show_compare(img, results, titles, figsize=(22, 6))",
    ],
}

changed = 0
for cell in nb['cells']:
    cid = cell.get('id', '')
    if cid in new_sources:
        cell['source'] = new_sources[cid]
        cell['outputs'] = []
        cell['execution_count'] = None
        changed += 1

print(f"Patched {changed} cells")

with open(nb_path, 'w') as f:
    json.dump(nb, f, indent=1)
    f.write('\n')

print("Saved.")
