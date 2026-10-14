"""Switch-accessible scanning virtual keyboard.

Built for someone who can reliably operate only a single key (default:
Space). The app continuously auto-scans:
  1. Rows, one at a time. Press the switch to lock in the current row.
  2. Blocks of up to BLOCK_SIZE keys within that row. Press the switch to
     lock in the current block. Rows that are already one block (prediction
     and SPACE/DEL/ENTER/CLEAR) skip this step.
  3. The individual keys within that block. Press the switch to select the
     highlighted key -- it's typed, and scanning restarts from the top.

Letter rows still take 3 presses (row, block, key). Single-block rows take
2 (row, then key). After the first finished word, the next scan starts on
the prediction row.

Run: python main.py    (nltk is optional -- see README)
Escape twice quits. Defaults live in config.py; every value can also be
changed live with the mouse via the Settings button (top right), which is
not part of the scanning flow. Changes are saved to settings.json.
"""

import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

import config
import settings
from predictor import Predictor
from scanner import STAGE_BLOCK, STAGE_KEY, STAGE_ROW, Scanner
from settings_ui import SettingsWindow

# Settings whose change needs the scan clock restarted / layout rebuilt.
_TIMING_KEYS = {"SCAN_INTERVAL_SECONDS", "AFTER_LOCK_SECONDS", "SELECT_PAUSE_SECONDS"}
_LAYOUT_KEYS = {"PREDICTION_SLOTS", "LETTER_ROWS", "BLOCK_SIZE"}
_PREDICTION_KEYS = {"PREDICTION_MODEL", "DICTIONARY_FALLBACK"}

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows platforms
    winsound = None


def _crash_log_path():
    import paths
    return paths.user_path("crash.log")


def _log_error(exc_type, exc, tb):
    """Append an error to crash.log (in the user data folder). Never raises."""
    import traceback
    try:
        with open(_crash_log_path(), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("--- %Y-%m-%d %H:%M:%S ---\n"))
            fh.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
    except Exception:
        pass
    try:
        traceback.print_exception(exc_type, exc, tb)
    except Exception:
        pass


def _show_fatal(exc_type, exc, tb):
    """Last resort for an error that stops the app: log it and tell the
    user where, since a packaged windowed app has no console to show it."""
    _log_error(exc_type, exc, tb)
    try:
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Scanning Keyboard stopped unexpectedly",
            f"{exc_type.__name__}: {exc}\n\nDetails were saved to:\n{_crash_log_path()}",
        )
        root.destroy()
    except Exception:
        pass


def _beep(freq, ms):
    if not config.AUDIO_ENABLED or winsound is None:
        return
    try:
        winsound.Beep(freq, ms)
    except Exception:
        pass  # audio is a nicety, never worth crashing over


