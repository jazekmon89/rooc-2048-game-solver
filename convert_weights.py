"""Convert N-tuple weights between C binary format and Python .npz format.

Usage:
    python convert_weights.py ntuple_weights.bin ntuple_weights.npz   # C -> Python
    python convert_weights.py ntuple_weights.npz ntuple_weights.bin   # Python -> C
"""

import sys
import struct
import numpy as np

MAGIC = 0x4E545550  # "NTUP"


def bin_to_npz(bin_path, npz_path):
    """Convert C binary weights to Python .npz format."""
    with open(bin_path, 'rb') as f:
        magic, n_tables = struct.unpack('ii', f.read(8))
        if magic != MAGIC:
            print(f'ERROR: Invalid magic number in {bin_path}')
            sys.exit(1)

        data = {'n_tables': np.array([n_tables])}
        total_weights = 0
        for i in range(n_tables):
            size = struct.unpack('i', f.read(4))[0]
            weights = np.frombuffer(f.read(size * 4), dtype=np.float32).copy()
            data[f'w{i}'] = weights
            total_weights += size

    np.savez_compressed(npz_path, **data)
    print(f'Converted {bin_path} -> {npz_path}')
    print(f'  {n_tables} tables, {total_weights:,} weights')


def npz_to_bin(npz_path, bin_path):
    """Convert Python .npz weights to C binary format."""
    data = np.load(npz_path)
    n_tables = int(data['n_tables'][0])

    with open(bin_path, 'wb') as f:
        f.write(struct.pack('ii', MAGIC, n_tables))
        total_weights = 0
        for i in range(n_tables):
            w = data[f'w{i}'].astype(np.float32)
            f.write(struct.pack('i', len(w)))
            f.write(w.tobytes())
            total_weights += len(w)

    print(f'Converted {npz_path} -> {bin_path}')
    print(f'  {n_tables} tables, {total_weights:,} weights')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src, dst = sys.argv[1], sys.argv[2]

    if src.endswith('.bin') and dst.endswith('.npz'):
        bin_to_npz(src, dst)
    elif src.endswith('.npz') and dst.endswith('.bin'):
        npz_to_bin(src, dst)
    else:
        print('ERROR: Specify .bin and .npz files (order determines direction)')
        print(__doc__)
        sys.exit(1)
