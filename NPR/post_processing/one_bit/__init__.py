"""
NPR Post-Processing module for lajolla renders.

Effects:
    obra_dinn  — 1-bit ordered dithering à la Return of the Obra Dinn
    (toon, painterly — coming soon)

Quick usage:
    from post_processing.image_io import read_image, write_image, tone_map
    from post_processing.obra_dinn import obra_dinn_effect

    img = read_image('render.exr')
    result = obra_dinn_effect(img, exposure=1.5, palette='obra_dinn')
    write_image('output.png', result)
"""
