"""2048 board logic and solver (MCTS + expectimax).

Move semantics match standard 2048: tiles slide toward the swipe direction;
equal adjacent tiles merge once per move (4+4+4 = 8 + 4, not 12 or 16).

Two solver modes:
- MCTS (default): Monte Carlo rollouts — simulate many random games per move.
  Naturally handles spawn randomness and sees further ahead than fixed-depth search.
- Expectimax: depth-limited tree search with transposition table and adaptive depth.

The heuristic (used by both) combines:
- Exponential snake gradient, monotonicity, smoothness, empty cells,
  merge potential, anchor bonus/penalty, trapped tile penalty, sandwich penalty.
"""

import math
import random
import time
import config
from config import (
    GRID_SIZE,
    # MCTS
    MCTS_SIMULATIONS, MCTS_MAX_ROLLOUT_DEPTH, MCTS_TIME_LIMIT,
    # Expectimax
    SEARCH_DEPTH_CRITICAL, SEARCH_DEPTH_TRANSITION, CHANCE_SAMPLE_SIZE,
    # Heuristic
    W_SNAKE, W_MONOTONICITY, W_SMOOTHNESS, W_EMPTY, W_MERGE,
    W_ANCHOR, W_ANCHOR_PENALTY, W_TRAPPED, W_SANDWICH, W_SPAWN_DANGER,
    SNAKE_WEIGHT_BASE,
)

GRID = GRID_SIZE

# Corner positions for quick lookup
_CORNERS = [(0, 0), (0, GRID - 1), (GRID - 1, 0), (GRID - 1, GRID - 1)]

# Neighbor offsets
_DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))

# Move names list for random selection
_MOVE_NAMES = ['up', 'down', 'left', 'right']


# ---------- log2 lookup ----------

_LOG2 = {0: 0}
for _i in range(1, 18):  # 2^1 through 2^17 = 131072
    _LOG2[1 << _i] = _i


def _log2(v):
    """Fast log2 for powers of 2. Falls back to math.log2."""
    return _LOG2.get(v) or (math.log2(v) if v > 0 else 0)


# ---------- exponential snake weights ----------

_SNAKE_ORDER = [
    [0,  1,  2,  3],
    [7,  6,  5,  4],
    [8,  9,  10, 11],
    [15, 14, 13, 12],
]


def _build_exp_weights(order, base):
    return [
        [base ** order[r][c] for c in range(GRID)]
        for r in range(GRID)
    ]


def _mirror_h(w):
    return [list(reversed(row)) for row in w]


def _mirror_v(w):
    return list(reversed(w))


def _all_orientations(base):
    bl = _build_exp_weights(_SNAKE_ORDER, base)
    return [
        bl,
        _mirror_h(bl),
        _mirror_v(bl),
        _mirror_h(_mirror_v(bl)),
    ]


_ORIENTATIONS = _all_orientations(SNAKE_WEIGHT_BASE)


def _best_snake_weights(b):
    """Pick the orientation that maximizes the total snake score across ALL tiles."""
    best_w, best_score = _ORIENTATIONS[0], -float('inf')
    for w in _ORIENTATIONS:
        score = 0
        for r in range(GRID):
            for c in range(GRID):
                v = b[r][c]
                if v > 0:
                    score += _log2(v) * w[r][c]
        if score > best_score:
            best_score = score
            best_w = w
    return best_w


# ---------- pre-computed row move tables ----------

def _compress_left(row):
    packed = [v for v in row if v != 0]
    out, i = [], 0
    while i < len(packed):
        if i + 1 < len(packed) and packed[i] == packed[i + 1]:
            out.append(packed[i] * 2)
            i += 2
        else:
            out.append(packed[i])
            i += 1
    while len(out) < GRID:
        out.append(0)
    return out


# Build lookup tables: _ROW_LEFT[row_tuple] -> result_tuple
# and _ROW_RIGHT[row_tuple] -> result_tuple
# Tiles are powers of 2 (0,2,4,8,...,131072) so there are at most 18 distinct
# values per cell. We enumerate all combinations that can appear in practice.
_TILE_VALUES = [0] + [1 << i for i in range(1, 18)]  # 0,2,4,...,131072

