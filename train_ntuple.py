"""Train an N-tuple network for 2048 via TD(0) afterstate learning.

Usage:
    python train_ntuple.py [--games 100000] [--lr 0.0025] [--save-every 5000]

The trainer plays complete games using 1-ply expectimax (try all 4 moves,
pick the one with the highest afterstate value). After each move it updates
the network weights using temporal difference learning.

Key concept - AFTERSTATE learning:
  - The "afterstate" is the board AFTER the player moves but BEFORE the
    random tile spawns. This removes randomness from the value function,
    making learning much more stable and efficient.

Progress is printed every 1000 games. Weights are auto-saved periodically
and at the end.

Training 100K games takes roughly 2-6 hours in Python depending on CPU.
"""

import random
import time
import sys
import argparse
import numpy as np
from ntuple_network import NTupleNetwork, _TILE_INDEX

# ---------- fast 2048 game engine with row caching ----------

GRID = 4

# Row move cache: (row_tuple) -> (result_tuple, merge_score)
_ROW_LEFT_CACHE = {}
_ROW_RIGHT_CACHE = {}


def _compress_left_scored(row_tuple):
    """Compress row left and return (result_tuple, score)."""
    cached = _ROW_LEFT_CACHE.get(row_tuple)
    if cached is not None:
        return cached
    packed = [v for v in row_tuple if v != 0]
    out = []
    score = 0
    i = 0
    while i < len(packed):
        if i + 1 < len(packed) and packed[i] == packed[i + 1]:
            merged = packed[i] * 2
            out.append(merged)
            score += merged
            i += 2
        else:
            out.append(packed[i])
            i += 1
    while len(out) < GRID:
        out.append(0)
    result = (tuple(out), score)
    _ROW_LEFT_CACHE[row_tuple] = result
    return result


def _compress_right_scored(row_tuple):
    cached = _ROW_RIGHT_CACHE.get(row_tuple)
    if cached is not None:
        return cached
    rev = (row_tuple[3], row_tuple[2], row_tuple[1], row_tuple[0])
    left_result, score = _compress_left_scored(rev)
    result = ((left_result[3], left_result[2], left_result[1], left_result[0]), score)
    _ROW_RIGHT_CACHE[row_tuple] = result
    return result


def move_left(b):
    nb = []
    total_score = 0
    for row in b:
        new_row, s = _compress_left_scored(tuple(row))
        nb.append(list(new_row))
        total_score += s
    return nb, total_score


def move_right(b):
    nb = []
    total_score = 0
    for row in b:
        new_row, s = _compress_right_scored(tuple(row))
        nb.append(list(new_row))
        total_score += s
    return nb, total_score


def move_up(b):
    cols = []
    total_score = 0
    for c in range(GRID):
        col = (b[0][c], b[1][c], b[2][c], b[3][c])
        new_col, s = _compress_left_scored(col)
        cols.append(new_col)
        total_score += s
    nb = [[cols[c][r] for c in range(GRID)] for r in range(GRID)]
    return nb, total_score


def move_down(b):
    cols = []
    total_score = 0
    for c in range(GRID):
        col = (b[0][c], b[1][c], b[2][c], b[3][c])
        new_col, s = _compress_right_scored(col)
        cols.append(new_col)
        total_score += s
    nb = [[cols[c][r] for c in range(GRID)] for r in range(GRID)]
    return nb, total_score


MOVE_FNS = [move_left, move_right, move_up, move_down]


def boards_equal(a, b):
    return a[0] == b[0] and a[1] == b[1] and a[2] == b[2] and a[3] == b[3]


def empty_cells(b):
    cells = []
    for r in range(GRID):
        for c in range(GRID):
            if b[r][c] == 0:
                cells.append((r, c))
    return cells


def spawn_tile(b):
    empties = empty_cells(b)
    if not empties:
        return False
    r, c = random.choice(empties)
    b[r][c] = 2 if random.random() < 0.9 else 4
    return True


def new_game():
    b = [[0] * GRID for _ in range(GRID)]
    spawn_tile(b)
    spawn_tile(b)
    return b


def max_tile(b):
    return max(max(row) for row in b)


def copy_board(b):
    return [row[:] for row in b]


# ---------- training ----------

def best_afterstate(board, network):
    """Try all 4 moves, return (afterstate, move_score) with highest value.

    Returns (None, 0) if no moves are possible (game over).
    """
    best_board = None
    best_value = -float('inf')
    best_score = 0

    for fn in MOVE_FNS:
        nb, score = fn(board)
        if boards_equal(board, nb):
            continue
        value = network.evaluate(nb) + score
        if value > best_value:
            best_value = value
            best_board = nb
            best_score = score

    return best_board, best_score


