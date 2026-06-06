# Ragnarok Origin Classic - 2048 Auto-Solver

Watches a region of ROOC Client, parses the 2048 board, computes the best move with expectimax, and sends a swipe. Features a GUI built with customtkinter for setup, calibration, and live board monitoring. Requires Interception to be installed in order for the key events to work.

## Pipeline

```
screenshot region → split 4×4 → color-match each cell → expectimax → mouse swipe → wait 1s → repeat
```

## Setup (Windows)

```powershell
cd rooc-2048-game-solver
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10+ recommended.

### Installing the Interception driver

The solver uses the [Interception](https://github.com/oblitum/Interception) driver to send kernel-level key events that the game client can actually receive. Without it, input will not work.

1. Download **Interception.zip** from the [latest release](https://github.com/oblitum/Interception/releases).
2. Extract it and copy the DLL into this project folder:
   - 64-bit Python → `Interception/library/x64/interception.dll`
   - 32-bit Python → `Interception/library/x86/interception.dll`
3. Open an **admin** command prompt in the extracted Interception folder and run:
   ```
   install-interception.exe /install
   ```
4. **Reboot** your PC — the driver only loads after a restart.
5. Verify the setup:
   ```powershell
   python setup_interception.py
   ```

> If you want to use a different input method (mouse drag, keyboard, DirectInput, PostMessage), change `INPUT_METHOD` in `config.py` — Interception is only required when `INPUT_METHOD = "interception"`.

## Usage

```powershell
python main.py
```

This launches the GUI. A CLI mode is also available with `python main.py --cli`.

### GUI overview

The GUI has a **sidebar** on the left for setup and settings, and a **main area** showing the live board, stats, and a log.

### 1. Pick the game window

Click **Pick Window** in the sidebar. A dialog lists all visible windows — hover to highlight them on screen. Select the game window so the solver can focus it before each swipe.

### 2. Pick the board region

Click **Pick Region**. A translucent overlay covers the screen — drag a rectangle around **just the 4×4 grid**, excluding the score panel, preview indicator, and buttons. The tighter the box, the more reliable the parsing.

Saved to `region.json`. Click **Pick Region** again at any time to redo it.

### 3. Calibrate tile colors

Click **Calibrate**. A dialog shows a snapshot of the board split into cells. Enter the tile value for each cell (0 = empty) and click **Save**. This records each tile's color signature to `tile_references.json`.

You only need to calibrate **once per game**, but you should re-run calibration if:
- A tile value appears that wasn't on the board during calibration (e.g., your first 32 or 64)
- The game's visual theme changes
- The classifier starts misreading cells

### 4. (Optional) Next tile region

Click **Next Tile Region** to select the "about to appear" preview indicator. This lets the solver know exactly which tile will spawn next, improving accuracy.

### 5. Start the solver

Click **START**. The solver begins reading the board, computing the best move, and sending input. The board view updates in real time, and stats (moves, max tile, estimated score) are displayed below it.

Click **STOP** to pause at any time.

### Sidebar settings

- **Solver** — switch between `ntuple`, `expectimax`, or `mcts`
- **Input** — choose the input method (`interception`, `postmessage`, `keyboard`, `mouse`, etc.)
- **Search Depth** — adjust the expectimax search depth via the slider

## Configuration

Most settings can be changed from the GUI sidebar. For additional tuning, edit `config.py` directly:

| Setting | Default | Notes |
|---|---|---|
| `LOOP_DELAY` | `1.0` | Seconds between moves. Lower if the game animates fast. |
| `SOLVER_MODE` | `"ntuple"` | `"ntuple"`, `"expectimax"`, or `"mcts"` (also changeable in GUI). |
| `SEARCH_DEPTH` | `6` | Expectimax depth (also adjustable via GUI slider). |
| `COLOR_MATCH_TOLERANCE` | `45` | Bigger = more permissive matching. Raise if tiles get misclassified as empty. |
| `INPUT_METHOD` | `"interception"` | Input method (also changeable in GUI). |
| `SWIPE_REACH` | `0.35` | Drag length as a fraction of the board size. Increase if swipes don't register. |

## Tuning the parser

If `parse_board` is misreading the board:

1. **Region too loose** — the cells include extra background, throwing off color signatures. Click **Pick Region** again and draw a tighter box.
2. **New tile value not in references** — click **Calibrate** to add the missing tile.
3. **Tolerance too low** — raise `COLOR_MATCH_TOLERANCE` in `config.py`.
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

Want a smarter solver? Increase `SEARCH_DEPTH` using the GUI slider or in `config.py`.

## Project layout

```
rooc-2048-game-solver/
├── main.py               # Entry point (launches GUI, or --cli for terminal mode)
├── region_picker.py      # Tkinter overlay for picking the board area
├── vision.py             # Screenshot, split, classify, calibrate
├── solver.py             # 2048 mechanics + expectimax
├── ntuple_network.py     # N-tuple network for board evaluation
├── train_ntuple.py       # Training script for n-tuple weights
├── train_fast.c          # C implementation of fast training
├── actions.py            # Swipe via mouse drag or arrow keys
├── interception_input.py # Kernel-level input via Interception driver
├── setup_interception.py # Interactive Interception driver setup
├── config.py             # All tunable constants
├── gui.py                # customtkinter GUI (setup, calibration, live board)
├── debug_grid.py         # Debug visualization
├── convert_weights.py    # Weight format converter
├── requirements.txt
└── README.md
```

## Notes

- Mouse-mode swipes work for emulators (BlueStacks, LDPlayer, MuMu) and most desktop 2048 clones. If your specific game uses DirectInput exclusively, `pyautogui` won't reach it — you'd need `pydirectinput` as a drop-in replacement.
- The "About to appear" preview can be captured using the **Next Tile Region** button. When set, the solver uses the known next tile instead of 90%/10% probability estimates, improving accuracy.
- If the game has online leaderboards or rewards tied to scores, auto-play may violate its terms of service. Personal/offline use is what this is built for.