_ROW_LEFT = {}
_ROW_RIGHT = {}

def _build_row_tables():
    """Pre-compute left/right move results for all encountered rows."""
    # We can't enumerate all 18^4 = 104976 combos upfront easily,
    # so we use lazy caching instead.
    pass

def _row_left(row_tuple):
    """Cached left-compress for a row tuple."""
    result = _ROW_LEFT.get(row_tuple)
    if result is not None:
        return result
    result = tuple(_compress_left(row_tuple))
    _ROW_LEFT[row_tuple] = result
    return result

def _row_right(row_tuple):
    """Cached right-compress for a row tuple."""
    result = _ROW_RIGHT.get(row_tuple)
    if result is not None:
        return result
    rev = (row_tuple[3], row_tuple[2], row_tuple[1], row_tuple[0])
    left = _row_left(rev)
    result = (left[3], left[2], left[1], left[0])
    _ROW_RIGHT[row_tuple] = result
    return result


# ---------- moves (using tuple boards for speed) ----------

def _board_to_tuples(b):
    """Convert list-of-lists board to tuple-of-tuples."""
    return (tuple(b[0]), tuple(b[1]), tuple(b[2]), tuple(b[3]))

def _tuples_to_board(t):
    """Convert tuple-of-tuples back to list-of-lists."""
    return [list(t[0]), list(t[1]), list(t[2]), list(t[3])]

def move_left(b):
    return [list(_row_left(tuple(row))) for row in b]

def move_right(b):
    return [list(_row_right(tuple(row))) for row in b]

def move_up(b):
    # Transpose, move left, transpose back
    cols = []
    for c in range(GRID):
        col = (b[0][c], b[1][c], b[2][c], b[3][c])
        cols.append(_row_left(col))
    return [[cols[c][r] for c in range(GRID)] for r in range(GRID)]

def move_down(b):
    cols = []
    for c in range(GRID):
        col = (b[0][c], b[1][c], b[2][c], b[3][c])
        cols.append(_row_right(col))
    return [[cols[c][r] for c in range(GRID)] for r in range(GRID)]


MOVES = {
    'up': move_up,
    'down': move_down,
    'left': move_left,
    'right': move_right,
}

_MOVE_FNS = [move_up, move_down, move_left, move_right]


# ---------- helpers ----------

def boards_equal(a, b):
    return (a[0] == b[0] and a[1] == b[1] and a[2] == b[2] and a[3] == b[3])


def empty_cells(b):
    return [(r, c) for r in range(GRID) for c in range(GRID) if b[r][c] == 0]


def _copy_board(b):
    return [row[:] for row in b]


def _spawn_random_tile(b):
    """Spawn a 2 (90%) or 4 (10%) in a random empty cell. Modifies b in place."""
    empties = empty_cells(b)
    if not empties:
        return False
    r, c = random.choice(empties)
    b[r][c] = 2 if random.random() < 0.9 else 4
    return True


# ---------- heuristic components ----------

def _monotonicity(b):
    total = 0
    for r in range(GRID):
        inc = dec = 0
        for c in range(GRID - 1):
            lv = _log2(b[r][c])
            rv = _log2(b[r][c + 1])
            if lv > rv:
                inc -= (lv - rv)
            elif rv > lv:
                dec -= (rv - lv)
        total += max(inc, dec)

    for c in range(GRID):
        inc = dec = 0
        for r in range(GRID - 1):
            tv = _log2(b[r][c])
            bv = _log2(b[r + 1][c])
            if tv > bv:
                inc -= (tv - bv)
            elif bv > tv:
                dec -= (bv - tv)
        total += max(inc, dec)

    return total


def _merge_potential(b):
    """Value-weighted merge potential: merging high tiles is worth much more."""
    merges = 0.0
    for r in range(GRID):
        for c in range(GRID):
            v = b[r][c]
            if v == 0:
                continue
            lv = _log2(v)
            if c + 1 < GRID and b[r][c + 1] == v:
                merges += lv
            if r + 1 < GRID and b[r + 1][c] == v:
                merges += lv
    return merges


