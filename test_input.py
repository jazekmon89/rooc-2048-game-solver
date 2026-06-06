"""Diagnostic: comprehensive input test for games that block synthetic input.

Run as Administrator:
    python test_input.py
"""

import time
import json
import sys
import ctypes
import ctypes.wintypes

from config import GAME_WINDOW_FILE, SWIPE_DURATION, SWIPE_REACH

user32 = ctypes.windll.user32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
_VK = {'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27}
_SCAN = {'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D}


def load_game_window():
    try:
        with open(GAME_WINDOW_FILE) as f:
            return json.load(f).get('title')
    except FileNotFoundError:
        return None


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def find_hwnd(title):
    import pygetwindow as gw
    title_lower = title.lower()
    matches = [w for w in gw.getAllWindows()
               if w.title and title_lower in w.title.lower() and w.visible]
    if not matches:
        return None
    try:
        return matches[0]._hWnd
    except AttributeError:
        return None


def focus_window(title):
    import pygetwindow as gw
    title_lower = title.lower()
    matches = [w for w in gw.getAllWindows()
               if w.title and title_lower in w.title.lower() and w.visible]
    if not matches:
        return False
    win = matches[0]
    try:
        if win.isMinimized:
            win.restore()
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 0x0002, 0)
        win.activate()
        time.sleep(0.3)
        return True
    except Exception:
        return False


def get_swipe_coords(region, direction='down'):
    cx = region['x'] + region['width'] / 2
    cy = region['y'] + region['height'] / 2
    reach = min(region['width'], region['height']) * SWIPE_REACH
    half = reach / 2
    if direction == 'down':
        return (int(cx), int(cy - half)), (int(cx), int(cy + half))
    if direction == 'up':
        return (int(cx), int(cy + half)), (int(cx), int(cy - half))
    if direction == 'left':
        return (int(cx + half), int(cy)), (int(cx - half), int(cy))
    if direction == 'right':
        return (int(cx - half), int(cy)), (int(cx + half), int(cy))


# ---- Test methods ----

def test_pyautogui_keyboard(title, region):
    """pyautogui.press() — uses SendInput internally."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    focus_window(title)
    time.sleep(0.3)
    pyautogui.press('down')


def test_pyautogui_mouse(title, region):
    """pyautogui mouse drag — physically moves cursor via SendInput."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    focus_window(title)
    time.sleep(0.3)
    start, end = get_swipe_coords(region, 'down')
    pyautogui.moveTo(start[0], start[1], duration=0.1)
    time.sleep(0.05)
    pyautogui.mouseDown()
    time.sleep(0.05)
    pyautogui.moveTo(end[0], end[1], duration=0.15)
    pyautogui.mouseUp()


def test_pydirectinput_keyboard(title, region):
    """pydirectinput.press() — uses SendInput with scan codes."""
    import pydirectinput
    focus_window(title)
    time.sleep(0.3)
    pydirectinput.press('down')


def test_pydirectinput_mouse(title, region):
    """pydirectinput mouse drag — physically moves cursor via SendInput."""
    import pydirectinput
    focus_window(title)
    time.sleep(0.3)
    start, end = get_swipe_coords(region, 'down')
    pydirectinput.moveTo(start[0], start[1])
    time.sleep(0.05)
    pydirectinput.mouseDown()
    steps = 15
    delay = 0.15 / steps
    for i in range(1, steps + 1):
        x = start[0] + (end[0] - start[0]) * i // steps
        y = start[1] + (end[1] - start[1]) * i // steps
        pydirectinput.moveTo(x, y)
        time.sleep(delay)
    pydirectinput.mouseUp()


def test_keybd_event(title, region):
    """Win32 keybd_event() — older API, different codepath from SendInput."""
    focus_window(title)
    time.sleep(0.3)
    vk = _VK['down']
    scan = _SCAN['down']
    user32.keybd_event(vk, scan, 0x0001, 0)              # EXTENDEDKEY down
    time.sleep(0.05)
    user32.keybd_event(vk, scan, 0x0001 | 0x0002, 0)     # EXTENDEDKEY + KEYUP


def test_mouse_event(title, region):
    """Win32 mouse_event() — older API for cursor movement + click."""
    focus_window(title)
    time.sleep(0.3)
    start, end = get_swipe_coords(region, 'down')

    # Move to start position using SetCursorPos
    user32.SetCursorPos(start[0], start[1])
    time.sleep(0.05)

    # Mouse down
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)

    # Drag to end
    steps = 15
    delay = 0.15 / steps
    for i in range(1, steps + 1):
        x = start[0] + (end[0] - start[0]) * i // steps
        y = start[1] + (end[1] - start[1]) * i // steps
        user32.SetCursorPos(x, y)
        time.sleep(delay)

    # Mouse up
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP


