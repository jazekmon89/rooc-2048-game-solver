"""N-tuple network for 2048 board evaluation.

Each n-tuple is a pattern of board positions. For a given board state,
we look up the tile values at those positions, convert to indices (0-15),
and use the combined index to look up a weight in a large 1D array.

The evaluation is the sum of weights from all tuples across all 8 symmetries
(4 rotations x 2 reflections). This makes the network rotationally invariant.

Tile encoding: 0=empty, 1=2, 2=4, 3=8, ..., 15=32768  (log2 of tile value)
"""

import numpy as np
import os

# Max tile index: 0 (empty) through 15 (32768). 16 possible values per cell.
N_TILE_VALUES = 16

# N-tuple patterns (board positions as (row, col) pairs).
# These are applied in all 8 symmetries automatically.
#
# N-tuple patterns: mix of 4-tuples and 5-tuples.
# 4-tuples: 16^4 = 65,536 entries. 5-tuples: 16^5 = 1,048,576 entries.
# 5-tuples are more expressive; 4-tuples give broad coverage cheaply.
PATTERNS = [
    # 5-tuples: key strategic patterns (~1M entries each)
    [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)],   # top row + corner turn
    [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)],   # 2x2 + extension
    [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)],   # L-block
    [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1)],   # column + neighbor

    # 4-tuples: rows, columns, squares
    [(0, 0), (0, 1), (0, 2), (0, 3)],   # full row
    [(1, 0), (1, 1), (1, 2), (1, 3)],   # full row
    [(0, 0), (1, 0), (2, 0), (3, 0)],   # full column
    [(0, 0), (0, 1), (1, 0), (1, 1)],   # 2x2
    [(0, 1), (0, 2), (1, 1), (1, 2)],   # 2x2
    [(1, 0), (1, 1), (2, 0), (2, 1)],   # 2x2
    [(0, 0), (0, 1), (1, 1), (1, 2)],   # Z-shape
]


def _rotate_90(pattern):
    """Rotate pattern 90 degrees clockwise on a 4x4 grid."""
    return [(c, 3 - r) for r, c in pattern]


def _reflect_h(pattern):
    """Reflect pattern horizontally on a 4x4 grid."""
    return [(r, 3 - c) for r, c in pattern]


def _all_symmetries(pattern):
    """Generate all 8 symmetries (4 rotations x 2 reflections)."""
    seen = set()
    symmetries = []
    p = list(pattern)
    for _ in range(4):
        key = tuple(sorted(p))
        if key not in seen:
            seen.add(key)
            symmetries.append(list(p))
        ref = _reflect_h(p)
        key_ref = tuple(sorted(ref))
        if key_ref not in seen:
            seen.add(key_ref)
            symmetries.append(ref)
        p = _rotate_90(p)
    return symmetries


def _tile_to_index(tile_value):
    """Convert tile value (0, 2, 4, 8, ...) to index (0, 1, 2, 3, ...)."""
    if tile_value == 0:
        return 0
    # log2 of tile value
    idx = 0
    v = tile_value
    while v > 1:
        v >>= 1
        idx += 1
    return min(idx, N_TILE_VALUES - 1)


# Pre-compute tile-to-index lookup
_TILE_INDEX = {0: 0}
for _i in range(1, 18):
    _TILE_INDEX[1 << _i] = min(_i, N_TILE_VALUES - 1)


class NTupleNetwork:
    """N-tuple network with TD learning support."""

    def __init__(self, patterns=None):
        self.patterns = patterns or PATTERNS

        # Expand each pattern into all its symmetries
        self.expanded = []  # list of (pattern_idx, positions_flat)
        self.table_sizes = []

        for i, pattern in enumerate(self.patterns):
            n = len(pattern)
            table_size = N_TILE_VALUES ** n
            self.table_sizes.append(table_size)
            for sym in _all_symmetries(pattern):
                # Flatten positions for faster iteration
                flat = []
                for r, c in sym:
                    flat.append(r)
                    flat.append(c)
                self.expanded.append((i, tuple(flat)))

        # Weight tables: plain Python lists for fast single-element access
        self.weights = [[0.0] * size for size in self.table_sizes]

    def evaluate(self, board):
        """Evaluate a board position. Returns a scalar score."""
        b0, b1, b2, b3 = board[0], board[1], board[2], board[3]
        rows = (b0, b1, b2, b3)
        ti = _TILE_INDEX
        total = 0.0
        for pattern_idx, flat in self.expanded:
            # Inline index computation for speed
            idx = 0
            for k in range(0, len(flat), 2):
                idx = idx * N_TILE_VALUES + ti.get(rows[flat[k]][flat[k + 1]], 0)
            total += self.weights[pattern_idx][idx]
        return total

    def update(self, board, delta):
        """Update weights for all features active on this board."""
        rows = (board[0], board[1], board[2], board[3])
        ti = _TILE_INDEX
        for pattern_idx, flat in self.expanded:
            idx = 0
            for k in range(0, len(flat), 2):
                idx = idx * N_TILE_VALUES + ti.get(rows[flat[k]][flat[k + 1]], 0)
            self.weights[pattern_idx][idx] += delta

    def save(self, filepath):
        """Save weights to a .npz file."""
        data = {f'w{i}': np.array(w, dtype=np.float32) for i, w in enumerate(self.weights)}
        data['n_tables'] = np.array([len(self.weights)])
        np.savez_compressed(filepath, **data)

    def load(self, filepath):
        """Load weights from a .npz file. Returns True on success."""
        if not os.path.exists(filepath):
            return False
        data = np.load(filepath)
        n = int(data['n_tables'][0])
        if n != len(self.weights):
            return False
        for i in range(n):
            key = f'w{i}'
            if key in data and len(data[key]) == len(self.weights[i]):
                self.weights[i] = data[key].astype(np.float32).tolist()
        return True

    def total_weights(self):
        """Total number of weight parameters."""
        return sum(len(w) for w in self.weights)

    def memory_mb(self):
        """Approximate memory usage in MB (8 bytes per float)."""
        return sum(len(w) for w in self.weights) * 8 / (1024 * 1024)