def _trapped_penalty(b):
    penalty = 0.0
    for r in range(GRID):
        for c in range(GRID):
            v = b[r][c]
            if v == 0:
                continue
            neighbors = []
            for dr, dc in _DIRS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID and 0 <= nc < GRID and b[nr][nc] > 0:
                    neighbors.append(b[nr][nc])
            if not neighbors:
                continue
            min_neighbor = min(neighbors)
            if min_neighbor >= v * 4:
                penalty -= (_log2(min_neighbor) - _log2(v))
    return penalty


def _sandwich_penalty(b):
    penalty = 0.0
    for r in range(GRID):
        for c in range(GRID):
            v = b[r][c]
            if v == 0:
                continue
            threshold = v * 4
            if 0 < c < GRID - 1:
                left, right = b[r][c - 1], b[r][c + 1]
                if left >= threshold and right >= threshold:
                    ratio = _log2(min(left, right)) - _log2(v)
                    penalty -= ratio * ratio
            if 0 < r < GRID - 1:
                up, down = b[r - 1][c], b[r + 1][c]
                if up >= threshold and down >= threshold:
                    ratio = _log2(min(up, down)) - _log2(v)
                    penalty -= ratio * ratio
    return penalty


def _spawn_danger(b):
    """Penalize empty cells where a new tile spawn would be immediately trapped.

    For each empty cell, simulate placing a small tile (2) there and check
    if ALL its non-empty neighbors are >= 4x that value (i.e., >= 8).
    Such spawns create trapped tiles that can't merge with anything nearby.
    Returns a non-positive value.
    """
    penalty = 0.0
    for r in range(GRID):
        for c in range(GRID):
            if b[r][c] != 0:
                continue
            # Check what happens if a 2 spawns here
            neighbors = []
            for dr, dc in _DIRS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID and 0 <= nc < GRID and b[nr][nc] > 0:
                    neighbors.append(b[nr][nc])
            if not neighbors:
                continue
            min_neighbor = min(neighbors)
            # A 2 spawning here would be trapped if all neighbors >= 8 (4x of 2)
            if min_neighbor >= 8:
                # Penalty proportional to how large the surrounding tiles are
                avg_log = sum(_log2(n) for n in neighbors) / len(neighbors)
                penalty -= avg_log
    return penalty


def _corner_check(b, max_tile):
    for r, c in _CORNERS:
        if b[r][c] == max_tile:
            return True
    return False


# ---------- heuristic ----------

def heuristic(b):
    """Evaluate board position. Higher is better."""
    empties = len(empty_cells(b))

    weights = _best_snake_weights(b)
    snake_score = 0
    for r in range(GRID):
        for c in range(GRID):
            v = b[r][c]
            if v > 0:
                snake_score += _log2(v) * weights[r][c]

    max_tile = max(max(row) for row in b)
    log_max = _log2(max_tile)
    anchor_score = 0

    max_w_pos = max(
        ((r, c) for r in range(GRID) for c in range(GRID)),
        key=lambda rc: weights[rc[0]][rc[1]]
    )
    if b[max_w_pos[0]][max_w_pos[1]] == max_tile:
        anchor_score = log_max * W_ANCHOR
    elif _corner_check(b, max_tile):
        anchor_score = log_max * W_ANCHOR * 0.5
    else:
        anchor_score = -(log_max ** 2) * W_ANCHOR_PENALTY

    mono = _monotonicity(b)

    smoothness = 0
    for r in range(GRID):
        for c in range(GRID):
            v = b[r][c]
            if v == 0:
                continue
            lv = _log2(v)
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID and 0 <= nc < GRID and b[nr][nc] > 0:
                    smoothness -= abs(lv - _log2(b[nr][nc]))

    merges = _merge_potential(b)
    trapped = _trapped_penalty(b)
    sandwich = _sandwich_penalty(b)
    spawn_danger = _spawn_danger(b)

    return (
        snake_score * W_SNAKE
        + mono * W_MONOTONICITY
        + smoothness * W_SMOOTHNESS
        + empties * W_EMPTY
        + merges * W_MERGE
        + anchor_score
        + trapped * W_TRAPPED
        + sandwich * W_SANDWICH
        + spawn_danger * W_SPAWN_DANGER
    )


