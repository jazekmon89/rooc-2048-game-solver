"""Vision pipeline: screenshot region, split into 4x4, classify each tile.

Classification uses a color-signature approach:
- For each tile cell, compute the median color of mid-brightness pixels
  (filters out white text and dark shadows).
- Match the signature to the closest known reference color from calibration.
- If no reference is within COLOR_MATCH_TOLERANCE, treat the cell as empty.

You calibrate ONCE per game (or whenever new tile values appear) by entering
the current board state. The system stores {value: rgb} pairs to disk.
"""

import json
import mss
import numpy as np
from PIL import Image

from config import (
    GRID_SIZE, TILE_REFERENCES_FILE, COLOR_MATCH_TOLERANCE, CELL_INSET_RATIO,
    STABLE_CHECK_INTERVAL, STABLE_CHECK_MAX_WAIT,
)


# ---------- capture ----------

def capture(region):
    """Take a screenshot of the given region dict. Returns a PIL Image (RGB)."""
    with mss.mss() as sct:
        mon = {
            'left': int(region['x']),
            'top': int(region['y']),
            'width': int(region['width']),
            'height': int(region['height']),
        }
        raw = sct.grab(mon)
        return Image.frombytes('RGB', raw.size, raw.rgb)


# ---------- split into cells ----------

def split_into_cells(img, grid=GRID_SIZE):
    """Divide image into grid x grid PIL Images. Returns a 2D list."""
    w, h = img.size
    cw, ch = w / grid, h / grid
    inset = min(cw, ch) * CELL_INSET_RATIO
    cells = []
    for r in range(grid):
        row = []
        for c in range(grid):
            left = int(c * cw + inset)
            top = int(r * ch + inset)
            right = int((c + 1) * cw - inset)
            bottom = int((r + 1) * ch - inset)
            row.append(img.crop((left, top, right, bottom)))
        cells.append(row)
    return cells


# ---------- color signature ----------

def cell_signature(cell_img):
    """Median color of mid-brightness pixels (drops text and shadow)."""
    arr = np.array(cell_img)
    brightness = arr.mean(axis=2)
    mask = (brightness < 235) & (brightness > 35)
    if mask.sum() < 10:
        return tuple(int(v) for v in arr.reshape(-1, 3).mean(axis=0))
    pixels = arr[mask]
    median = np.median(pixels, axis=0)
    return tuple(int(v) for v in median)


def color_distance(c1, c2):
    return (sum((a - b) ** 2 for a, b in zip(c1, c2))) ** 0.5


def _chromaticity(c):
    """Normalize RGB to ratios (brightness-invariant). Returns scaled tuple."""
    s = c[0] + c[1] + c[2]
    if s < 30:
        return (0.0, 0.0, 0.0)
    return (c[0] * 255.0 / s, c[1] * 255.0 / s, c[2] * 255.0 / s)


# ---------- reference store ----------

def load_references():
    """Load {value: (r, g, b)} dict, or empty dict if no file yet."""
    try:
        with open(TILE_REFERENCES_FILE) as f:
            data = json.load(f)
        refs = {int(k): tuple(v) for k, v in data.items()}
        update_tolerance(refs)
        return refs
    except FileNotFoundError:
        return {}


def save_references(refs):
    serializable = {str(k): list(v) for k, v in refs.items()}
    with open(TILE_REFERENCES_FILE, 'w') as f:
        json.dump(serializable, f, indent=2)


# ---------- classification ----------

# Cached effective tolerance — recomputed when references change.
_effective_tolerance = COLOR_MATCH_TOLERANCE


def update_tolerance(references):
    """Recompute the effective tolerance based on how close references are.

    If two tile colors are only 11 units apart (e.g., tile 4 and 8),
    a tolerance of 45 would let tile 16 (22 away from 8) match as 8.
    We set the tolerance to half the minimum inter-reference distance,
    so each tile can only match its own reference.
    """
    global _effective_tolerance
    if len(references) < 2:
        _effective_tolerance = COLOR_MATCH_TOLERANCE
        return _effective_tolerance

    min_dist = float('inf')
    sigs = list(references.values())
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            d = color_distance(sigs[i], sigs[j])
            if 0 < d < min_dist:
                min_dist = d

    if min_dist == float('inf'):
        _effective_tolerance = COLOR_MATCH_TOLERANCE
    else:
        # Half the minimum distance, floored at 8 (noise margin), capped at config
        _effective_tolerance = min(COLOR_MATCH_TOLERANCE, max(8, min_dist / 2))

    return _effective_tolerance


