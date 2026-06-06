"""2048 Auto-Solver GUI built with customtkinter."""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import queue
import time
import json
import math
from dataclasses import dataclass
from datetime import datetime

import config
from region_picker import load_region, load_next_tile_region
from config import (
    REGION_FILE, NEXT_TILE_REGION_FILE, GAME_WINDOW_FILE,
    UNKNOWN_TILE_THRESHOLD,
)
from vision import (
    capture, split_into_cells, cell_signature, load_references,
    save_references, update_tolerance, parse_board,
    wait_for_stable_board, parse_next_tile,
)
from solver import best_move, is_game_over
from actions import swipe, set_game_window_title, set_game_window_hwnd

# ── Display colors for the board canvas ──────────────────────────────
TILE_COLORS = {
    0:     "#cdc1b4",
    2:     "#eee4da", 4:     "#ede0c8",
    8:     "#f2b179", 16:    "#f59563",
    32:    "#f67c5f", 64:    "#f65e3b",
    128:   "#edcf72", 256:   "#edcc61",
    512:   "#edc850", 1024:  "#edc53f",
    2048:  "#edc22e", 4096:  "#3e3933",
    8192:  "#3c3a32", 16384: "#3c3a32",
    32768: "#3c3a32", 65536: "#3c3a32",
}
_TEXT_LIGHT = "#776e65"
_TEXT_DARK = "#f9f6f2"

SOLVER_MODES = ["ntuple", "expectimax", "mcts"]
INPUT_METHODS = [
    "interception", "postmessage", "postmessage_mouse",
    "keyboard", "directinput", "directinput_keyboard", "mouse",
]

# ── Thread-safe message types ────────────────────────────────────────

@dataclass
class BoardUpdate:
    board: list
    unknowns: list
    move: str
    next_tile: object
    move_count: int

@dataclass
class LogMsg:
    text: str

@dataclass
class SolverStopped:
    reason: str


# ── Background solver thread ─────────────────────────────────────────

class SolverThread:
    def __init__(self, region, references, next_tile_region, msg_queue, stop_event):
        self._region = region
        self._references = references
        self._next_tile_region = next_tile_region
        self._queue = msg_queue
        self._stop = stop_event
        self._thread = None
        self._move_count = 0
        self._last_board = None
        self._stuck_count = 0

    def start(self):
        self._stop.clear()
        self._move_count = 0
        self._last_board = None
        self._stuck_count = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def references(self):
        return self._references

    @references.setter
    def references(self, refs):
        self._references = refs

    def _emit(self, msg):
        self._queue.put(msg)

    def _run(self):
        try:
            self._emit(LogMsg("Solver loop running..."))
            while not self._stop.is_set():
                board, unknowns = wait_for_stable_board(
                    self._region, self._references
                )
                if self._stop.is_set():
                    break

                if len(unknowns) >= UNKNOWN_TILE_THRESHOLD:
                    self._emit(LogMsg(
                        f"{len(unknowns)} unrecognized cell(s) - consider recalibrating"
                    ))

                # Stuck detection
                if board == self._last_board:
                    self._stuck_count += 1
                    if self._stuck_count >= 5:
                        self._emit(SolverStopped("Board unchanged for 5 cycles"))
                        return
                else:
                    self._stuck_count = 0

                next_tile = None
                if self._next_tile_region:
                    next_tile = parse_next_tile(
                        self._next_tile_region, self._references
                    )

                if is_game_over(board):
                    self._move_count += 1
                    self._emit(BoardUpdate(board, unknowns, "", next_tile, self._move_count))
                    self._emit(SolverStopped("Game over"))
                    return

                move = best_move(board, next_tile=next_tile)
                if move is None:
                    self._emit(SolverStopped("No valid move"))
                    return

                swipe(move, self._region)
                self._move_count += 1
                self._last_board = board

                self._emit(BoardUpdate(board, unknowns, move, next_tile, self._move_count))

                # Sleep in small chunks so stop is responsive
                delay = config.POST_SWIPE_PAUSE + config.LOOP_DELAY
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    if self._stop.is_set():
                        return
                    time.sleep(0.05)

        except Exception as e:
            self._emit(LogMsg(f"ERROR: {e}"))
            self._emit(SolverStopped(f"Error: {e}"))