# =====================================================================
# MCTS (Monte Carlo Tree Search) solver
# =====================================================================

# Pre-compute preferred move orders for each corner anchor.
# For each corner, we prefer moves that push tiles TOWARD that corner.
_CORNER_MOVE_PREFS = {
    (0, 0):           [move_up, move_left, move_right, move_down],
    (0, GRID - 1):    [move_up, move_right, move_left, move_down],
    (GRID - 1, 0):    [move_down, move_left, move_right, move_up],
    (GRID - 1, GRID - 1): [move_down, move_right, move_left, move_up],
}


def _find_max_corner(b):
    """Return the corner (r, c) nearest to the max tile."""
    max_val = 0
    max_r = max_c = 0
    for r in range(GRID):
        for c in range(GRID):
            if b[r][c] > max_val:
                max_val = b[r][c]
                max_r, max_c = r, c
    # Snap to nearest corner
    cr = 0 if max_r < GRID / 2 else GRID - 1
    cc = 0 if max_c < GRID / 2 else GRID - 1
    return (cr, cc)


def _rollout(b, max_depth, preferred_fns):
    """Fast rollout using corner-biased move strategy.

    Moves are selected by trying preferred directions first (toward the
    anchor corner), with random shuffling of the top 2 preferred moves
    for diversity. NO heuristic calls during the rollout — only at the end.
    This makes each rollout ~0.1ms, enabling thousands per decision.
    """
    board = _copy_board(b)
    for _ in range(max_depth):
        moved = False
        # Shuffle the top 2 preferred moves for diversity, keep rest ordered
        fns = list(preferred_fns)
        if random.random() < 0.5:
            fns[0], fns[1] = fns[1], fns[0]

        for fn in fns:
            nb = fn(board)
            if not boards_equal(board, nb):
                board = nb
                moved = True
                break
        if not moved:
            break
        _spawn_random_tile(board)

    return heuristic(board)


def _mcts_best_move(board, next_tile=None):
    """MCTS solver: run thousands of fast rollouts per move."""
    # Find valid moves
    valid_moves = []
    for name, fn in MOVES.items():
        nb = fn(board)
        if not boards_equal(board, nb):
            valid_moves.append((name, nb))

    if not valid_moves:
        return None

    if len(valid_moves) == 1:
        return valid_moves[0][0]

    # Determine preferred move order based on max tile corner
    corner = _find_max_corner(board)
    preferred_fns = _CORNER_MOVE_PREFS[corner]

    # Run rollouts for each move
    move_scores = {name: 0.0 for name, _ in valid_moves}
    move_counts = {name: 0 for name, _ in valid_moves}

    start_time = time.time()
    time_limit = MCTS_TIME_LIMIT
    n_sims = MCTS_SIMULATIONS
    rounds = 0

    while True:
        # Check time limit
        if time_limit > 0 and time.time() - start_time >= time_limit:
            break
        if rounds >= n_sims:
            break

        for name, nb in valid_moves:
            rollout_board = _copy_board(nb)

            # Spawn tile
            if next_tile is not None and move_counts[name] == 0:
                empties = empty_cells(rollout_board)
                if empties:
                    r, c = random.choice(empties)
                    rollout_board[r][c] = next_tile
            else:
                _spawn_random_tile(rollout_board)

            score = _rollout(rollout_board, MCTS_MAX_ROLLOUT_DEPTH, preferred_fns)
            move_scores[name] += score
            move_counts[name] += 1

        rounds += 1

    # Pick the move with highest average score
    best_name, best_avg = None, -float('inf')
    for name, _ in valid_moves:
        if move_counts[name] > 0:
            avg = move_scores[name] / move_counts[name]
            if avg > best_avg:
                best_avg = avg
                best_name = name

    return best_name


