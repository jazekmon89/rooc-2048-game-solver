"""Interactive setup for the Interception driver.

Guides you through installation step by step.
Run as admin: python setup_interception.py
"""

import os
import sys
import ctypes
import subprocess


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


HERE = os.path.dirname(os.path.abspath(__file__))


def check_dll():
    """Check if interception.dll is in the project folder."""
    dll = os.path.join(HERE, 'interception.dll')
    return os.path.exists(dll)


def check_driver():
    """Check if the Interception driver is loaded."""
    # The driver registers as a service. Check if it exists.
    try:
        result = subprocess.run(
            ['sc', 'query', 'keyboard'],
            capture_output=True, text=True
        )
        if 'RUNNING' in result.stdout:
            return True
        # Also check the mouse driver
        result = subprocess.run(
            ['sc', 'query', 'mouse'],
            capture_output=True, text=True
        )
        return 'RUNNING' in result.stdout
    except Exception:
        return False


def check_context():
    """Try to create an Interception context (driver must be loaded)."""
    dll_path = os.path.join(HERE, 'interception.dll')
    if not os.path.exists(dll_path):
        return False, 'DLL not found'
    try:
        dll = ctypes.CDLL(dll_path)
        dll.interception_create_context.restype = ctypes.c_void_p
        ctx = dll.interception_create_context()
        if ctx:
            dll.interception_destroy_context.argtypes = [ctypes.c_void_p]
            dll.interception_destroy_context(ctx)
            return True, 'OK'
        return False, 'create_context returned NULL (driver not loaded?)'
    except Exception as e:
        return False, str(e)


def main():
    print('=' * 60)
    print('  INTERCEPTION DRIVER SETUP')
    print('=' * 60)
    print(f'  Admin: {"YES" if is_admin() else "NO — rerun as admin!"}')
    print()

    # Step 1: Check DLL
    has_dll = check_dll()
    print(f'  [{"OK" if has_dll else "MISSING"}] interception.dll in project folder')

    if not has_dll:
        print()
        print('  STEP 1: Download Interception')
        print('  ─────────────────────────────')
        print('  Go to: https://github.com/oblitum/Interception/releases')
        print('  Download: Interception.zip (from the latest release)')
        print('  Extract it somewhere (e.g., Desktop)')
        print()
        print('  STEP 2: Copy the DLL')
        print('  ────────────────────')
        is_64 = sys.maxsize > 2**32
        arch = 'x64' if is_64 else 'x86'
        print(f'  Your Python is {"64-bit" if is_64 else "32-bit"}, so copy:')
        print(f'    FROM: Interception/library/{arch}/interception.dll')
        print(f'    TO:   {HERE}\\interception.dll')
        print()
        print('  STEP 3: Install the driver')
        print('  ──────────────────────────')
        print('  Open an admin command prompt in the Interception folder and run:')
        print('    install-interception.exe /install')
        print()
        print('  STEP 4: REBOOT your PC')
        print('  ──────────────────────')
        print('  The driver only loads after a reboot.')
        print()
        print('  After completing all steps, run this script again to verify.')
        return

    # Step 2: Check if driver creates a context
    ctx_ok, ctx_msg = check_context()
    print(f'  [{"OK" if ctx_ok else "FAIL"}] Interception context: {ctx_msg}')

    if not ctx_ok:
        print()
        print('  The DLL is present but the driver is not loaded.')
        print('  You need to:')
        print('    1. Install the driver (admin cmd):')
        print('       install-interception.exe /install')
        print('    2. REBOOT your PC')
        print()
        print('  After rebooting, run this script again.')
        return

    # Step 3: Everything looks good — run a test
    print()
    print('  Everything looks good! Running a quick test...')
    print()

    from interception_input import test
    test()

    print()
    resp = input('  Did the game respond? (y/n): ').strip().lower()
    if resp == 'y':
        print()
        print('  SUCCESS! Set INPUT_METHOD = "interception" in config.py')
        print('  Then run: python main.py')
    else:
        print()
        print('  The key was sent but the game didn\'t respond.')
        print('  Try: python interception_input.py')
        print('  Make sure the 2048 mini-game is active in the game window.')


if __name__ == '__main__':
    main()
