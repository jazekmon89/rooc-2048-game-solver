"""Test with manual focus: you switch to the game, we send input after a countdown.

This eliminates focus-switching as a variable. If this works, the problem was
focus management, not input blocking.

Run as admin: python test_focus.py
"""

import time
import sys
import json
import ctypes

from config import GAME_WINDOW_FILE, SWIPE_REACH, SWIPE_DURATION

user32 = ctypes.windll.user32

_VK = {'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27}
_SCAN = {'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D}


def load():
    with open(GAME_WINDOW_FILE) as f:
        title = json.load(f)['title']
    with open('region.json') as f:
        region = json.load(f)
    return title, region


def countdown(seconds, msg):
    print(f'\n  {msg}')
    for i in range(seconds, 0, -1):
        print(f'  Sending in {i}...', end='\r', flush=True)
        time.sleep(1)
    print(f'  Sending NOW!        ')


def check_foreground(title):
    """Check what window is actually in the foreground."""
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    fg_title = buf.value
    is_game = title.lower() in fg_title.lower() if fg_title else False
    return fg_title, is_game


def test_keyboard_sendinput():
    """pydirectinput keyboard — the simplest SendInput test."""
    import pydirectinput
    pydirectinput.press('down')


def test_keyboard_keybd_event():
    """keybd_event with arrow key."""
    vk = _VK['down']
    scan = _SCAN['down']
    user32.keybd_event(vk, scan, 0x0001, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, scan, 0x0001 | 0x0002, 0)


def test_mouse_drag(region):
    """Physical mouse drag using SetCursorPos + mouse_event."""
    cx = int(region['x'] + region['width'] / 2)
    cy = int(region['y'] + region['height'] / 2)
    reach = int(min(region['width'], region['height']) * SWIPE_REACH / 2)

    # First CLICK the center of the board to make sure it's selected
    user32.SetCursorPos(cx, cy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.3)

    # Now do the swipe (down)
    sy = cy - reach
    ey = cy + reach
    user32.SetCursorPos(cx, sy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    steps = 15
    delay = SWIPE_DURATION / steps
    for i in range(1, steps + 1):
        y = sy + (ey - sy) * i // steps
        user32.SetCursorPos(cx, y)
        time.sleep(delay)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up


def test_click_then_key(region):
    """Click the board center first (to select the mini-game), then arrow key."""
    cx = int(region['x'] + region['width'] / 2)
    cy = int(region['y'] + region['height'] / 2)

    # Click to ensure the 2048 mini-game is selected within the game
    user32.SetCursorPos(cx, cy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.3)

    # Now send arrow key
    import pydirectinput
    pydirectinput.press('down')


def main():
    title, region = load()

    print('=' * 60)
    print('  MANUAL FOCUS TEST')
    print('=' * 60)
    print(f'  Target: "{title}"')
    print(f'  Region: {region}')
    print()
    print('  This test gives you time to switch to the game yourself.')
    print('  After you press Enter, you have 5 seconds to:')
    print('    1. Click on the game window')
    print('    2. Click on the 2048 board')
    print('  Then input will be sent.')

    # ---- Test 1: Keyboard with manual focus ----
    print('\n' + '-' * 60)
    print('  TEST 1: Arrow key (you focus the game first)')
    input('  Press Enter, then switch to the game and click the 2048 board...')
    countdown(5, 'Switch to the game NOW! Click on the 2048 board!')

    fg_title, is_game = check_foreground(title)
    print(f'  Foreground window: "{fg_title}" {"(GAME)" if is_game else "(NOT GAME!)"}')

    test_keyboard_sendinput()
    print('  Sent: pydirectinput arrow DOWN')
    time.sleep(0.5)

    # Quick follow-up with keybd_event
    test_keyboard_keybd_event()
    print('  Sent: keybd_event arrow DOWN')

    moved = input('\n  Did the board move? (y/n): ').strip().lower()
    if moved == 'y':
        print('\n  SUCCESS! The issue was focus management.')
        print('  The game needs to be properly focused + the 2048 board clicked.')
        return

    # ---- Test 2: Click board center then arrow key ----
    print('\n' + '-' * 60)
    print('  TEST 2: Click board center + arrow key (automated)')
    print('  This will move your mouse to the board, click, then press DOWN.')
    input('  Press Enter, then switch to the game...')
    countdown(5, 'Switch to the game NOW!')

    fg_title, is_game = check_foreground(title)
    print(f'  Foreground window: "{fg_title}" {"(GAME)" if is_game else "(NOT GAME!)"}')

    test_click_then_key(region)
    print('  Sent: click center + pydirectinput arrow DOWN')

    moved = input('\n  Did the board move? (y/n): ').strip().lower()
    if moved == 'y':
        print('\n  SUCCESS! The 2048 needs a click first to "select" it.')
        print('  We can add an auto-click before each move.')
        return

    # ---- Test 3: Mouse drag with click ----
    print('\n' + '-' * 60)
    print('  TEST 3: Mouse swipe (click center, then drag down)')
    input('  Press Enter, then switch to the game...')
    countdown(5, 'Switch to the game NOW!')

    fg_title, is_game = check_foreground(title)
    print(f'  Foreground window: "{fg_title}" {"(GAME)" if is_game else "(NOT GAME!)"}')

    test_mouse_drag(region)
    print('  Sent: click center + mouse drag DOWN')

    moved = input('\n  Did the board move? (y/n): ').strip().lower()
    if moved == 'y':
        print('\n  SUCCESS! The game responds to mouse swipes.')
        print('  Use INPUT_METHOD = "mouse" or "directinput" with click-first logic.')
        return

    # ---- Nothing worked ----
    print('\n' + '=' * 60)
    print('  STILL NOTHING.')
    print()
    print('  Even with the game manually focused, synthetic input is blocked.')
    print('  This game uses low-level input reading (Raw Input / DirectInput)')
    print('  that filters out synthetic events.')
    print()
    print('  The ONLY remaining option is the Interception driver:')
    print('    1. Download: https://github.com/oblitum/Interception/releases')
    print('    2. Admin cmd: install-interception.exe /install')
    print('    3. REBOOT')
    print('    4. pip install interception-python')
    print('    5. Set INPUT_METHOD = "interception" in config.py')
    print('=' * 60)


if __name__ == '__main__':
    main()
