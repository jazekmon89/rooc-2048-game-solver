"""Main entry point: orchestrates the screenshot → parse → solve → swipe loop."""

import time
import sys
import json

from config import LOOP_DELAY, POST_SWIPE_PAUSE, GAME_WINDOW_FILE, UNKNOWN_TILE_THRESHOLD
from region_picker import pick_region, load_region, pick_next_tile_region, load_next_tile_region
from vision import (
    parse_board, calibrate_interactive, load_references,
    wait_for_stable_board, recalibrate_unknowns, parse_next_tile,
)
from solver import best_move, is_game_over
from actions import swipe, set_game_window_title


# ---------- console helpers ----------

def print_board(b):
    sep = '+' + ('------+' * len(b))
    print(sep)
    for row in b:
        cells = [f'{v:>4}' if v > 0 else '   .' for v in row]
        print('| ' + ' | '.join(cells) + ' |')
        print(sep)


def yes_no(prompt, default='y'):
    suffix = '[Y/n]' if default == 'y' else '[y/N]'
    ans = input(f'{prompt} {suffix}: ').strip().lower()
    if not ans:
        return default == 'y'
    return ans.startswith('y')


# ---------- region ----------

def ensure_region():
    region = load_region()
    if region is not None:
        print(f'Loaded region: x={region["x"]} y={region["y"]} '
              f'w={region["width"]} h={region["height"]}')
        if not yes_no('Use this region?'):
            region = None
    if region is None:
        input('\nMake the game visible on screen, then press Enter to pick the region.')
        region = pick_region()
        if region is None:
            print('No region selected. Exiting.')
            sys.exit(0)
    return region


# ---------- game window picker ----------

def save_game_window(title):
    with open(GAME_WINDOW_FILE, 'w') as f:
        json.dump({'title': title}, f, indent=2)


def load_game_window():
    try:
        with open(GAME_WINDOW_FILE) as f:
            return json.load(f).get('title')
    except FileNotFoundError:
        return None


def list_visible_windows():
    try:
        import pygetwindow as gw
    except ImportError:
        return None
    windows = []
    for w in gw.getAllWindows():
        if not w.visible or w.width < 100 or w.height < 100:
            continue
        title = (w.title or '').strip()
        if not title:
            continue
        windows.append(w)
    return windows


def pick_game_window_interactive():
    """Show a numbered list. Returns chosen title, or '' to skip focusing."""
    windows = list_visible_windows()
    if windows is None:
        print('ERROR: pygetwindow not installed. Run: pip install pygetwindow')
        return ''
    if not windows:
        print('No visible windows found.')
        return ''

    print('\nVisible windows:')
    print('  [ 0]  Skip — I will keep the game focused manually')
    for i, w in enumerate(windows, 1):
        title = w.title[:60]
        print(f'  [{i:>2}]  {w.width:>5}x{w.height:<5}  "{title}"')

    while True:
        raw = input('\nEnter the number of your game window: ').strip()
        if raw == '0':
            return ''
        try:
            idx = int(raw)
            if 1 <= idx <= len(windows):
                return windows[idx - 1].title
        except ValueError:
            pass
        print(f'  Please enter a number between 0 and {len(windows)}.')


def ensure_game_window():
    """Resolve which window swipes will be focused to."""
    saved = load_game_window()
    if saved:
        print(f'Saved game window: "{saved}"')
        if yes_no('Use this window?'):
            set_game_window_title(saved)
            return
    title = pick_game_window_interactive()
    if title:
        save_game_window(title)
        set_game_window_title(title)
        print(f'Will focus "{title}" before each swipe.')
    else:
        print('Focus management disabled. Keep the game window in front manually.')


# ---------- next-tile region ----------

def ensure_next_tile_region():
    """Optionally load or pick the next-tile indicator region."""
    region = load_next_tile_region()
    if region is not None:
        print(f'Loaded next-tile region: x={region["x"]} y={region["y"]} '
              f'w={region["width"]} h={region["height"]}')
        if yes_no('Use this next-tile region?'):
            return region
    if not yes_no('Set up next-tile detection? (improves solver accuracy)'):
        print('Next-tile detection disabled. Solver will use 90%/10% probabilities.')
        return None
    input('\nMake sure the next-tile indicator is visible on screen, then press Enter.')
    region = pick_next_tile_region()
    if region is None:
        print('No next-tile region selected. Feature disabled.')
    return region


# ---------- references ----------

def ensure_references(region):
    refs = load_references()
    if refs:
        print(f'Loaded {len(refs)} tile references: {sorted(refs.keys())}')
        if yes_no('Recalibrate?', default='n'):
            refs = calibrate_interactive(region)
    else:
        print('No tile references found. Starting calibration.')
        refs = calibrate_interactive(region)
    return refs


# ---------- main loop ----------

def main():
    print('=== 2048 Auto-Solver ===\n')
    region = ensure_region()
    ensure_game_window()
    references = ensure_references(region)
    next_tile_region = ensure_next_tile_region()

    print('\nStarting in 3 seconds.')
    print('Emergency stop: slam the mouse into a screen corner, or press Ctrl+C.\n')
    time.sleep(3)

    move_count = 0
    last_board = None
    stuck_count = 0

    try:
        while True:
            # Wait for animation to finish, then read the stable board
            board, unknowns = wait_for_stable_board(region, references)

            # Auto-recalibrate if too many cells are unrecognized
            if len(unknowns) >= UNKNOWN_TILE_THRESHOLD:
                print(f'\n{len(unknowns)} unrecognized cell(s) detected.')
                references = recalibrate_unknowns(region, references, unknowns)
                # Re-read after recalibration
                board, unknowns = parse_board(region, references)

            if board == last_board:
                stuck_count += 1
                if stuck_count >= 3:
                    print('Board has not changed for 3 cycles. Pausing.')
                    if not yes_no('Continue trying?'):
                        break
                    stuck_count = 0
            else:
                stuck_count = 0

            print(f'\n--- Move {move_count + 1} ---')
            print_board(board)
            # Capture the known next tile (if configured)
            next_tile = parse_next_tile(next_tile_region, references)

            if unknowns:
                print(f'  ({len(unknowns)} cell(s) unrecognized — shown as 0)')
            if next_tile is not None:
                print(f'  Next tile: {next_tile}')
            elif next_tile_region is not None:
                print(f'  Next tile: unknown (classification failed)')

            if is_game_over(board):
                print('Game over: no legal moves remain.')
                break

            move = best_move(board, next_tile=next_tile)
            if move is None:
                print('Solver returned no move. Stopping.')
                break

            print(f'Best move: {move.upper()}')
            swipe(move, region)
            last_board = board
            move_count += 1

            time.sleep(POST_SWIPE_PAUSE + LOOP_DELAY)

    except KeyboardInterrupt:
        print(f'\nStopped by user after {move_count} moves.')


if __name__ == '__main__':
    import sys
    if '--cli' in sys.argv:
        main()
    else:
        from gui import run_gui
        run_gui()