# =====================================================================
# Expectimax solver (kept as alternative)
# =====================================================================

_tt = {}


def _board_key(b):
    return tuple(b[0]) + tuple(b[1]) + tuple(b[2]) + tuple(b[3])


def expectimax(b, depth, is_player, next_tile=None):
    if depth == 0:
        return heuristic(b)

    tt_key = None
    if next_tile is None:
        tt_key = (_board_key(b), depth, is_player)
        cached = _tt.get(tt_key)
        if cached is not None:
            return cached

    if is_player:
        best = None
        for fn in MOVES.values():
            nb = fn(b)
            if not boards_equal(b, nb):
                v = expectimax(nb, depth - 1, False, next_tile)
                if best is None or v > best:
                    best = v
        result = best if best is not None else heuristic(b) - 10_000_000
    else:
        empties = empty_cells(b)
        if not empties:
            result = heuristic(b)
        else:
            if len(empties) > CHANCE_SAMPLE_SIZE:
                step = len(empties) / CHANCE_SAMPLE_SIZE
                sample = [empties[int(i * step)] for i in range(CHANCE_SAMPLE_SIZE)]
            else:
                sample = empties

            total = 0.0
            if next_tile is not None:
                for r, c in sample:
                    nb = [row[:] for row in b]
                    nb[r][c] = next_tile
                    total += expectimax(nb, depth - 1, True, None)
            else:
                for r, c in sample:
                    for val, prob in ((2, 0.9), (4, 0.1)):
                        nb = [row[:] for row in b]
                        nb[r][c] = val
                        total += prob * expectimax(nb, depth - 1, True, None)
            result = total / len(sample)

    if tt_key is not None:
        _tt[tt_key] = result
    return result


def _adaptive_depth(b, base_depth):
    empties = len(empty_cells(b))
    if empties <= 3:
        return max(base_depth, SEARCH_DEPTH_CRITICAL)
    elif empties <= 5:
        return max(base_depth, SEARCH_DEPTH_TRANSITION)
    return base_depth


def _restricted_direction(board):
    """Determine which move direction would push the max tile off its edge.

    This is the KEY strategic constraint for 2048: never move in the direction
    that dislodges the max tile from its edge, unless no other move works.
    - Max tile on bottom edge (row 3) → restrict 'up'
    - Max tile on top edge (row 0)    → restrict 'down'
    Returns the restricted direction name, or None if max tile isn't on an edge.
    """
    max_tile = max(max(row) for row in board)
    for r in range(GRID):
        for c in range(GRID):
            if board[r][c] == max_tile:
                if r == 0:
                    return 'down'
                if r == GRID - 1:
                    return 'up'
                return None
    return None


def _expectimax_best_move(board, next_tile=None):
    """Expectimax solver with soft move restriction.

    The restricted direction (which would push the max tile off its edge)
    gets a score penalty. It can still be chosen, but only if it's
    significantly better than alternatives (e.g., a critical merge).
    """
    global _tt
    _tt = {}

    actual_depth = _adaptive_depth(board, config.SEARCH_DEPTH)
    restricted = _restricted_direction(board)

    # Penalty scales with max tile: small tiles = small penalty, big tiles = big penalty
    max_tile = max(max(row) for row in board)
    restrict_penalty = _log2(max_tile) ** 2 * 30 if restricted else 0

    best_name, best_score = None, -float('inf')
    for name, fn in MOVES.items():
        nb = fn(board)
        if not boards_equal(board, nb):
            score = expectimax(nb, actual_depth - 1, False, next_tile)
            # Apply soft penalty to restricted direction
            if name == restricted:
                score -= restrict_penalty
            if score > best_score:
                best_score = score
                best_name = name
    return best_name


# =====================================================================
# N-tuple network solver
# =====================================================================

_ntuple_net = None