class App:
    def __init__(self):
        self._settings = None  # the open SettingsWindow, if any
        self.root = tk.Tk()
        # An error inside any Tk callback is logged and the app keeps
        # running, rather than leaving a user with no idea what happened.
        self.root.report_callback_exception = lambda *exc: _log_error(*exc)
        self.root.title("Scanning Keyboard")
        self.root.configure(bg=config.BG_COLOR)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<KeyPress>", self._on_key)
        # If some other window steals keyboard focus (an OS notification,
        # a screensaver, an accidental click), switch presses would
        # silently go nowhere. In KIOSK_MODE, reclaim focus shortly after
        # losing it -- delayed slightly so we're not fighting whatever
        # just took it mid-transition. (Always bound, so KIOSK_MODE can be
        # switched on/off live from Settings.)
        self.root.bind("<FocusOut>", lambda e: self.root.after(50, self._reclaim_focus))
        self._apply_kiosk()

        self.canvas = tk.Canvas(self.root, bg=config.BG_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._render())

        # Mouse-only entry to the settings window. Not focusable and not
        # reachable by the scanner, so it can never be hit by accident
        # from the switch.
        self.settings_btn = tk.Button(
            self.root, text="\u2699 Settings", command=self.open_settings, takefocus=0,
            font=("Segoe UI", 11), bg="#2b2b2b", fg="#cccccc", activebackground="#555555",
            activeforeground="#ffffff", relief="flat", borderwidth=0, padx=14, pady=5,
        )
        self.settings_btn.place(relx=1.0, x=-12, y=8, anchor="ne")

        self.scanner = Scanner(config.LAYOUT)
        self.predictor = Predictor()
        self.text = ""
        self._refresh_predictions()
        self._last_switch_time = float("-inf")
        self._paused_until = 0.0
        self._flash_pos = None  # (row, block, key) of the just-selected key
        self._last_escape_time = float("-inf")
        self._fit_font = tkfont.Font(family=config.FONT_FAMILY, weight="bold")
        self._fit_family = config.FONT_FAMILY
        self._tick_after_id = None

        self._render()
        self._schedule_tick()

    def _apply_kiosk(self):
        self.root.attributes("-topmost", bool(config.KIOSK_MODE))
        if config.KIOSK_MODE:
            self.root.after(50, self._reclaim_focus)

    def _reclaim_focus(self):
        if not config.KIOSK_MODE or self._settings is not None:
            return  # let the settings window have focus while it's open
        try:
            self.root.focus_force()
        except tk.TclError:
            pass  # window may already be closing

    def run(self):
        self.root.mainloop()

    # --- settings (mouse only; separate from scanning) ---

    def open_settings(self):
        if self._settings is not None:
            try:
                self._settings.win.lift()
                self._settings.win.focus_force()
            except tk.TclError:
                pass
            return
        self.scanner.reset()
        self._flash_pos = None
        self._render()
        self._settings = SettingsWindow(self, self._settings_closed)

    def _settings_closed(self):
        self._settings = None
        self.scanner.reset()
        self._flash_pos = None
        self._render()
        self._schedule_tick()
        self.root.after(50, self._reclaim_focus)
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def apply_settings(self, keys):
        """Bring the running app in line with settings that were just
        changed. Most values are read from config at the moment they're
        used; this rebuilds the few things computed ahead of time."""
        keys = set(keys)
        relayout = bool(keys & _LAYOUT_KEYS)
        if relayout:
            config.LAYOUT = config.build_layout()
            self.scanner = Scanner(config.LAYOUT)
            self._flash_pos = None
        if "PREDICTION_MODEL" in keys:
            self.predictor = Predictor()
        if relayout or keys & _PREDICTION_KEYS:
            self._refresh_predictions()
        if "KIOSK_MODE" in keys:
            self._apply_kiosk()
        if "BG_COLOR" in keys:
            self.root.configure(bg=config.BG_COLOR)
            self.canvas.configure(bg=config.BG_COLOR)
        if relayout or keys & _TIMING_KEYS:
            self._schedule_tick()
        self._render()

    # --- input ---

    def _on_key(self, event):
        if self._settings is not None:
            return  # scanning is paused while Settings is open
        if event.keysym.lower() != config.SWITCH_KEYSYM.lower():
            return
        now = time.monotonic()
        if now < self._paused_until:
            return  # ignore presses during the post-selection confirmation pause
        if now - self._last_switch_time < config.SWITCH_DEBOUNCE_SECONDS:
            return  # debounce: OS key-repeat or accidental double-press
        self._last_switch_time = now
        self._handle_select()

    def _on_escape(self, event):
        # Killing a fullscreen, otherwise-unattended communication tool
        # should never happen from a single stray keypress -- require two
        # presses within QUIT_CONFIRM_WINDOW_SECONDS.
        now = time.monotonic()
        if now - self._last_escape_time < config.QUIT_CONFIRM_WINDOW_SECONDS:
            self.root.destroy()
            return
        self._last_escape_time = now
        _beep(config.CONFIRM_TONE_HZ, config.CONFIRM_TONE_MS)

    def _handle_select(self):
        about_to_choose_key = self.scanner.stage == STAGE_KEY
        if about_to_choose_key:
            self._flash_pos = (self.scanner.row_index, self.scanner.block_index, self.scanner.key_index)

        selected = self.scanner.select()

        if selected is None:
            _beep(config.ADVANCE_TONE_HZ, config.ADVANCE_TONE_MS)
            self._render()
            self._schedule_tick(self._after_lock_seconds())
            return

        self._apply_key(selected)
        self._refresh_predictions()
        self._maybe_focus_predictions()
        _beep(config.SELECT_TONE_HZ, config.SELECT_TONE_MS)
        self._paused_until = time.monotonic() + config.SELECT_PAUSE_SECONDS
        self._render(flash=True)
        self._schedule_tick(config.SELECT_PAUSE_SECONDS)

    def _apply_key(self, key):
        if key.startswith(config.PRED_PREFIX):
            word = key[len(config.PRED_PREFIX):]
            if word:
                self._insert_prediction(word)
            return
        if key == "SPACE":
            self.text += " "
        elif key == "BACKSPACE":
            self.text = self.text[:-1]
        elif key == "ENTER":
            self.predictor.observe(self.text.split("\n")[-1])
            self.text += "\n"
        elif key == "CLEAR":
            self.text = ""
        else:
            self.text += key

    def _insert_prediction(self, word):
        """Replace the in-progress word (or append after a finished one)
        and add a trailing space so the next prediction is for a new word."""
        i = max(self.text.rfind(" "), self.text.rfind("\n"))
        if not self.text or self.text.endswith(" ") or self.text.endswith("\n"):
            self.text += word + " "
        else:
            self.text = self.text[: i + 1] + word + " "

    def _refresh_predictions(self):
        words = self.predictor.suggest(self.text, k=config.PREDICTION_SLOTS)
        self.scanner.layout[0][:] = [config.PRED_PREFIX + w for w in words]

    def _maybe_focus_predictions(self):
        """After the first finished word, start the next scan on the
        prediction row so next-word suggestions are the first thing shown."""
        needed = getattr(config, "PRED_FOCUS_AFTER_WORDS", 1)
        if needed and self._finished_word_count() >= needed:
            self.scanner.start_at_prediction_row()

    def _finished_word_count(self):
        line = self.text.split("\n")[-1]
        if not line.strip():
            return 0
        parts = line.split()
        if line.endswith(" ") or self.text.endswith("\n"):
            return len(parts)
        return max(0, len(parts) - 1)

    # --- scan timer ---

    def _after_lock_seconds(self):
        return float(getattr(config, "AFTER_LOCK_SECONDS", config.SCAN_INTERVAL_SECONDS))

    def _cancel_tick(self):
        after_id = getattr(self, "_tick_after_id", None)
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except tk.TclError:
            pass
        self._tick_after_id = None

    def _schedule_tick(self, delay_seconds=None):
        """(Re)start the auto-scan clock. Cancels any pending tick so a
        switch press always gives the new highlight a full dwell."""
        self._cancel_tick()
        if delay_seconds is None:
            delay_seconds = config.SCAN_INTERVAL_SECONDS
        ms = max(1, int(float(delay_seconds) * 1000))
        self._tick_after_id = self.root.after(ms, self._tick)

    def _tick(self):
        self._tick_after_id = None
        if self._settings is not None:
            self._schedule_tick(0.25)  # paused while Settings is open
            return
        remaining = self._paused_until - time.monotonic()
        if remaining > 0:
            self._schedule_tick(remaining)
            return
        event = self.scanner.tick()
        if event == "reset":
            _beep(config.CANCEL_TONE_HZ, config.CANCEL_TONE_MS)
            _beep(config.CANCEL_TONE_HZ, config.CANCEL_TONE_MS)
        else:
            _beep(config.TICK_TONE_HZ, config.TICK_TONE_MS)
        self._render()
        self._schedule_tick()

    # --- rendering ---

    def _render(self, flash=False):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()

        # Fixed share of the screen regardless of TEXT_LINES, so the keys
        # below never change size when more lines are turned on.
        text_h = int(h * config.TEXT_BOX_HEIGHT_FRACTION)
        self._draw_text_buffer(w, text_h)

        kb_top = text_h
        kb_h = h - text_h
        layout = self.scanner.layout
        n_rows = len(layout)
        row_h = kb_h / n_rows

        highlight = None if flash else self.scanner.current_highlight()
        m = config.CELL_MARGIN

        for r, row in enumerate(layout):
            y0 = kb_top + r * row_h
            y1 = y0 + row_h
            key_w = w / len(row)
            blocks = self.scanner.blocks_for_row(r)

            flat_to_block = []
            for b_idx, block in enumerate(blocks):
                for k_idx in range(len(block)):
                    flat_to_block.append((b_idx, k_idx))

            display_labels = [config.display_label(label) for label in row]
            is_pred_row = any(label.startswith(config.PRED_PREFIX) for label in row)
            if not is_pred_row:
                fit_labels = [lab if lab else "MMMMMM" for lab in display_labels]
                row_font_size = self._fit_font_size(fit_labels, key_w, row_h)

            for i, label in enumerate(row):
                x0 = i * key_w
                x1 = x0 + key_w
                b_idx, k_idx = flat_to_block[i]

                is_flash = flash and self._flash_pos == (r, b_idx, k_idx)
                bg, fg = self._color_for(r, b_idx, k_idx, highlight, is_flash)

                self.canvas.create_rectangle(x0 + m, y0 + m, x1 - m, y1 - m, fill=bg, outline="")
                shown = display_labels[i]
                if not shown:
                    continue
                if is_pred_row:
                    font_size = self._fit_font_size([shown], key_w, row_h)
                else:
                    font_size = row_font_size
                self.canvas.create_text(
                    (x0 + x1) / 2, (y0 + y1) / 2, text=shown, fill=fg,
                    font=(config.FONT_FAMILY, font_size, "bold"),
                    width=max(1, int((x1 - x0) - 2 * m)),
                )

    def _fit_font_size(self, labels, cell_w, cell_h, min_size=None):
        """Largest font size (within config bounds) at which every label in
        `labels` fits inside a cell of cell_w x cell_h, leaving margin."""
        max_w = cell_w * config.CELL_FIT_WIDTH_FRACTION
        max_h = cell_h * config.CELL_FIT_HEIGHT_FRACTION
        lo = config.MIN_KEY_FONT_SIZE if min_size is None else min_size
        hi = max(lo, config.MAX_KEY_FONT_SIZE)
        best = lo
        if self._fit_family != config.FONT_FAMILY:
            self._fit_font.configure(family=config.FONT_FAMILY)
            self._fit_family = config.FONT_FAMILY
        while lo <= hi:
            mid = (lo + hi) // 2
            self._fit_font.configure(size=mid)
            widest = max(self._fit_font.measure(label) for label in labels)
            line_h = self._fit_font.metrics("linespace")
            if widest <= max_w and line_h <= max_h:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _color_for(self, row, block_idx, key_idx, highlight, is_flash):
        if is_flash:
            return config.FLASH_BG, config.FLASH_FG
        if highlight is None or row != highlight["row"]:
            return config.KEY_IDLE_BG, config.KEY_IDLE_FG

        stage = highlight["stage"]
        if stage == STAGE_ROW:
            return config.ROW_SCAN_BG, config.ROW_SCAN_FG
        if stage == STAGE_BLOCK:
            if block_idx == highlight["block"]:
                return config.BLOCK_SCAN_BG, config.BLOCK_SCAN_FG
            return config.ROW_LOCKED_BG, config.ROW_LOCKED_FG
        # STAGE_KEY
        if block_idx != highlight["block"]:
            return config.ROW_LOCKED_BG, config.ROW_LOCKED_FG
        if key_idx == highlight["key"]:
            return config.KEY_SCAN_BG, config.KEY_SCAN_FG
        return config.BLOCK_SCAN_BG, config.BLOCK_SCAN_FG

    def _draw_text_buffer(self, w, text_h):
        self.canvas.create_rectangle(0, 0, w, text_h, fill=config.TEXT_BUFFER_BG, outline="")

        n_lines = max(1, min(3, int(config.TEXT_LINES)))
        slot_h = text_h / n_lines  # vertical space for each text line
        x0 = 20
        cursor_room = config.CURSOR_GAP + config.CURSOR_WIDTH + 10
        # Keep text clear of the Settings button in the top-right corner.
        button_room = max(self.settings_btn.winfo_reqwidth(), 90) + 24
        avail_w = max(60, w - x0 - cursor_room - button_room)

        if n_lines == 1:
            display_text = self.text.replace("\n", "\\n")
            if len(display_text) > 40:
                display_text = "..." + display_text[-37:]
            font_size = self._fit_font_size([display_text or "M"], avail_w, slot_h, min_size=6)
            font_size = min(font_size, config.MAX_TEXT_FONT_SIZE)
            self._fit_font.configure(size=font_size)
            lines = [display_text]
        else:
            # Same box height as one line, so more lines means smaller text.
            font_size = self._fit_font_size(["Mg"], 100000, slot_h, min_size=6)
            font_size = min(font_size, config.MAX_TEXT_FONT_SIZE)
            self._fit_font.configure(size=font_size)
            lines = self._wrap_text(self.text, avail_w)[-n_lines:]

        # The cursor always sits right after the last character (or at the
        # very start, if nothing's been typed yet) -- this is what makes a
        # just-typed SPACE visible: the bar jumps right with nothing to see
        # in between, clearly distinct from "nothing happened".
        cursor_x = x0 + config.CURSOR_GAP
        cursor_cy = slot_h / 2
        for i, line in enumerate(lines):
            cy = slot_h * (i + 0.5)
            line_w = 0
            if line:
                self.canvas.create_text(
                    x0, cy, text=line, fill=config.TEXT_COLOR,
                    font=(config.FONT_FAMILY, font_size, "bold"), anchor="w",
                )
                line_w = self._fit_font.measure(line)
            if i == len(lines) - 1:
                cursor_x = x0 + line_w + config.CURSOR_GAP
                cursor_cy = cy

        cursor_h = slot_h * config.CURSOR_HEIGHT_FRACTION
        self.canvas.create_rectangle(
            cursor_x, cursor_cy - cursor_h / 2, cursor_x + config.CURSOR_WIDTH, cursor_cy + cursor_h / 2,
            fill=config.CURSOR_COLOR, outline="",
        )

        if not self.text:
            hint_size = min(
                config.TEXT_HINT_FONT_SIZE,
                self._fit_font_size(["Mg"], 100000, slot_h, min_size=6),
            )
            self.canvas.create_text(
                cursor_x + config.CURSOR_WIDTH + 16, slot_h / 2, text="(nothing typed yet)",
                fill="#666666", font=(config.FONT_FAMILY, hint_size), anchor="w",
            )

    def _wrap_text(self, text, avail_w):
        """Break `text` into display lines no wider than avail_w at the
        current _fit_font size. Wraps at spaces, honors typed newlines,
        and splits a single over-long word by characters. Always returns
        at least one (possibly empty) line."""
        measure = self._fit_font.measure
        lines = []
        for hard_line in text.split("\n"):
            current = ""
            for token in re.findall(r"\s+|\S+", hard_line):
                if token.isspace():
                    current += token
                    continue
                if current.strip() and measure(current + token) > avail_w:
                    lines.append(current)
                    current = ""
                while len(token) > 1 and measure(token) > avail_w:
                    cut = len(token) - 1
                    while cut > 1 and measure(token[:cut]) > avail_w:
                        cut -= 1
                    if current:
                        lines.append(current)
                        current = ""
                    lines.append(token[:cut])
                    token = token[cut:]
                current += token
            lines.append(current)
        return lines