# ── Calibration dialog ───────────────────────────────────────────────

class CalibrationDialog(ctk.CTkToplevel):
    def __init__(self, parent, region, on_complete):
        super().__init__(parent)
        self.title("Tile Calibration")
        self.geometry("520x520")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._region = region
        self._on_complete = on_complete
        self._entries = []
        self._photo_refs = []

        # Capture the board
        self._img = capture(region)
        self._cells = split_into_cells(self._img)

        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Enter tile values (0 = empty):",
                     font=("", 14, "bold")).pack(pady=(12, 8))

        grid = ctk.CTkFrame(self)
        grid.pack(padx=16, pady=4)

        from PIL import ImageTk

        for r in range(4):
            row_entries = []
            for c in range(4):
                cell_frame = ctk.CTkFrame(grid, fg_color="transparent")
                cell_frame.grid(row=r, column=c, padx=6, pady=6)

                cell_img = self._cells[r][c].resize((55, 55))
                photo = ImageTk.PhotoImage(cell_img)
                self._photo_refs.append(photo)
                tk.Label(cell_frame, image=photo, bd=1, relief="solid").pack()

                var = ctk.StringVar(value="0")
                entry = ctk.CTkEntry(cell_frame, textvariable=var, width=60,
                                     justify="center")
                entry.pack(pady=(4, 0))
                row_entries.append(var)
            self._entries.append(row_entries)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=12)
        ctk.CTkButton(btn_frame, text="Save", width=100,
                      command=self._on_save).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color="#666", command=self.destroy).pack(side="left", padx=8)

    def _on_save(self):
        refs = load_references()
        for r in range(4):
            for c in range(4):
                raw = self._entries[r][c].get().strip()
                if not raw:
                    continue
                try:
                    val = int(raw)
                except ValueError:
                    messagebox.showerror("Error",
                                         f"Cell ({r+1},{c+1}): not a valid number",
                                         parent=self)
                    return
                if val == 0:
                    continue
                sig = cell_signature(self._cells[r][c])
                if sig is not None:
                    refs[val] = sig

        save_references(refs)
        update_tolerance(refs)
        self._on_complete(refs)
        self.destroy()


# ── Game window picker dialog ────────────────────────────────────────

class _HighlightBorder:
    """Four thin topmost windows forming a colored rectangle around a target window."""

    _THICKNESS = 4
    _COLOR = "#00ff00"

    def __init__(self):
        self._bars = []

    def show(self, x, y, w, h):
        """Show (or reposition) the highlight around the given screen rect."""
        self.hide()
        t = self._THICKNESS
        rects = [
            (x - t, y - t, w + 2 * t, t),       # top
            (x - t, y + h, w + 2 * t, t),        # bottom
            (x - t, y, t, h),                     # left
            (x + w, y, t, h),                     # right
        ]
        for rx, ry, rw, rh in rects:
            bar = tk.Toplevel()
            bar.overrideredirect(True)
            bar.attributes("-topmost", True)
            bar.configure(bg=self._COLOR)
            bar.geometry(f"{rw}x{rh}+{rx}+{ry}")
            # Make click-through on Windows
            try:
                import ctypes
                hwnd = int(bar.frame(), 16)
                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, -20, ex_style | 0x80000 | 0x20  # WS_EX_LAYERED | WS_EX_TRANSPARENT
                )
            except Exception:
                pass
            self._bars.append(bar)

    def hide(self):
        for bar in self._bars:
            try:
                bar.destroy()
            except Exception:
                pass
        self._bars = []


class GameWindowDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("Select Game Window")
        self.geometry("520x420")
        self.transient(parent)
        self.grab_set()

        self._on_select = on_select
        self._selected = ctk.StringVar(value="")
        self._windows = {}  # key (str index) -> {title, hwnd, x, y, w, h}
        self._highlight = _HighlightBorder()

        ctk.CTkLabel(self, text="Select the game window:",
                     font=("", 14, "bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Hover a radio button to highlight the window on screen.",
                     font=("", 11), text_color="#aaa").pack()

        scroll = ctk.CTkScrollableFrame(self, height=250)
        scroll.pack(padx=16, pady=(6, 0), fill="both", expand=True)

        try:
            import pygetwindow as gw
            idx = 0
            for w in gw.getAllWindows():
                if not w.visible or w.width < 100 or w.height < 100:
                    continue
                title = (w.title or "").strip()
                if not title:
                    continue
                key = str(idx)
                try:
                    hwnd = w._hWnd
                except AttributeError:
                    hwnd = None
                self._windows[key] = {
                    "title": title, "hwnd": hwnd,
                    "x": w.left, "y": w.top, "w": w.width, "h": w.height,
                }
                rb = ctk.CTkRadioButton(
                    scroll, text=f"{w.width}x{w.height}  {title[:50]}",
                    variable=self._selected, value=key,
                )
                rb.pack(anchor="w", pady=2)
                # Bind hover events for highlight
                rb.bind("<Enter>", lambda e, k=key: self._on_hover(k))
                rb.bind("<Leave>", lambda e: self._highlight.hide())
                idx += 1
        except ImportError:
            ctk.CTkLabel(scroll,
                         text="pygetwindow not installed.\npip install pygetwindow").pack()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Select", width=100,
                      command=self._on_ok).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="Skip", width=100, fg_color="#666",
                      command=lambda: self._finish(None)).pack(side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

    def _on_hover(self, key):
        info = self._windows.get(key)
        if info:
            self._highlight.show(info["x"], info["y"], info["w"], info["h"])

    def _on_ok(self):
        key = self._selected.get()
        info = self._windows.get(key)
        if info:
            self._finish(info)
        else:
            self._finish(None)

    def _finish(self, info):
        self._highlight.hide()
        if info:
            self._on_select(info)
        else:
            self._on_select(None)
        self.destroy()


# ── Region picker overlay (Toplevel, not second Tk) ──────────────────

def _pick_region_overlay(parent, save_file, label_text):
    """Full-screen overlay as a Toplevel of the CTk root."""
    parent.withdraw()
    time.sleep(0.2)

    overlay = tk.Toplevel()
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-alpha", 0.3)
    overlay.attributes("-topmost", True)
    overlay.configure(bg="black")

    canvas = tk.Canvas(overlay, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    label = tk.Label(overlay, text=label_text,
                     bg="white", fg="black", font=("Arial", 13), padx=8, pady=4)
    label.place(relx=0.5, y=24, anchor="n")

    state = {"start": None, "rect": None, "result": None}

    def on_press(e):
        state["start"] = (e.x, e.y)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                outline="lime", width=3)

    def on_drag(e):
        if state["rect"] and state["start"]:
            x0, y0 = state["start"]
            canvas.coords(state["rect"], x0, y0, e.x, e.y)

    def on_release(e):
        if state["start"]:
            x0, y0 = state["start"]
            x1, y1 = e.x, e.y
            x, y = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0), abs(y1 - y0)
            if w > 20 and h > 20:
                state["result"] = {"x": x, "y": y, "width": w, "height": h}
                overlay.destroy()

    def on_escape(_e):
        overlay.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>", on_escape)

    overlay.wait_window()
    parent.deiconify()

    if state["result"]:
        with open(save_file, "w") as f:
            json.dump(state["result"], f, indent=2)
        return state["result"]
    return None


