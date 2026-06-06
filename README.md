# 2048 Auto-Solver

Watches a region of your screen, parses the 2048 board, computes the best move with expectimax, and sends a swipe. Runs in the background as a Python script.

## Pipeline

```
screenshot region → split 4×4 → color-match each cell → expectimax → mouse swipe → wait 1s → repeat
```

## Setup (Windows)

```powershell
cd ai2048
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10+ recommended.

## First run

```powershell
python main.py
```

The script will walk you through three steps:

### 1. Pick the board region

A translucent overlay covers the screen. Drag a rectangle around **just the 4×4 grid** — exclude the score panel, "About to appear" preview, and bottom buttons. The tighter the box, the more reliable the parsing.

Saved to `region.json`. Delete that file (or answer "no" at startup) to repick.

### 2. Calibrate tile colors

The script captures a snapshot and asks you to type the current board state, one row at a time. Example:

```
Row 1: 0 0 0 0
Row 2: 0 2 0 0
Row 3: 16 0 0 0
Row 4: 8 0 4 0
```

For each non-zero cell it records the tile's color signature. Saved to `tile_references.json`.

You only need to calibrate **once per game**, but you should re-run calibration if:
- A tile value appears that wasn't on the board during calibration (e.g., your first 32 or 64)
- The game's visual theme changes
- The classifier starts misreading cells

To add a single tile without redoing the whole grid, use the helper from a Python shell:
```python
from vision import add_unknown_tile
import json
region = json.load(open('region.json'))
add_unknown_tile(region, row=0, col=2, value=64)  # 0-indexed
```

### 3. Solver loop

Once calibration is saved, the script counts down 3 seconds and begins. Each cycle prints the parsed board and the chosen move.

**Stop the loop:**
- Press `Ctrl+C` in the terminal
- Or slam the mouse cursor into any screen corner (pyautogui failsafe)

## Configuration

All knobs live in `config.py`:

| Setting | Default | Notes |
|---|---|---|
| `LOOP_DELAY` | `1.0` | Seconds between moves. Lower if the game animates fast. |
| `SEARCH_DEPTH` | `3` | Expectimax depth. `4` is smarter but ~5× slower. |
| `COLOR_MATCH_TOLERANCE` | `45` | Bigger = more permissive matching. Raise if tiles get misclassified as empty. |
| `INPUT_METHOD` | `"mouse"` | Switch to `"keyboard"` for browser 2048 or PC games with arrow-key controls. |
| `SWIPE_REACH` | `0.35` | Drag length as a fraction of the board size. Increase if swipes don't register. |

## Tuning the parser

If `parse_board` is misreading the board:

1. **Region too loose** — the cells include extra background, throwing off color signatures. Repick a tighter box.
2. **New tile value not in references** — recalibrate or use `add_unknown_tile`.
3. **Tolerance too low** — raise `COLOR_MATCH_TOLERANCE` in config.
4. **Tiles look very similar** (e.g., 2 and 4 in your theme) — try lowering `CELL_INSET_RATIO` so more pixels contribute to the signature.

Quick diagnostic — drop this into a Python shell to see what the parser sees:
```python
from region_picker import load_region
from vision import capture, split_into_cells, cell_signature, load_references, classify_cell
region = load_region()
refs = load_references()
img = capture(region)
img.save('debug.png')  # inspect what was captured
for r, row in enumerate(split_into_cells(img)):
    for c, cell in enumerate(row):
        print(f'({r},{c}) sig={cell_signature(cell)} → {classify_cell(cell, refs)}')
```

## Tuning the solver

The default heuristic anchors the snake at bottom-left. If you'd rather anchor elsewhere, edit `SNAKE_WEIGHTS` in `solver.py` — put the highest weight on whatever corner you want as your fortress, and snake outward from there.

Want a smarter solver? Bump `SEARCH_DEPTH` to 4 (still real-time at 1s/move) or 5 (start trading speed for strength).

## Project layout

```
ai2048/
├── main.py            # Orchestrator + setup flow
├── region_picker.py   # Tkinter overlay for picking the board area
├── vision.py          # Screenshot, split, classify, calibrate
├── solver.py          # 2048 mechanics + expectimax
├── actions.py         # Swipe via mouse drag or arrow keys
├── config.py          # All tunable constants
├── requirements.txt
└── README.md
```

## Notes

- Mouse-mode swipes work for emulators (BlueStacks, LDPlayer, MuMu) and most desktop 2048 clones. If your specific game uses DirectInput exclusively, `pyautogui` won't reach it — you'd need `pydirectinput` as a drop-in replacement.
- The "About to appear" preview is currently ignored. If you want to use it, capture a second small region above the board, parse it the same way, and pass the known next tile into the solver as the chance node's only spawn (skipping the 2/4 sampling on that ply). This makes the solver materially smarter for games that show previews.
- If the game has online leaderboards or rewards tied to scores, auto-play may violate its terms of service. Personal/offline use is what this is built for.
