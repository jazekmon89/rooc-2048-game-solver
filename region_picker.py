"""Fullscreen transparent overlay to let the user select screen regions.

Run standalone to (re)pick: `python region_picker.py`
Or import the functions from main.py.
"""

import json
import tkinter as tk
from config import REGION_FILE, NEXT_TILE_REGION_FILE


# ---------- generic overlay ----------

def _pick_region_generic(save_file, label_text):
    """Show a transparent fullscreen overlay; user drags to select a rectangle.

    Saves {x, y, width, height} (screen coordinates) to save_file and returns it.
    Returns None if cancelled.
    """
    root = tk.Tk()
    root.attributes('-fullscreen', True)
    root.attributes('-alpha', 0.3)
    root.attributes('-topmost', True)
    root.configure(bg='black')

    canvas = tk.Canvas(root, cursor='cross', bg='black', highlightthickness=0)
    canvas.pack(fill='both', expand=True)

    label = tk.Label(
        root,
        text=label_text,
        bg='white', fg='black', font=('Arial', 13), padx=8, pady=4,
    )
    label.place(relx=0.5, y=24, anchor='n')

    state = {'start': None, 'rect': None, 'result': None}

    def on_press(e):
        state['start'] = (e.x, e.y)
        if state['rect']:
            canvas.delete(state['rect'])
        state['rect'] = canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                outline='lime', width=3)

    def on_drag(e):
        if state['rect'] and state['start']:
            x0, y0 = state['start']
            canvas.coords(state['rect'], x0, y0, e.x, e.y)

    def on_release(e):
        if state['start']:
            x0, y0 = state['start']
            x1, y1 = e.x, e.y
            x, y = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0), abs(y1 - y0)
            if w > 20 and h > 20:
                # Fullscreen window starts at (0, 0); canvas coords == screen coords
                state['result'] = {'x': x, 'y': y, 'width': w, 'height': h}
                root.destroy()

    def on_escape(_e):
        root.destroy()

    canvas.bind('<ButtonPress-1>', on_press)
    canvas.bind('<B1-Motion>', on_drag)
    canvas.bind('<ButtonRelease-1>', on_release)
    root.bind('<Escape>', on_escape)

    root.mainloop()

    if state['result']:
        with open(save_file, 'w') as f:
            json.dump(state['result'], f, indent=2)
        return state['result']
    return None


def _load_region_generic(file_path):
    """Load a previously saved region dict, or None if not set."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# ---------- board region ----------

def pick_region():
    """Show overlay to select the game board region."""
    return _pick_region_generic(
        REGION_FILE,
        'Drag a rectangle around the 2048 BOARD ONLY (not the score/buttons). Esc to cancel.',
    )


def load_region():
    """Load previously saved board region dict, or None if not set."""
    return _load_region_generic(REGION_FILE)


# ---------- next-tile region ----------

def pick_next_tile_region():
    """Show overlay to select the 'next tile' indicator region."""
    return _pick_region_generic(
        NEXT_TILE_REGION_FILE,
        'Drag a rectangle around the NEXT TILE indicator. Esc to cancel/skip.',
    )


def load_next_tile_region():
    """Load previously saved next-tile region dict, or None if not set."""
    return _load_region_generic(NEXT_TILE_REGION_FILE)


if __name__ == '__main__':
    r = pick_region()
    print('Selected board region:', r)
    r2 = pick_next_tile_region()
    print('Selected next-tile region:', r2)