# ── Main application ─────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("2048 Auto-Solver")
        self.geometry("900x680")
        self.minsize(780, 580)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # State
        self._region = load_region()
        self._next_tile_region = load_next_tile_region()
        self._references = load_references()
        self._game_window_title = self._load_game_window()
        if self._game_window_title:
            set_game_window_title(self._game_window_title)

        self._msg_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._solver = None
        self._running = False
        self._move_count = 0
        self._max_tile = 0

        # Build UI
        self._build_sidebar()
        self._build_main_area()
        self._update_status_indicators()

        # Queue polling
        self.after(50, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Sidebar ──────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=220)
        sb.pack(side="left", fill="y", padx=(10, 0), pady=10)
        sb.pack_propagate(False)

        # Setup
        ctk.CTkLabel(sb, text="SETUP", font=("", 14, "bold")).pack(pady=(12, 6))
        self._btn_region = ctk.CTkButton(sb, text="Pick Region",
                                         command=self._on_pick_region)
        self._btn_region.pack(fill="x", padx=10, pady=3)
        self._btn_window = ctk.CTkButton(sb, text="Pick Window",
                                         command=self._on_pick_game_window)
        self._btn_window.pack(fill="x", padx=10, pady=3)
        self._btn_calibrate = ctk.CTkButton(sb, text="Calibrate",
                                            command=self._on_calibrate)
        self._btn_calibrate.pack(fill="x", padx=10, pady=3)
        self._btn_next_tile = ctk.CTkButton(sb, text="Next Tile Region",
                                            command=self._on_pick_next_tile)
        self._btn_next_tile.pack(fill="x", padx=10, pady=3)

        # Settings
        ctk.CTkLabel(sb, text="SETTINGS", font=("", 14, "bold")).pack(pady=(20, 6))

        ctk.CTkLabel(sb, text="Solver:", anchor="w").pack(anchor="w", padx=12)
        self._solver_var = ctk.StringVar(value=config.SOLVER_MODE)
        ctk.CTkOptionMenu(sb, values=SOLVER_MODES, variable=self._solver_var,
                          command=self._on_solver_change).pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(sb, text="Input:", anchor="w").pack(anchor="w", padx=12)
        self._input_var = ctk.StringVar(value=config.INPUT_METHOD)
        ctk.CTkOptionMenu(sb, values=INPUT_METHODS, variable=self._input_var,
                          command=self._on_input_change).pack(fill="x", padx=10, pady=3)

        ctk.CTkLabel(sb, text="Search Depth:", anchor="w").pack(anchor="w", padx=12)
        depth_row = ctk.CTkFrame(sb, fg_color="transparent")
        depth_row.pack(fill="x", padx=10, pady=3)
        self._depth_slider = ctk.CTkSlider(depth_row, from_=1, to=10,
                                           number_of_steps=9,
                                           command=self._on_depth_change)
        self._depth_slider.set(config.SEARCH_DEPTH)
        self._depth_slider.pack(side="left", fill="x", expand=True)
        self._depth_label = ctk.CTkLabel(depth_row, text=str(config.SEARCH_DEPTH),
                                         width=24)
        self._depth_label.pack(side="right", padx=(6, 0))

        # Start / Stop
        self._btn_start = ctk.CTkButton(
            sb, text="START", font=("", 16, "bold"), height=50,
            fg_color="#2d8a4e", hover_color="#25733f",
            command=self._on_start_stop,
        )
        self._btn_start.pack(fill="x", padx=10, pady=(24, 10))

        # Status indicators
        ctk.CTkLabel(sb, text="STATUS", font=("", 14, "bold")).pack(pady=(10, 4))
        self._lbl_st_region = ctk.CTkLabel(sb, text="Region: --", anchor="w",
                                           font=("", 12))
        self._lbl_st_region.pack(anchor="w", padx=12)
        self._lbl_st_window = ctk.CTkLabel(sb, text="Window: --", anchor="w",
                                           font=("", 12))
        self._lbl_st_window.pack(anchor="w", padx=12)
        self._lbl_st_calib = ctk.CTkLabel(sb, text="Calibration: --", anchor="w",
                                          font=("", 12))
        self._lbl_st_calib.pack(anchor="w", padx=12)

    # ── Main area ────────────────────────────────────────────────────

    def _build_main_area(self):
        main = ctk.CTkFrame(self)
        main.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # Board canvas
        board_frame = ctk.CTkFrame(main)
        board_frame.pack(pady=(8, 4))
        self._canvas_size = 320
        self._canvas = tk.Canvas(board_frame, width=self._canvas_size,
                                 height=self._canvas_size, bg="#bbada0",
                                 highlightthickness=0)
        self._canvas.pack(padx=10, pady=10)
        self._draw_board([[0] * 4 for _ in range(4)])

        # Stats row
        stats = ctk.CTkFrame(main, fg_color="transparent")
        stats.pack(fill="x", padx=16, pady=(4, 2))
        self._lbl_moves = ctk.CTkLabel(stats, text="Moves: 0", font=("", 13))
        self._lbl_moves.pack(side="left", padx=(0, 16))
        self._lbl_max = ctk.CTkLabel(stats, text="Max Tile: 0", font=("", 13))
        self._lbl_max.pack(side="left", padx=(0, 16))
        self._lbl_score = ctk.CTkLabel(stats, text="Score: ~0", font=("", 13))
        self._lbl_score.pack(side="left")

        # Log area
        ctk.CTkLabel(main, text="Log", font=("", 12, "bold"),
                     anchor="w").pack(fill="x", padx=16, pady=(8, 2))
        self._log_box = ctk.CTkTextbox(main, height=160, font=("Consolas", 12),
                                       state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    # ── Board drawing ────────────────────────────────────────────────

    def _draw_board(self, board):
        self._canvas.delete("all")
        size = self._canvas_size
        gap = 6
        cell = (size - gap * 5) / 4

        for r in range(4):
            for c in range(4):
                x = gap + c * (cell + gap)
                y = gap + r * (cell + gap)
                val = board[r][c]
                color = TILE_COLORS.get(val, "#3c3a32")

                self._canvas.create_rectangle(
                    x, y, x + cell, y + cell,
                    fill=color, outline="", width=0,
                )

                if val > 0:
                    tc = _TEXT_LIGHT if val <= 4 else _TEXT_DARK
                    fs = 24 if val < 100 else (20 if val < 1000 else
                          16 if val < 10000 else 13)
                    self._canvas.create_text(
                        x + cell / 2, y + cell / 2,
                        text=str(val), fill=tc,
                        font=("Helvetica", fs, "bold"),
                    )

    # ── Logging ──────────────────────────────────────────────────────

    def _log(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{ts}] {text}\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    # ── Status indicators ────────────────────────────────────────────

    def _update_status_indicators(self):
        if self._region:
            self._lbl_st_region.configure(
                text=f"Region: {self._region['width']}x{self._region['height']}")
        else:
            self._lbl_st_region.configure(text="Region: not set")

        if self._game_window_title:
            short = self._game_window_title[:20]
            self._lbl_st_window.configure(text=f"Window: {short}")
        else:
            self._lbl_st_window.configure(text="Window: manual focus")

        n = len(self._references)
        self._lbl_st_calib.configure(
            text=f"Calibration: {n} tiles" if n else "Calibration: not done")

    # ── Queue polling ────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                if isinstance(msg, BoardUpdate):
                    self._draw_board(msg.board)
                    self._update_stats(msg.board, msg.move, msg.move_count)
                    if msg.move:
                        self._log(f"Move {msg.move_count}: {msg.move.upper()}")
                elif isinstance(msg, LogMsg):
                    self._log(msg.text)
                elif isinstance(msg, SolverStopped):
                    self._log(f"Stopped: {msg.reason}")
                    self._set_running(False)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    # ── Stats ────────────────────────────────────────────────────────

    def _update_stats(self, board, move, move_count):
        self._move_count = move_count
        max_tile = max(max(row) for row in board)
        if max_tile > self._max_tile:
            self._max_tile = max_tile

        score = 0
        for row in board:
            for v in row:
                if v > 2:
                    score += int(v * (math.log2(v) - 1))

        self._lbl_moves.configure(text=f"Moves: {move_count}")
        self._lbl_max.configure(text=f"Max Tile: {self._max_tile}")
        self._lbl_score.configure(text=f"Score: ~{score:,}")

    # ── Button handlers ──────────────────────────────────────────────

    def _on_pick_region(self):
        result = _pick_region_overlay(
            self, REGION_FILE,
            "Drag a rectangle around the 2048 BOARD ONLY. Esc to cancel.",
        )
        if result:
            self._region = result
            self._log(f"Region set: {result['width']}x{result['height']}")
        self._update_status_indicators()

    def _on_pick_next_tile(self):
        result = _pick_region_overlay(
            self, NEXT_TILE_REGION_FILE,
            "Drag a rectangle around the NEXT TILE indicator. Esc to skip.",
        )
        if result:
            self._next_tile_region = result
            self._log("Next-tile region set")
        self._update_status_indicators()

    def _on_pick_game_window(self):
        GameWindowDialog(self, self._on_window_selected)

    def _on_window_selected(self, info):
        """info is None (skip) or dict with title, hwnd, x, y, w, h."""
        if info and info.get("hwnd"):
            title = info["title"]
            hwnd = info["hwnd"]
            self._game_window_title = title
            set_game_window_hwnd(hwnd, title)
            with open(GAME_WINDOW_FILE, "w") as f:
                json.dump({"title": title, "hwnd": hwnd}, f, indent=2)
            self._log(f"Window: {title[:35]} (hwnd={hwnd})")
        elif info and info.get("title"):
            title = info["title"]
            self._game_window_title = title
            set_game_window_title(title)
            with open(GAME_WINDOW_FILE, "w") as f:
                json.dump({"title": title}, f, indent=2)
            self._log(f"Window: {title[:40]}")
        else:
            self._game_window_title = ""
            self._log("Window focus: manual")
        self._update_status_indicators()

    def _on_calibrate(self):
        if not self._region:
            messagebox.showwarning("Not Ready", "Pick a board region first.")
            return
        CalibrationDialog(self, self._region, self._on_calibration_done)

    def _on_calibration_done(self, refs):
        self._references = refs
        if self._solver:
            self._solver.references = refs
        self._log(f"Calibrated {len(refs)} tiles")
        self._update_status_indicators()

    def _on_solver_change(self, value):
        config.SOLVER_MODE = value
        self._log(f"Solver: {value}")

    def _on_input_change(self, value):
        config.INPUT_METHOD = value
        self._log(f"Input: {value}")

    def _on_depth_change(self, value):
        d = int(round(value))
        config.SEARCH_DEPTH = d
        self._depth_label.configure(text=str(d))

    # ── Start / Stop ─────────────────────────────────────────────────

    def _on_start_stop(self):
        if self._running:
            self._stop_solver()
        else:
            self._start_solver()

    def _start_solver(self):
        if not self._region:
            messagebox.showwarning("Not Ready", "Pick a board region first.")
            return
        if not self._references:
            messagebox.showwarning("Not Ready", "Run calibration first.")
            return

        self._set_running(True)
        self._stop_event.clear()
        self._solver = SolverThread(
            self._region, self._references, self._next_tile_region,
            self._msg_queue, self._stop_event,
        )
        self._solver.start()
        self._log("Solver started")

    def _stop_solver(self):
        if self._solver:
            self._solver.stop()
            self._solver = None
        self._set_running(False)
        self._log("Solver stopped")

    def _set_running(self, running):
        self._running = running
        if running:
            self._btn_start.configure(text="STOP", fg_color="#c0392b",
                                      hover_color="#a93226")
        else:
            self._btn_start.configure(text="START", fg_color="#2d8a4e",
                                      hover_color="#25733f")
        state = "disabled" if running else "normal"
        self._btn_region.configure(state=state)
        self._btn_calibrate.configure(state=state)
        self._btn_next_tile.configure(state=state)

    # ── Helpers ──────────────────────────────────────────────────────

    def _load_game_window(self):
        try:
            with open(GAME_WINDOW_FILE) as f:
                return json.load(f).get("title")
        except FileNotFoundError:
            return None

    def _on_close(self):
        if self._solver:
            self._solver.stop()
        self.destroy()


# ── Entry point ──────────────────────────────────────────────────────

def run_gui():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
