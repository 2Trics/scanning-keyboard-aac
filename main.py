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

Run: python main.py    (needs nltk -- see README)
Escape quits. Every timing, color, and layout value lives in config.py.
"""

import time
import tkinter as tk
import tkinter.font as tkfont

import config
from predictor import NgramPredictor
from scanner import STAGE_BLOCK, STAGE_KEY, STAGE_ROW, Scanner

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows platforms
    winsound = None


def _beep(freq, ms):
    if not config.AUDIO_ENABLED or winsound is None:
        return
    try:
        winsound.Beep(freq, ms)
    except Exception:
        pass  # audio is a nicety, never worth crashing over


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Scanning Keyboard")
        self.root.configure(bg=config.BG_COLOR)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<KeyPress>", self._on_key)

        if config.KIOSK_MODE:
            self.root.attributes("-topmost", True)
            # If some other window steals keyboard focus (an OS
            # notification, a screensaver, an accidental click), switch
            # presses would silently go nowhere. Reclaim focus shortly
            # after losing it -- delayed slightly so we're not fighting
            # whatever just took it mid-transition.
            self.root.bind("<FocusOut>", lambda e: self.root.after(50, self._reclaim_focus))
            self.root.after(50, self._reclaim_focus)

        self.canvas = tk.Canvas(self.root, bg=config.BG_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._render())

        self.scanner = Scanner(config.LAYOUT)
        self.predictor = NgramPredictor()
        self.text = ""
        self._refresh_predictions()
        self._last_switch_time = float("-inf")
        self._paused_until = 0.0
        self._flash_pos = None  # (row, block, key) of the just-selected key
        self._flash_colors = (config.FLASH_BG, config.FLASH_FG)
        self._pending_clear = None  # monotonic time of an unconfirmed CLEAR press, or None
        self._last_escape_time = float("-inf")
        self._fit_font = tkfont.Font(family=config.FONT_FAMILY, weight="bold")
        self._tick_after_id = None

        self._render()
        self._schedule_tick()

    def _reclaim_focus(self):
        try:
            self.root.focus_force()
        except tk.TclError:
            pass  # window may already be closing

    def run(self):
        self.root.mainloop()

    # --- input ---

    def _on_key(self, event):
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

        applied = self._apply_key(selected)
        self._refresh_predictions()
        self._maybe_focus_predictions()
        if applied:
            _beep(config.SELECT_TONE_HZ, config.SELECT_TONE_MS)
            self._flash_colors = (config.FLASH_BG, config.FLASH_FG)
        else:
            _beep(config.CONFIRM_TONE_HZ, config.CONFIRM_TONE_MS)
            self._flash_colors = (config.CONFIRM_FLASH_BG, config.CONFIRM_FLASH_FG)
        self._paused_until = time.monotonic() + config.SELECT_PAUSE_SECONDS
        self._render(flash=True)
        self._schedule_tick(config.SELECT_PAUSE_SECONDS)

    def _apply_key(self, key):
        if key.startswith(config.PRED_PREFIX):
            word = key[len(config.PRED_PREFIX):]
            if word:
                self._insert_prediction(word)
            return True

        if key == "CLEAR":
            self.text = ""
            return True  # Applies immediately on selection

        if key == "SPACE":
            self.text += " "
        elif key == "BACKSPACE":
            self.text = self.text[:-1]
        elif key == "ENTER":
            self.predictor.observe(self.text.split("\n")[-1])
            self.text += "\n"
        else:
            self.text += key
        return True

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

        text_h = int(h * 0.14)
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

    def _fit_font_size(self, labels, cell_w, cell_h):
        """Largest font size (within config bounds) at which every label in
        `labels` fits inside a cell of cell_w x cell_h, leaving margin."""
        max_w = cell_w * config.CELL_FIT_WIDTH_FRACTION
        max_h = cell_h * config.CELL_FIT_HEIGHT_FRACTION
        lo, hi = config.MIN_KEY_FONT_SIZE, config.MAX_KEY_FONT_SIZE
        best = lo
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
            return self._flash_colors
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
        display_text = self.text.replace("\n", "\\n")
        if len(display_text) > 40:
            display_text = "..." + display_text[-37:]
        text = display_text or "(nothing typed yet)"
        font_size = self._fit_font_size([text], w - 40, text_h)
        font_size = min(font_size, config.MAX_TEXT_FONT_SIZE)
        self.canvas.create_text(
            20, text_h / 2, text=text, fill=config.TEXT_COLOR,
            font=(config.FONT_FAMILY, font_size, "bold"), anchor="w",
        )


if __name__ == "__main__":
    App().run()
