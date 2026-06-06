"""Send swipes to the game window.

Input methods, selected via config.INPUT_METHOD:
- "mouse":                pyautogui mouse drag.
- "keyboard":             pyautogui arrow-key press.
- "directinput":          pydirectinput mouse drag via Windows SendInput.
- "directinput_keyboard": pydirectinput arrow-key press via SendInput.
- "postmessage":          Send WM_KEYDOWN/WM_KEYUP directly to the window handle.
                          Works even if the game ignores SendInput.
                          Does NOT require the window to be foreground.

Focus management: most native Windows apps only accept synthetic input when
their window is foreground. Call set_game_window_title(title) once at startup
and swipe() will activate that window before sending input.
"""

import time
import ctypes
import ctypes.wintypes
import pyautogui
import config
from config import SWIPE_DURATION, SWIPE_REACH

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0

user32 = ctypes.windll.user32

_GAME_WINDOW_TITLE = None
_GAME_HWND = None  # cached window handle for PostMessage methods


# ---------- Win32 constants ----------

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001

# Virtual key codes for arrow keys
_VK = {'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27}

# Scan codes for arrow keys (extended keys)
_SCAN = {'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D}


def _make_lparam_down(scan):
    """Build lParam for WM_KEYDOWN with extended key flag."""
    return 1 | (scan << 16) | (1 << 24)


def _make_lparam_up(scan):
    """Build lParam for WM_KEYUP with extended key flag + release bits."""
    return 1 | (scan << 16) | (1 << 24) | (1 << 30) | (1 << 31)


def _make_mouse_lparam(x, y):
    """Pack client-area coordinates into lParam for mouse messages."""
    return (y << 16) | (x & 0xFFFF)


# ---------- window handle ----------

def set_game_window_title(title):
    """Tell swipe() which window to focus before each move."""
    global _GAME_WINDOW_TITLE, _GAME_HWND
    _GAME_WINDOW_TITLE = title
    _GAME_HWND = None  # re-resolve on next use


def set_game_window_hwnd(hwnd, title=""):
    """Directly set the target window handle (avoids ambiguity with duplicate titles)."""
    global _GAME_WINDOW_TITLE, _GAME_HWND
    _GAME_HWND = hwnd
    _GAME_WINDOW_TITLE = title or f"hwnd:{hwnd}"


def _find_hwnd():
    """Find and cache the window handle by title."""
    global _GAME_HWND
    if _GAME_HWND:
        # Verify handle is still valid
        if user32.IsWindow(_GAME_HWND):
            return _GAME_HWND
        _GAME_HWND = None

    if not _GAME_WINDOW_TITLE:
        return None

    try:
        import pygetwindow as gw
    except ImportError:
        return None

    title_lower = _GAME_WINDOW_TITLE.lower()
    matches = [w for w in gw.getAllWindows()
               if w.title and title_lower in w.title.lower() and w.visible]
    if not matches:
        return None

    try:
        _GAME_HWND = matches[0]._hWnd
    except AttributeError:
        return None
    return _GAME_HWND


def _focus_game_window():
    """Bring the game window to foreground. Returns True on success."""
    if not _GAME_WINDOW_TITLE:
        return False
    try:
        import pygetwindow as gw
    except ImportError:
        return False

    title_lower = _GAME_WINDOW_TITLE.lower()
    matches = [w for w in gw.getAllWindows()
               if w.title and title_lower in w.title.lower() and w.visible]
    if not matches:
        return False
    win = matches[0]

    try:
        # Skip if already foreground (avoids unnecessary churn)
        try:
            if user32.GetForegroundWindow() == win._hWnd:
                return True
        except AttributeError:
            pass

        if win.isMinimized:
            win.restore()

        # Windows blocks SetForegroundWindow unless the caller is the active
        # input thread. A phantom Alt keystroke marks our thread as user-active.
        user32.keybd_event(0x12, 0, 0, 0)        # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)   # Alt up
        win.activate()

        # Verify the window actually came to foreground
        for _ in range(5):
            time.sleep(0.05)
            try:
                if user32.GetForegroundWindow() == win._hWnd:
                    return True
            except AttributeError:
                time.sleep(0.08)
                return True  # can't verify, assume success
        return False
    except Exception:
        return False


# ---------- swipe endpoints ----------

def _endpoints(direction, region):
    cx = region['x'] + region['width'] / 2
    cy = region['y'] + region['height'] / 2
    reach = min(region['width'], region['height']) * SWIPE_REACH
    half = reach / 2
    if direction == 'up':
        return (cx, cy + half), (cx, cy - half)
    if direction == 'down':
        return (cx, cy - half), (cx, cy + half)
    if direction == 'left':
        return (cx + half, cy), (cx - half, cy)
    if direction == 'right':
        return (cx - half, cy), (cx + half, cy)
    raise ValueError(f'Unknown direction: {direction}')


# ---------- input methods ----------

def _swipe_mouse(direction, region):
    start, end = _endpoints(direction, region)
    pyautogui.moveTo(start[0], start[1], duration=0.05)
    pyautogui.mouseDown()
    pyautogui.moveTo(end[0], end[1], duration=SWIPE_DURATION)
    pyautogui.mouseUp()


def _swipe_keyboard(direction, _region):
    pyautogui.press(direction)


def _swipe_directinput(direction, region):
    try:
        import pydirectinput
    except ImportError as e:
        raise RuntimeError(
            'pydirectinput not installed. Run: pip install pydirectinput'
        ) from e

    start, end = _endpoints(direction, region)
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])

    pydirectinput.moveTo(sx, sy)
    time.sleep(0.02)
    pydirectinput.mouseDown()
    steps = 12
    step_delay = SWIPE_DURATION / steps
    for i in range(1, steps + 1):
        x = sx + (ex - sx) * i // steps
        y = sy + (ey - sy) * i // steps
        pydirectinput.moveTo(x, y)
        time.sleep(step_delay)
    pydirectinput.mouseUp()