def test_sendinput_scancode(title, region):
    """Manual SendInput with SCANCODE flag — ensures hardware-like scan codes."""

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ('wVk', ctypes.wintypes.WORD),
            ('wScan', ctypes.wintypes.WORD),
            ('dwFlags', ctypes.wintypes.DWORD),
            ('time', ctypes.wintypes.DWORD),
            ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ('dx', ctypes.c_long),
            ('dy', ctypes.c_long),
            ('mouseData', ctypes.wintypes.DWORD),
            ('dwFlags', ctypes.wintypes.DWORD),
            ('time', ctypes.wintypes.DWORD),
            ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', ctypes.wintypes.DWORD), ('u', INPUT_UNION)]

    focus_window(title)
    time.sleep(0.3)

    scan = _SCAN['down']

    # Key down: SCANCODE + EXTENDEDKEY
    inp_down = INPUT()
    inp_down.type = 1  # INPUT_KEYBOARD
    inp_down.u.ki.wVk = 0
    inp_down.u.ki.wScan = scan
    inp_down.u.ki.dwFlags = 0x0008 | 0x0001  # SCANCODE | EXTENDEDKEY
    inp_down.u.ki.time = 0
    inp_down.u.ki.dwExtraInfo = None

    user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(0.05)

    # Key up
    inp_up = INPUT()
    inp_up.type = 1
    inp_up.u.ki.wVk = 0
    inp_up.u.ki.wScan = scan
    inp_up.u.ki.dwFlags = 0x0008 | 0x0001 | 0x0002  # SCANCODE | EXTENDEDKEY | KEYUP
    inp_up.u.ki.time = 0
    inp_up.u.ki.dwExtraInfo = None

    user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def test_postmessage_key(title, region):
    """PostMessage WM_KEYDOWN/UP to window handle."""
    hwnd = find_hwnd(title)
    if not hwnd:
        raise RuntimeError('Window not found')
    scan = _SCAN['down']
    vk = _VK['down']
    lp_down = 1 | (scan << 16) | (1 << 24)
    lp_up = 1 | (scan << 16) | (1 << 24) | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lp_down)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lp_up)


def test_interception(title, region):
    """Interception driver — kernel-level input, indistinguishable from hardware."""
    try:
        import interception
    except ImportError:
        raise RuntimeError(
            'interception-python not installed.\n'
            '    1. Install driver: https://github.com/oblitum/Interception\n'
            '       Download, run: install-interception.exe /install\n'
            '       Then REBOOT.\n'
            '    2. pip install interception-python'
        )

    ctx = interception.auto_capture_devices(keyboard=True, mouse=True)
    # Send arrow down key
    interception.key_down(ctx, 'down')
    time.sleep(0.05)
    interception.key_up(ctx, 'down')


TESTS = [
    ('pyautogui keyboard',      'pyautogui.press() — SendInput virtual key',         test_pyautogui_keyboard),
    ('pyautogui mouse drag',    'pyautogui mouse drag — moves real cursor',           test_pyautogui_mouse),
    ('pydirectinput keyboard',  'pydirectinput.press() — SendInput scan code',        test_pydirectinput_keyboard),
    ('pydirectinput mouse drag','pydirectinput mouse drag — moves real cursor',       test_pydirectinput_mouse),
    ('keybd_event',             'Win32 keybd_event() — old API, arrow key',           test_keybd_event),
    ('mouse_event drag',        'Win32 mouse_event() + SetCursorPos — old mouse API', test_mouse_event),
    ('SendInput scancode',      'Manual SendInput with SCANCODE flag',                test_sendinput_scancode),
    ('PostMessage key',         'PostMessage WM_KEYDOWN to window handle',            test_postmessage_key),
    ('Interception driver',     'Kernel-level input injection (needs driver)',         test_interception),
]


def main():
    title = load_game_window()
    if not title:
        print('No game window saved. Run main.py first.')
        sys.exit(1)

    try:
        with open('region.json') as f:
            region = json.load(f)
    except FileNotFoundError:
        print('No region.json found. Run main.py first to pick the region.')
        sys.exit(1)

    print('=' * 60)
    print('  2048 INPUT DIAGNOSTIC v3')
    print('=' * 60)
    print(f'  Script as admin:  {"YES" if is_admin() else "NO — run as admin!"}')
    print(f'  Target window:    "{title}"')
    hwnd = find_hwnd(title)
    print(f'  Window handle:    {"0x{:X}".format(hwnd) if hwnd else "NOT FOUND"}')
    print(f'  Region:           {region}')

    print('\n  IMPORTANT: Before testing, confirm that the 2048 mini-game')
    print('  responds when YOU physically press arrow keys or swipe with')
    print('  your mouse. If it doesn\'t, we need to know that first.')
    print()
    resp = input('  Does physical keyboard/mouse work on the 2048? (y/n/unsure): ').strip().lower()
    if resp == 'n':
        print('\n  The game doesn\'t respond to physical input either.')
        print('  Make sure the 2048 mini-game is active/focused within the game.')
        print('  You may need to click on the 2048 board first.')
        input('  Click on the 2048 board in the game, then press Enter here...')

    print('\n' + '=' * 60)
    print('  TESTING EACH METHOD — sends a DOWN action each time.')
    print('  Watch the game board after each test.')
    print('=' * 60)

    for name, desc, fn in TESTS:
        print(f'\n  [{name}]')
        print(f'  {desc}')
        input('  Press Enter to test...')
        try:
            fn(title, region)
            print('  -> Sent successfully.')
        except Exception as e:
            print(f'  -> ERROR: {e}')
            continue

        time.sleep(0.3)
        moved = input('  Did the board move? (y/n): ').strip().lower()
        if moved == 'y':
            print(f'\n  *** SUCCESS: "{name}" works! ***')
            print(f'  Update INPUT_METHOD in config.py to use this method.')
            return

    print('\n' + '=' * 60)
    print('  NOTHING WORKED.')
    print()
    print('  Recommended: Install the Interception driver.')
    print('  It injects input at the kernel level — games cannot')
    print('  distinguish it from real hardware.')
    print()
    print('  Steps:')
    print('    1. Download from: https://github.com/oblitum/Interception')
    print('       (go to Releases, download Interception.zip)')
    print('    2. Extract, open admin command prompt in that folder, run:')
    print('       install-interception.exe /install')
    print('    3. REBOOT your PC (required for driver to load)')
    print('    4. pip install interception-python')
    print('    5. Run this test again — "Interception driver" should work.')
    print('=' * 60)


if __name__ == '__main__':
    main()