def _load_ntuple_network():
    """Lazy-load the N-tuple network weights."""
    global _ntuple_net
    if _ntuple_net is not None:
        return _ntuple_net

    from ntuple_network import NTupleNetwork
    from config import NTUPLE_WEIGHTS_FILE

    _ntuple_net = NTupleNetwork()
    if _ntuple_net.load(NTUPLE_WEIGHTS_FILE):
        print(f'N-tuple network loaded: {NTUPLE_WEIGHTS_FILE} '
              f'({_ntuple_net.total_weights():,} weights)')
    else:
        print(f'WARNING: No trained weights found at {NTUPLE_WEIGHTS_FILE}')
        print(f'  Run: python train_ntuple.py')
        print(f'  Falling back to expectimax solver.')
        _ntuple_net = None
    return _ntuple_net


def _ntuple_eval(b):
    """Evaluate using the N-tuple network (learned heuristic)."""
    net = _load_ntuple_network()
    if net is None:
        return heuristic(b)
    return net.evaluate(b)


_ntt = {}  # transposition table for ntuple expectimax


def _ntuple_expectimax(b, depth, is_player, next_tile=None):
    """Expectimax search using the N-tuple network as evaluation function."""
    if depth == 0:
        return _ntuple_eval(b)

    tt_key = None
    if next_tile is None:
        tt_key = (_board_key(b), depth, is_player)
        cached = _ntt.get(tt_key)
        if cached is not None:
            return cached

    if is_player:
        best = None
        for fn in MOVES.values():
            nb = fn(b)
            if not boards_equal(b, nb):
                v = _ntuple_expectimax(nb, depth - 1, False, next_tile)
                if best is None or v > best:
                    best = v
        result = best if best is not None else _ntuple_eval(b) - 10_000_000
    else:
        empties = empty_cells(b)
        if not empties:
            result = _ntuple_eval(b)
        else:
            if len(empties) > CHANCE_SAMPLE_SIZE:
                step = len(empties) / CHANCE_SAMPLE_SIZE
                sample = [empties[int(i * step)] for i in range(CHANCE_SAMPLE_SIZE)]
            else:
                sample = empties

            total = 0.0
            if next_tile is not None:
                for r, c in sample:
                    nb = [row[:] for row in b]
                    nb[r][c] = next_tile
                    total += _ntuple_expectimax(nb, depth - 1, True, None)
            else:
                for r, c in sample:
                    for val, prob in ((2, 0.9), (4, 0.1)):
                        nb = [row[:] for row in b]
                        nb[r][c] = val
                        total += prob * _ntuple_expectimax(nb, depth - 1, True, None)
            result = total / len(sample)

    if tt_key is not None:
        _ntt[tt_key] = result
    return result


def _ntuple_best_move(board, next_tile=None):
    """Expectimax search with N-tuple learned evaluation.

    Combines the deep lookahead of expectimax with the learned evaluation
    of the N-tuple network. Much stronger than either alone.
    """
    net = _load_ntuple_network()
    if net is None:
        return _expectimax_best_move(board, next_tile)

    global _ntt
    _ntt = {}

    actual_depth = _adaptive_depth(board, config.SEARCH_DEPTH)

    best_name, best_score = None, -float('inf')
    for name, fn in MOVES.items():
        nb = fn(board)
        if not boards_equal(board, nb):
            score = _ntuple_expectimax(nb, actual_depth - 1, False, next_tile)
            if score > best_score:
                best_score = score
                best_name = name
    return best_name


# =====================================================================
# Public API
# =====================================================================

def best_move(board, depth=None, next_tile=None):
    """Return 'up'/'down'/'left'/'right', or None if board is locked."""
    mode = config.SOLVER_MODE
    if mode == "ntuple":
        return _ntuple_best_move(board, next_tile)
    elif mode == "mcts":
        return _mcts_best_move(board, next_tile)
    else:
        return _expectimax_best_move(board, next_tile)


def is_game_over(board):
    """No empty cells AND no merges possible in any direction."""
    if empty_cells(board):
        return False
    return all(boards_equal(board, fn(board)) for fn in MOVES.values())
