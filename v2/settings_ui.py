"""The mouse-operated Settings window.

Deliberately separate from the scanning flow: it is only reachable with
the mouse (the on-screen Settings button), and while it is open the
scanner is paused and KIOSK_MODE focus-reclaiming steps aside so the
window can be used normally. Every change is applied immediately and
saved; there is no Apply/OK step.
"""

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from tkinter import font as tkfont

import config
import settings

PAD = 8


class SettingsWindow:
    def __init__(self, app, on_close):
        self.app = app
        self.on_close = on_close
        self._pending = set()
        self._flush_id = None
        self._refreshers = {}   # key -> callable that re-reads config into its control
        self._capturing = None

        root = app.root
        self.win = tk.Toplevel(root)
        win = self.win
        win.title("Settings")
        win.transient(root)
        screen_w, screen_h = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(820, screen_w - 80), min(720, screen_h - 120)
        win.geometry(f"{w}x{h}+{(screen_w - w) // 2}+{max(20, (screen_h - h) // 3)}")
        win.minsize(560, 420)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())

        outer = ttk.Frame(win, padding=PAD)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Changes apply immediately and are saved automatically. "
                 "Scanning is paused while this window is open.",
            wraplength=w - 40,
        ).pack(anchor="w", pady=(0, PAD))

        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(PAD, 0))
        ttk.Button(footer, text="Reset all to defaults", command=self._reset_all).pack(side="left")
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.status = ttk.Label(footer, text="")
        self.status.pack(side="right", padx=PAD)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)

        self._families = None
        for group in settings.GROUPS:
            page = self._scrollable_page(self.notebook)
            self.notebook.add(page.container, text=group)
            row = 0
            for s in settings.SCHEMA:
                if s.group == group:
                    self._add_row(page.inner, row, s)
                    row += 1
            page.inner.columnconfigure(1, weight=1)

        win.after(50, win.focus_force)

    # ------------------------------------------------------------ plumbing

    def _scrollable_page(self, parent):
        container = ttk.Frame(parent)
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=PAD)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))

        def wheel(event):
            canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

        container.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        container.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        class Page:
            pass

        page = Page()
        page.container, page.inner = container, inner
        return page

    def _add_row(self, parent, row, s):
        label_box = ttk.Frame(parent)
        label_box.grid(row=row, column=0, sticky="nw", padx=(0, 16), pady=6)
        ttk.Label(label_box, text=s.label).pack(anchor="w")
        if s.hint:
            ttk.Label(label_box, text=s.hint, foreground="#666666", wraplength=300,
                      justify="left").pack(anchor="w")
        control = self._build_control(parent, s)
        control.grid(row=row, column=1, sticky="w", pady=6)

    def _commit(self, s, value):
        """Apply one change live (debounced save + app refresh)."""
        try:
            settings.apply(s.key, value)
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return False
        self.status.configure(text="")
        self._pending.add(s.key)
        if self._flush_id is not None:
            self.win.after_cancel(self._flush_id)
        self._flush_id = self.win.after(120, self._flush)
        return True

    def _flush(self):
        self._flush_id = None
        keys, self._pending = self._pending, set()
        if not keys:
            return
        if not settings.save():
            self.status.configure(text="(could not save to disk; change is live for this session)")
        self.app.apply_settings(keys)

    def _reset_all(self):
        if not messagebox.askyesno(
            "Reset settings", "Put every setting back to its default?", parent=self.win
        ):
            return
        keys = settings.reset_all()
        settings.save()
        for refresh in self._refreshers.values():
            refresh()
        self.app.apply_settings(keys)

    def close(self):
        if self._flush_id is not None:
            self.win.after_cancel(self._flush_id)
            self._flush()
        try:
            self.win.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_close()

    # ------------------------------------------------------------ controls

    def _build_control(self, parent, s):
        builder = {
            "float": self._number, "int": self._number, "bool": self._bool,
            "color": self._color, "choice": self._choice, "font": self._font,
            "text": self._text, "keysym": self._keysym, "strlist": self._strlist,
        }[s.kind]
        return builder(parent, s)

    def _number(self, parent, s):
        frame = ttk.Frame(parent)
        var = tk.StringVar(value=settings.format_number(s, getattr(config, s.key)))
        scale = None

        def take(raw, move_slider=True):
            try:
                value = settings.coerce(s, raw)
            except ValueError:
                var.set(settings.format_number(s, getattr(config, s.key)))
                return
            var.set(settings.format_number(s, value))
            if value == getattr(config, s.key):
                return
            # Never call scale.set() from the slider's own callback: Tk
            # rejects that re-entrant call with a bare TclError.
            if move_slider and scale is not None:
                try:
                    scale.set(value)
                except tk.TclError:
                    pass
            self._commit(s, value)

        def from_slider(raw):
            take(raw, move_slider=False)

        spin = ttk.Spinbox(frame, from_=s.lo, to=s.hi, increment=s.step, width=8,
                           textvariable=var, command=lambda: take(var.get()))
        spin.bind("<Return>", lambda e: take(var.get()))
        spin.bind("<FocusOut>", lambda e: take(var.get()))
        if s.slider:
            scale = ttk.Scale(frame, from_=s.lo, to=s.hi, orient="horizontal", length=260,
                              command=from_slider)
            scale.set(getattr(config, s.key))
            scale.pack(side="left", padx=(0, PAD))
        spin.pack(side="left")

        def refresh():
            value = getattr(config, s.key)
            var.set(settings.format_number(s, value))
            if scale is not None:
                try:
                    scale.set(value)
                except tk.TclError:
                    pass

        self._refreshers[s.key] = refresh
        return frame

    def _bool(self, parent, s):
        var = tk.BooleanVar(value=bool(getattr(config, s.key)))
        check = ttk.Checkbutton(parent, text="On", variable=var,
                                command=lambda: self._commit(s, var.get()))
        self._refreshers[s.key] = lambda: var.set(bool(getattr(config, s.key)))
        return check

    def _color(self, parent, s):
        frame = ttk.Frame(parent)
        current = getattr(config, s.key)
        var = tk.StringVar(value=current)
        swatch = tk.Button(frame, width=5, bg=current, activebackground=current,
                           relief="solid", borderwidth=1)

        def paint(value):
            swatch.configure(bg=value, activebackground=value)

        def take(_event=None):
            try:
                value = settings.coerce(s, var.get())
            except ValueError as exc:
                self.status.configure(text=str(exc))
                var.set(getattr(config, s.key))
                paint(getattr(config, s.key))
                return
            var.set(value)
            paint(value)
            if value != getattr(config, s.key):
                self._commit(s, value)

        def pick():
            _rgb, chosen = colorchooser.askcolor(color=var.get(), parent=self.win, title=s.label)
            if chosen:
                var.set(chosen)
                take()

        swatch.configure(command=pick)
        entry = ttk.Entry(frame, textvariable=var, width=10)
        entry.bind("<Return>", take)
        entry.bind("<FocusOut>", take)
        swatch.pack(side="left", padx=(0, PAD))
        entry.pack(side="left")

        def refresh():
            var.set(getattr(config, s.key))
            paint(getattr(config, s.key))

        self._refreshers[s.key] = refresh
        return frame

    def _choice(self, parent, s):
        choices = settings.model_choices() if s.key == "PREDICTION_MODEL" else s.choices
        var = tk.StringVar(value=str(getattr(config, s.key)))
        box = ttk.Combobox(parent, textvariable=var, values=list(choices), state="readonly", width=24)
        box.bind("<<ComboboxSelected>>", lambda e: self._commit(s, var.get()))
        self._refreshers[s.key] = lambda: var.set(str(getattr(config, s.key)))
        return box

    def _font(self, parent, s):
        if self._families is None:
            self._families = sorted(
                {f for f in tkfont.families(self.app.root) if not f.startswith("@")}
            )
        var = tk.StringVar(value=str(getattr(config, s.key)))
        box = ttk.Combobox(parent, textvariable=var, values=self._families, state="readonly", width=30)
        box.bind("<<ComboboxSelected>>", lambda e: self._commit(s, var.get()))
        self._refreshers[s.key] = lambda: var.set(str(getattr(config, s.key)))
        return box

    def _text(self, parent, s):
        var = tk.StringVar(value=str(getattr(config, s.key)))

        def take(_event=None):
            try:
                value = settings.coerce(s, var.get())
            except ValueError as exc:
                self.status.configure(text=str(exc))
                var.set(getattr(config, s.key))
                return
            var.set(value)
            if value != getattr(config, s.key):
                self._commit(s, value)

        entry = ttk.Entry(parent, textvariable=var, width=14)
        entry.bind("<Return>", take)
        entry.bind("<FocusOut>", take)
        self._refreshers[s.key] = lambda: var.set(str(getattr(config, s.key)))
        return entry

    def _strlist(self, parent, s):
        frame = ttk.Frame(parent)
        values = list(getattr(config, s.key))
        vars_ = [tk.StringVar(value=v) for v in values]

        def take(_event=None):
            try:
                value = settings.coerce(s, [v.get() for v in vars_])
            except ValueError as exc:
                self.status.configure(text=str(exc))
                value = list(getattr(config, s.key))
            for var, text in zip(vars_, value):
                var.set(text)
            if value != getattr(config, s.key):
                self._commit(s, value)

        for var in vars_:
            entry = ttk.Entry(frame, textvariable=var, width=20)
            entry.bind("<Return>", take)
            entry.bind("<FocusOut>", take)
            entry.pack(anchor="w", pady=1)

        def refresh():
            for var, text in zip(vars_, getattr(config, s.key)):
                var.set(text)

        self._refreshers[s.key] = refresh
        return frame

    def _keysym(self, parent, s):
        button = ttk.Button(parent, width=34)

        def show():
            button.configure(text=f"{getattr(config, s.key)}   (click to change)")

        def stop(_event=None):
            if self._capturing is button:
                self._capturing = None
                show()

        def capture(event):
            if self._capturing is not button:
                return None
            if event.keysym != "Escape" and event.keysym not in (
                "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"
            ):
                self._commit(s, event.keysym)
            stop()
            return "break"

        def start():
            self._capturing = button
            button.configure(text="Press the switch key now...  (Esc to cancel)")
            button.focus_set()

        button.configure(command=start)
        button.bind("<KeyPress>", capture)
        button.bind("<FocusOut>", stop)
        show()
        self._refreshers[s.key] = show
        return button
