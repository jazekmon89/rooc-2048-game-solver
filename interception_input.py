"""Interception driver wrapper — kernel-level keyboard input injection.

Uses ctypes to call interception.dll directly (no pip package needed).

Setup:
  1. Download Interception from https://github.com/oblitum/Interception/releases
  2. Run as admin: install-interception.exe /install
  3. REBOOT (required for driver to load)
  4. Copy library/x64/interception.dll into this project folder
"""

import ctypes
import time
import os
import sys


class InterceptionKeyStroke(ctypes.Structure):
    _fields_ = [
        ('code', ctypes.c_ushort),
        ('state', ctypes.c_ushort),
        ('information', ctypes.c_uint),
    ]


# Arrow key scan codes
SCAN = {
    'up': 0x48,
    'down': 0x50,
    'left': 0x4B,
    'right': 0x4D,
}

# Key state flags
KEY_DOWN = 0x00
KEY_UP = 0x01
KEY_E0 = 0x02    # Extended key flag (required for arrow keys)

_dll = None
_ctx = None
_device = 1  # keyboard device (1 = first keyboard)


def _find_dll():
    """Search for interception.dll in common locations."""
    here = os.path.dirname(os.path.abspath(__file__))
    is_64bit = sys.maxsize > 2**32

    candidates = [
        os.path.join(here, 'interception.dll'),
        os.path.join(here, 'lib', 'interception.dll'),
        # From Interception release zip structure
        os.path.join(here, 'library', 'x64' if is_64bit else 'x86', 'interception.dll'),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def init():
    """Load the DLL and create an Interception context."""
    global _dll, _ctx

    if _ctx is not None:
        return True

    dll_path = _find_dll()
    if dll_path is None:
        raise FileNotFoundError(
            'interception.dll not found!\n'
            'Copy it from the Interception download:\n'
            '  library/x64/interception.dll  →  this project folder\n'
            'See setup_interception.py for full instructions.'
        )

    _dll = ctypes.CDLL(dll_path)

    # Set up function signatures
    _dll.interception_create_context.restype = ctypes.c_void_p
    _dll.interception_create_context.argtypes = []

    _dll.interception_destroy_context.restype = None
    _dll.interception_destroy_context.argtypes = [ctypes.c_void_p]

    _dll.interception_send.restype = ctypes.c_int
    _dll.interception_send.argtypes = [
        ctypes.c_void_p,    # context
        ctypes.c_int,       # device
        ctypes.c_void_p,    # stroke pointer
        ctypes.c_uint,      # nstroke
    ]

    _ctx = _dll.interception_create_context()
    if not _ctx:
        raise RuntimeError(
            'Failed to create Interception context.\n'
            'Is the Interception driver installed? Did you reboot after installing?'
        )

    return True


def send_key(direction, hold=0.05):
    """Send an arrow key press + release to the first keyboard device.

    This is injected at the kernel driver level — the OS and all applications
    see it as genuine hardware input.
    """
    init()

    scan = SCAN[direction]

    # Key down (E0 flag for extended keys like arrows)
    stroke = InterceptionKeyStroke(code=scan, state=KEY_DOWN | KEY_E0, information=0)
    sent = _dll.interception_send(_ctx, _device, ctypes.byref(stroke), 1)
    if sent != 1:
        print(f'WARNING: interception_send key_down returned {sent}')

    time.sleep(hold)

    # Key up
    stroke.state = KEY_UP | KEY_E0
    _dll.interception_send(_ctx, _device, ctypes.byref(stroke), 1)


def cleanup():
    """Destroy the Interception context."""
    global _ctx
    if _dll is not None and _ctx is not None:
        _dll.interception_destroy_context(_ctx)
        _ctx = None


def test():
    """Quick self-test: send a down arrow key."""
    print('Interception driver test')
    print(f'  DLL: {_find_dll() or "NOT FOUND"}')

    try:
        init()
        print(f'  Context created: OK')
    except Exception as e:
        print(f'  ERROR: {e}')
        return False

    print('  Sending DOWN arrow in 3 seconds...')
    print('  Switch to the game NOW!')
    for i in range(3, 0, -1):
        print(f'  {i}...', flush=True)
        time.sleep(1)

    send_key('down')
    print('  Sent! Did the game respond?')
    cleanup()
    return True


if __name__ == '__main__':
    test()