def classify_cell(cell_img, references):
    """Return (tile_value, is_unknown).

    tile_value is the best-matching value or 0 if empty/unrecognized.
    is_unknown is True when the cell has a strong color signature (not empty)
    but doesn't match any known reference.

    Uses a two-pass approach:
    1. Raw RGB distance (works in normal brightness)
    2. Chromaticity (ratio-based) fallback (handles screen dimming)
    """
    sig = cell_signature(cell_img)
    if not references:
        return 0, True

    # Pass 1: raw RGB matching
    best_val, best_dist = 0, float('inf')
    for val, ref in references.items():
        d = color_distance(sig, ref)
        if d < best_dist:
            best_dist = d
            best_val = val

    if best_dist <= _effective_tolerance:
        return best_val, False

    # Pass 2: chromaticity fallback (brightness-invariant)
    # Handles dimmed screens where RGB values shift uniformly
    sig_chr = _chromaticity(sig)
    if sig_chr != (0.0, 0.0, 0.0):
        best_val_chr, best_dist_chr = 0, float('inf')
        for val, ref in references.items():
            ref_chr = _chromaticity(ref)
            d = color_distance(sig_chr, ref_chr)
            if d < best_dist_chr:
                best_dist_chr = d
                best_val_chr = val
        # Tighter tolerance for chromaticity (ratios are more sensitive)
        if best_dist_chr <= 15:
            return best_val_chr, False

    return 0, True  # no match → unknown


def parse_board(region, references):
    """Capture → split → classify.

    Returns (board, unknowns) where:
    - board is GRID_SIZE x GRID_SIZE list of ints
    - unknowns is a list of (row, col, signature) for unrecognized cells
    """
    img = capture(region)
    cells = split_into_cells(img)
    board = []
    unknowns = []
    for r, row in enumerate(cells):
        board_row = []
        for c, cell_img in enumerate(row):
            val, is_unknown = classify_cell(cell_img, references)
            board_row.append(val)
            if is_unknown:
                sig = cell_signature(cell_img)
                unknowns.append((r, c, sig))
        board.append(board_row)
    return board, unknowns


def parse_next_tile(region, references):
    """Capture the next-tile indicator region and classify it.

    This is a single tile, not a 4x4 grid. We apply the same inset ratio
    to avoid border artifacts, then classify against known references.

    Returns the tile value (int), or None if the feature is disabled,
    the classification fails, or the cell looks empty.
    """
    if region is None:
        return None

    img = capture(region)
    w, h = img.size
    inset = min(w, h) * CELL_INSET_RATIO
    cropped = img.crop((int(inset), int(inset), int(w - inset), int(h - inset)))

    val, is_unknown = classify_cell(cropped, references)
    if is_unknown or val == 0:
        return None
    return val


def wait_for_stable_board(region, references):
    """Capture repeatedly until the board stops changing (animation done).

    Returns (board, unknowns) from the final stable capture.
    """
    import time
    elapsed = 0.0
    prev_board, prev_unknowns = parse_board(region, references)
    while elapsed < STABLE_CHECK_MAX_WAIT:
        time.sleep(STABLE_CHECK_INTERVAL)
        elapsed += STABLE_CHECK_INTERVAL
        curr_board, curr_unknowns = parse_board(region, references)
        if curr_board == prev_board:
            return curr_board, curr_unknowns
        prev_board, prev_unknowns = curr_board, curr_unknowns
    return prev_board, prev_unknowns


# ---------- calibration ----------