def _selftest(report_path):
    """Headless-ish smoke test used to verify a packaged .exe actually
    works on a clean machine: bundled data present, predictions working,
    settings round-trip, multi-line text box and the Settings window
    build and close. Writes a report file and exits 0 on success."""
    import os
    import tempfile
    import traceback

    import paths
    import predictor as predictor_module

    lines, failures = [], []

    def check(name, ok, detail=""):
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    try:
        lines.append(
            f"frozen={paths.is_frozen()} resources={paths.resource_dir()} "
            f"userdata={paths.user_data_dir()}"
        )
        config.AUDIO_ENABLED = False
        words = len(predictor_module._DICTIONARY_WORDS)
        check("dictionary bundled", words > 50000, f"{words} words")
        lines.append(f"[INFO] NLTK tokenizer active: {predictor_module._NLTK_OK}")

        p = Predictor()
        check("blank line -> blank slots", p.suggest("") == [""] * config.PREDICTION_SLOTS)
        after_space = p.suggest("HOW ")
        check("next-word suggestions", all(after_space), str(after_space))
        completions = p.suggest("BLU")
        check("dictionary fallback fills slots", all(completions), str(completions))

        tmp = os.path.join(tempfile.mkdtemp(), "settings.json")
        settings.apply("TEXT_LINES", 3)
        settings.apply("SCAN_INTERVAL_SECONDS", 2.5)
        settings.apply("LETTER_ROWS", ["abc", "def", "ghi"])
        check("settings save", settings.save(tmp))
        settings.reset_all()
        settings.load(tmp)
        check(
            "settings reload",
            config.TEXT_LINES == 3 and config.SCAN_INTERVAL_SECONDS == 2.5
            and config.LAYOUT[1] == list("ABC"),
        )
        settings.reset_all()
        settings.apply("TEXT_LINES", 3)

        app = App()
        app.root.update()
        app.text = "I WOULD LIKE A GLASS OF WATER PLEASE AND ALSO SOME HELP WITH MY BACK TODAY THANK YOU "
        app._render()
        wrapped = app._wrap_text(app.text, 500)
        check("multi-line wrap", len(wrapped) > 1, f"{len(wrapped)} lines")
        for _ in range(4):
            app._handle_select()
            app._paused_until = 0.0
        app.root.update()
        app.apply_settings(set(settings.BY_KEY))
        app.root.update()
        app.open_settings()
        app.root.update()
        check("settings window opens", app._settings is not None)
        app._settings.close()
        app.root.update()
        check("settings window closes", app._settings is None)
        app.root.destroy()
    except Exception:
        lines.append(traceback.format_exc())
        failures.append("exception")

    lines.append("SELFTEST " + ("FAILED" if failures else "OK"))
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import os
        import tempfile

        i = sys.argv.index("--selftest")
        report = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(
            tempfile.gettempdir(), "scanning_keyboard_selftest.txt"
        )
        _selftest(report)
    else:
        try:
            settings.load()
            App().run()
        except Exception:
            _show_fatal(*sys.exc_info())
            sys.exit(1)
