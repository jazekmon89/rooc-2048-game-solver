"""Configuration for the 2048 auto-solver."""

# --- Grid ---
GRID_SIZE = 4

# --- Timing ---
LOOP_DELAY = 1.0
SWIPE_DURATION = 0.08
POST_SWIPE_PAUSE = 0.15
STABLE_CHECK_INTERVAL = 0.15   # seconds between captures when waiting for animation
STABLE_CHECK_MAX_WAIT = 2.0    # max seconds to wait for board to stabilize

# --- Solver ---
SOLVER_MODE = "ntuple"          # "ntuple", "expectimax", or "mcts"

# MCTS settings (if SOLVER_MODE = "mcts")
MCTS_SIMULATIONS = 800
MCTS_MAX_ROLLOUT_DEPTH = 25
MCTS_TIME_LIMIT = 0.4

# Expectimax settings
SEARCH_DEPTH = 6
SEARCH_DEPTH_CRITICAL = 8      # depth when empties <= 3
SEARCH_DEPTH_TRANSITION = 7    # depth when empties is 4-5
CHANCE_SAMPLE_SIZE = 6          # max empty cells to evaluate per chance node

# Heuristic weights (used by both MCTS and expectimax)
W_SNAKE = 1.0
W_MONOTONICITY = 47.0
W_SMOOTHNESS = 25.0
W_EMPTY = 270.0
W_MERGE = 50.0
W_ANCHOR = 50.0                # strong reward for max tile in corner
W_ANCHOR_PENALTY = 80.0        # penalty when max tile NOT in any corner
W_TRAPPED = 40.0               # penalty for small tiles surrounded by large ones
W_SANDWICH = 40.0              # penalty for tile sandwiched between large opposing neighbors
W_SPAWN_DANGER = 35.0          # penalty for empty cells where a spawn would be trapped
SNAKE_WEIGHT_BASE = 1.45       # exponential base for snake weights (~256:1 ratio)

# --- Vision ---
COLOR_MATCH_TOLERANCE = 45
CELL_INSET_RATIO = 0.22
UNKNOWN_TILE_THRESHOLD = 1     # pause for recalibration if this many cells are unrecognized

# --- Input ---
# "mouse"                — pyautogui mouse drag
# "keyboard"             — pyautogui arrow keys
# "directinput"          — pydirectinput mouse drag (SendInput)
# "directinput_keyboard" — pydirectinput arrow keys (SendInput)
# "postmessage"          — WM_KEYDOWN/UP sent directly to window handle
# "postmessage_mouse"    — WM_LBUTTONDOWN/MOUSEMOVE/UP sent to window handle
# "interception"         — Kernel-level via Interception driver (run setup_interception.py)
INPUT_METHOD = "interception"
SWIPE_REACH = 0.35

# --- Files ---
REGION_FILE = "region.json"
NEXT_TILE_REGION_FILE = "next_tile_region.json"
TILE_REFERENCES_FILE = "tile_references.json"
GAME_WINDOW_FILE = "game_window.json"
NTUPLE_WEIGHTS_FILE = "ntuple_weights.npz"