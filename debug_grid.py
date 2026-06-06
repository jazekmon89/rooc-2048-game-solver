"""Debug tool: capture the board and draw the cell grid overlay.

Saves an image showing exactly where each cell is being sampled from.
If the grid lines don't align with the actual tiles, the region needs adjusting.

Usage: python debug_grid.py
"""

import json
from PIL import Image, ImageDraw, ImageFont
from vision import capture, split_into_cells, cell_signature, load_references, color_distance
from config import GRID_SIZE, REGION_FILE, CELL_INSET_RATIO, COLOR_MATCH_TOLERANCE


def load_region():
    with open(REGION_FILE) as f:
        return json.load(f)


def main():
    region = load_region()
    references = load_references()

    print(f'Region: {region}')
    print(f'References: {sorted(references.keys())}')

    # Capture the board
    img = capture(region)
    print(f'Captured image: {img.size[0]}x{img.size[1]}')

    # Save raw capture
    img.save('debug_raw.png')
    print('Saved: debug_raw.png (raw screenshot)')

    # Draw grid overlay
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)

    w, h = img.size
    cw, ch = w / GRID_SIZE, h / GRID_SIZE
    inset = min(cw, ch) * CELL_INSET_RATIO

    # Draw full grid lines (where cells are divided)
    for i in range(GRID_SIZE + 1):
        x = int(i * cw)
        y = int(i * ch)
        draw.line([(x, 0), (x, h)], fill='lime', width=2)
        draw.line([(0, y), (w, y)], fill='lime', width=2)

    # Draw inset rectangles (the actual sampled area per cell)
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            left = int(c * cw + inset)
            top = int(r * ch + inset)
            right = int((c + 1) * cw - inset)
            bottom = int((r + 1) * ch - inset)
            draw.rectangle([left, top, right, bottom], outline='red', width=2)

            # Show the detected color and value
            cell_img = img.crop((left, top, right, bottom))
            sig = cell_signature(cell_img)

            # Classify
            best_val, best_dist = '?', float('inf')
            for val, ref in references.items():
                d = color_distance(sig, ref)
                if d < best_dist:
                    best_dist = d
                    best_val = val

            if best_dist > COLOR_MATCH_TOLERANCE:
                label = '??'
                color = 'yellow'
            elif best_val == 0:
                label = '.'
                color = 'white'
            else:
                label = str(best_val)
                color = 'cyan'

            # Draw label
            text_x = int(c * cw + cw / 2)
            text_y = int(r * ch + 8)
            draw.text((text_x, text_y), label, fill=color)

            # Draw RGB value
            rgb_text = f'{sig[0]},{sig[1]},{sig[2]}'
            draw.text((left + 4, bottom - 14), rgb_text, fill='white')

    overlay.save('debug_grid.png')
    print('Saved: debug_grid.png (with grid overlay)')
    print()
    print('Open debug_grid.png and check:')
    print('  - GREEN lines = cell boundaries')
    print('  - RED rectangles = sampled area (after inset)')
    print('  - If red rectangles are NOT centered on the tiles,')
    print('    re-pick the region more tightly around the tiles.')


if __name__ == '__main__':
    main()