def _swipe_directinput_keyboard(direction, _region):
    """Arrow key press via pydirectinput (SendInput). More reliable for games."""
    try:
        import pydirectinput
    except ImportError as e:
        raise RuntimeError(
            'pydirectinput not installed. Run: pip install pydirectinput'
        ) from e
    pydirectinput.press(direction)


def _swipe_postmessage_key(direction, _region):
    """Send arrow key directly to the window handle via PostMessage.

    This bypasses SendInput entirely — the key event is delivered straight
    to the game's message queue. Works even if the game ignores synthetic
    SendInput, and does NOT require the window to be foreground.
    """
    hwnd = _find_hwnd()
    if not hwnd:
        print('WARNING: postmessage — could not find game window handle.')
        return

    vk = _VK[direction]
    scan = _SCAN[direction]
    lp_down = _make_lparam_down(scan)
    lp_up = _make_lparam_up(scan)

    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lp_down)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, lp_up)


def _swipe_postmessage_mouse(direction, region):
    """Send a mouse drag directly to the window handle via PostMessage.

    Coordinates are converted to client-area relative. Useful if the 2048
    mini-game responds to swipe gestures rather than arrow keys.
    """
    hwnd = _find_hwnd()
    if not hwnd:
        print('WARNING: postmessage_mouse — could not find game window handle.')
        return

    # Get window client area origin to convert screen coords → client coords
    point = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    ox, oy = point.x, point.y

    start, end = _endpoints(direction, region)
    sx, sy = int(start[0]) - ox, int(start[1]) - oy
    ex, ey = int(end[0]) - ox, int(end[1]) - oy

    # Mouse down at start
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _make_mouse_lparam(sx, sy))
    # Drag through intermediate points
    steps = 12
    step_delay = SWIPE_DURATION / steps
    for i in range(1, steps + 1):
        x = sx + (ex - sx) * i // steps
        y = sy + (ey - sy) * i // steps
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, _make_mouse_lparam(x, y))
        time.sleep(step_delay)
    # Mouse up at end
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, _make_mouse_lparam(ex, ey))


def _swipe_interception(direction, _region):
    """Kernel-level key press via the Interception driver.

    Indistinguishable from real hardware input. Requires:
    1. Interception driver installed + reboot
    2. interception.dll in the project folder
    See setup_interception.py for full instructions.
    """
    from interception_input import send_key
    send_key(direction)


# ---------- public API ----------

def _keep_alive(region):
    """Tiny mouse wiggle over the game area to prevent AFK/Battery Saver."""
    cx = int(region['x'] + region['width'] / 2)
    cy = int(region['y'] + region['height'] / 2)
    pyautogui.moveTo(cx, cy)


def swipe(direction, region):
    """Focus the game window, then send a swipe in the given direction."""
    # Mouse wiggle to prevent in-game AFK detection / Battery Saver
    _keep_alive(region)

    # PostMessage methods don't need foreground focus
    method = config.INPUT_METHOD
    if method in ('postmessage', 'postmessage_mouse'):
        pass  # skip focus
    else:
        _focus_game_window()

    if method == 'mouse':
        _swipe_mouse(direction, region)
    elif method == 'keyboard':
        _swipe_keyboard(direction, region)
    elif method == 'directinput':
        _swipe_directinput(direction, region)
    elif method == 'directinput_keyboard':
        _swipe_directinput_keyboard(direction, region)
    elif method == 'postmessage':
        _swipe_postmessage_key(direction, region)
    elif method == 'postmessage_mouse':
        _swipe_postmessage_mouse(direction, region)
    elif method == 'interception':
        _swipe_interception(direction, region)
    else:
        raise ValueError(f'Unknown INPUT_METHOD: {method}')