def calibrate_interactive(region):
    """Capture current board, ask user to type the values, record colors."""
    print('\n=== Calibration ===')
    input('Make sure the board is stable (no animations), then press Enter to capture...')

    img = capture(region)

    # Save the capture so the user reads tile values from THIS image,
    # not the live game (which may change). This prevents sync issues.
    snapshot_path = 'calibration_snapshot.png'
    img.save(snapshot_path)
    print(f'\nSnapshot saved to: {snapshot_path}')
    print(f'*** IMPORTANT: Open {snapshot_path} and read the values from THAT image, ***')
    print(f'*** NOT from the live game! This ensures your input matches the capture. ***\n')
    print(f'Type the {GRID_SIZE} values in each row.')
    print('Use 0 for empty cells, space-separated. Example: "2 0 0 4"\n')

    cells = split_into_cells(img)
    # Merge with existing references so previously learned tiles survive
    # across new games. Tiles visible now get fresh readings; tiles not
    # on the current board keep their old references.
    references = load_references()
    prev_count = len(references)

    for r in range(GRID_SIZE):
        while True:
            raw = input(f'Row {r + 1}: ').strip()
            try:
                values = [int(v) for v in raw.split()]
                if len(values) != GRID_SIZE:
                    print(f'  Need exactly {GRID_SIZE} values.')
                    continue
                break
            except ValueError:
                print('  Could not parse as integers, try again.')

        for c, val in enumerate(values):
            sig = cell_signature(cells[r][c])
            if val == 0:
                references[0] = sig
                print(f'  Empty     → RGB{sig}')
                continue
            references[val] = sig
            print(f'  Tile {val:>5} → RGB{sig}')

    # Sanity check: warn if two different tile values got the same color
    seen_colors = {}
    conflicts = []
    for val, sig in references.items():
        for other_val, other_sig in seen_colors.items():
            if color_distance(sig, other_sig) < 10:
                conflicts.append((val, other_val, sig))
        seen_colors[val] = sig

    if conflicts:
        print('\n  WARNING: These tiles have nearly identical colors:')
        for v1, v2, sig in conflicts:
            n1 = 'empty' if v1 == 0 else str(v1)
            n2 = 'empty' if v2 == 0 else str(v2)
            print(f'    Tile {n1} and tile {n2} → both RGB{sig}')
        print('  This will cause misclassification!')
        print(f'  Please re-check your input against {snapshot_path}')
        if input('  Redo calibration? (y/n): ').strip().lower() == 'y':
            return calibrate_interactive(region)

    save_references(references)
    tol = update_tolerance(references)
    new_count = len(references) - prev_count
    print(f'Saved {len(references)} tile references ({new_count} new, {prev_count} kept) '
          f'(effective tolerance: {tol:.1f})\n')
    return references


def add_unknown_tile(region, row, col, value):
    """Helper: manually add one tile's color (e.g., when a new value appears)."""
    img = capture(region)
    cells = split_into_cells(img)
    sig = cell_signature(cells[row][col])
    refs = load_references()
    refs[value] = sig
    save_references(refs)
    print(f'Added tile {value} → RGB{sig}')


def recalibrate_unknowns(region, references, unknowns):
    """Prompt user to identify unrecognized tiles. Returns updated references dict."""
    print(f'\n--- {len(unknowns)} unrecognized tile(s) detected ---')
    print('The board has cells the app cannot identify (likely new high-value tiles).')
    print('Please look at your game screen and enter the value for each cell below.')
    print('Enter 0 if the cell is actually empty, or "s" to skip.\n')

    img = capture(region)
    cells = split_into_cells(img)
    updated = False

    for r, c, sig in unknowns:
        # Skip if this color is already close to a known reference
        # (e.g., user already taught us this color in an earlier cell)
        already_known = any(
            color_distance(sig, ref) <= _effective_tolerance
            for ref in references.values()
        )
        if already_known:
            continue

        while True:
            raw = input(f'  Cell (row {r+1}, col {c+1}) — RGB{sig}: ').strip().lower()
            if raw == 's':
                break
            try:
                val = int(raw)
                if val < 0:
                    print('    Value must be >= 0.')
                    continue
                fresh_sig = cell_signature(cells[r][c])
                references[val] = fresh_sig
                print(f'    Learned: {"empty" if val == 0 else f"tile {val}"} → RGB{fresh_sig}')
                updated = True
                break
            except ValueError:
                print('    Enter a number or "s" to skip.')

    if updated:
        save_references(references)
        tol = update_tolerance(references)
        print(f'  Saved {len(references)} tile references (tolerance: {tol:.1f}).\n')
    return references