def play_game(network, lr):
    """Play one full game, updating weights via TD(0) afterstate learning.

    Returns (max_tile, total_score, n_moves).
    """
    board = new_game()
    total_score = 0
    n_moves = 0

    while True:
        # Find best afterstate (board after move, before spawn)
        afterstate, move_score = best_afterstate(board, network)
        if afterstate is None:
            break  # game over

        total_score += move_score
        n_moves += 1

        # V(s) = current afterstate value
        v_current = network.evaluate(afterstate)

        # Spawn random tile
        board = copy_board(afterstate)
        spawn_tile(board)

        # Find next afterstate
        next_afterstate, next_score = best_afterstate(board, network)

        if next_afterstate is not None:
            # TD target: reward + V(s')
            v_next = network.evaluate(next_afterstate) + next_score
            td_error = v_next - v_current
        else:
            # Terminal state
            td_error = -v_current

        # Update weights
        n_active = len(network.expanded)
        delta = lr * td_error / n_active
        network.update(afterstate, delta)

        if next_afterstate is None:
            break
        # board already has the spawned tile, continue to next move

    return max_tile(board), total_score, n_moves


def train(n_games=100000, lr=0.0025, save_every=5000, weights_file='ntuple_weights.npz'):
    """Train the N-tuple network."""
    network = NTupleNetwork()

    # Try to resume from existing weights
    if network.load(weights_file):
        print(f'Resumed from existing weights: {weights_file}')
    else:
        print('Starting fresh training.')

    print(f'Network: {len(network.patterns)} patterns, '
          f'{len(network.expanded)} expanded tuples, '
          f'{network.total_weights():,} weights ({network.memory_mb():.1f} MB)')
    print(f'Training {n_games:,} games, lr={lr}, saving every {save_every}')
    print()

    stats_interval = 1000
    max_tiles = []
    scores = []
    start_time = time.time()
    interval_start = time.time()

    for game_num in range(1, n_games + 1):
        mt, score, moves = play_game(network, lr)
        max_tiles.append(mt)
        scores.append(score)

        if game_num % stats_interval == 0:
            elapsed = time.time() - interval_start
            total_elapsed = time.time() - start_time

            recent_tiles = max_tiles[-stats_interval:]
            recent_scores = scores[-stats_interval:]

            # Count tile achievements
            counts = {}
            for t in [2048, 4096, 8192, 16384, 32768]:
                counts[t] = sum(1 for x in recent_tiles if x >= t)

            avg_score = sum(recent_scores) / len(recent_scores)
            avg_max = sum(recent_tiles) / len(recent_tiles)
            best = max(recent_tiles)
            games_per_sec = stats_interval / elapsed

            print(f'Game {game_num:>7,} | '
                  f'avg_score {avg_score:>8,.0f} | '
                  f'avg_max {avg_max:>6,.0f} | '
                  f'best {best:>5} | '
                  f'2048+ {counts[2048]:>3}/{stats_interval} | '
                  f'4096+ {counts[4096]:>3}/{stats_interval} | '
                  f'8192+ {counts[8192]:>3}/{stats_interval} | '
                  f'{games_per_sec:.1f} g/s | '
                  f'{total_elapsed/60:.0f}m')

            interval_start = time.time()

        if game_num % save_every == 0:
            network.save(weights_file)
            print(f'  -> Weights saved to {weights_file}')

    # Final save
    network.save(weights_file)
    print(f'\nTraining complete. Final weights saved to {weights_file}')

    # Final stats
    total_time = time.time() - start_time
    print(f'Total time: {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)')
    print(f'Total games: {n_games:,}')

    # Overall achievement rates
    all_tiles = max_tiles
    for t in [512, 1024, 2048, 4096, 8192, 16384]:
        count = sum(1 for x in all_tiles if x >= t)
        print(f'  {t:>5}+ rate: {count/len(all_tiles)*100:.1f}%')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train N-tuple network for 2048')
    parser.add_argument('--games', type=int, default=100000, help='Number of games to train')
    parser.add_argument('--lr', type=float, default=0.0025, help='Learning rate')
    parser.add_argument('--save-every', type=int, default=5000, help='Save weights every N games')
    parser.add_argument('--weights', type=str, default='ntuple_weights.npz', help='Weights file path')
    args = parser.parse_args()

    train(n_games=args.games, lr=args.lr, save_every=args.save_every, weights_file=args.weights)
