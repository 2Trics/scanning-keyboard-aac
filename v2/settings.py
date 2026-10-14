"""Live-editable settings: what can be changed, valid ranges, and saving.

config.py holds the defaults. Every value the app uses is read from the
`config` module at the moment it's needed, so changing a setting is just
`setattr(config, KEY, value)` -- main.py then rebuilds the few things that
are computed ahead of time (layout, scanner, predictor, tick timer).

Only values that differ from the defaults are written to settings.json
(in the user data folder), so a later change to a default still reaches
anyone who never touched that setting.
"""

import copy
import json
import os
import re
from dataclasses import dataclass

import config
import paths

SETTINGS_FILENAME = "settings.json"

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    group: str
    kind: str  # float | int | bool | color | choice | font | text | keysym | strlist
    lo: float = 0       # numeric min; for text/strlist: max length
    hi: float = 0       # numeric max
    step: float = 1
    slider: bool = False
    choices: tuple = ()
    count: int = 0      # strlist: required number of entries
    hint: str = ""


def _models():
    from aac_sentences import CORPORA
    return tuple(CORPORA) + ("brown",)


G_SPEED = "Speed & Switch"
G_PRED = "Prediction"
G_TEXT = "Text box"
G_KEYS = "Keyboard"
G_SOUND = "Sound"
G_COLORS = "Colors"

GROUPS = [G_SPEED, G_PRED, G_TEXT, G_KEYS, G_SOUND, G_COLORS]

SCHEMA = [
    # --- Speed & switch ---
    Setting("SCAN_INTERVAL_SECONDS", "Scan speed: seconds on each highlight", G_SPEED,
            "float", 0.3, 10, 0.1, True,
            hint="How long each row / group / key stays highlighted before moving on. "
                 "Higher = slower."),
    Setting("AFTER_LOCK_SECONDS", "Seconds on the first option after a row/group is chosen", G_SPEED,
            "float", 0.3, 10, 0.1, True,
            hint="Gives time to react after a press, before the highlight moves."),
    Setting("SELECT_PAUSE_SECONDS", "Pause after a key is typed (seconds)", G_SPEED,
            "float", 0, 5, 0.1, True,
            hint="Scanning waits this long after a letter/word is chosen."),
    Setting("AUTO_CANCEL_CYCLES", "Full laps with no press before starting over", G_SPEED,
            "int", 1, 10, 1, True,
            hint="Recovers from choosing the wrong row or group."),
    Setting("SWITCH_KEYSYM", "Switch key", G_SPEED, "keysym",
            hint="Click the button, then press the key to use as the switch."),
    Setting("SWITCH_DEBOUNCE_SECONDS", "Ignore repeat presses within (seconds)", G_SPEED,
            "float", 0, 2, 0.05, True,
            hint="Filters key-repeat and accidental double presses."),
    Setting("PRED_FOCUS_AFTER_WORDS", "Jump to predictions after this many finished words", G_SPEED,
            "int", 0, 10, 1, True, hint="0 turns the jump off."),
    Setting("QUIT_CONFIRM_WINDOW_SECONDS", "Seconds to confirm quitting (Esc twice)", G_SPEED,
            "float", 0.5, 10, 0.5),
    Setting("KIOSK_MODE", "Keep this window on top and reclaim focus", G_SPEED, "bool",
            hint="Turn off if the computer is used for other things between sessions."),

    # --- Prediction ---
    Setting("PREDICTION_MODEL", "Word prediction model", G_PRED, "choice",
            choices=("aac", "care", "social", "brown"),
            hint="aac = everyday conversation, care = needs/comfort/body, "
                 "social = greetings/small talk, brown = old general-English model."),
    Setting("PREDICTION_SLOTS", "Number of word suggestions", G_PRED, "int", 1, 8, 1, True),
    Setting("DICTIONARY_FALLBACK", "Fill empty suggestions from the built-in dictionary", G_PRED,
            "bool"),

    # --- Text box ---
    Setting("TEXT_LINES", "Lines of text shown (1-3)", G_TEXT, "int", 1, 3, 1, True,
            hint="More lines = smaller text in the same-size box. Keys are unchanged."),
    Setting("TEXT_BOX_HEIGHT_FRACTION", "Text box height (fraction of the screen)", G_TEXT,
            "float", 0.08, 0.4, 0.01, True),
    Setting("MAX_TEXT_FONT_SIZE", "Largest text size", G_TEXT, "int", 12, 300, 2),
    Setting("TEXT_HINT_FONT_SIZE", "Size of the '(nothing typed yet)' hint", G_TEXT, "int", 8, 100, 1),
    Setting("CURSOR_WIDTH", "Cursor bar width (px)", G_TEXT, "int", 2, 40, 1),
    Setting("CURSOR_HEIGHT_FRACTION", "Cursor bar height (fraction of a line)", G_TEXT,
            "float", 0.2, 1.0, 0.05, True),
    Setting("CURSOR_GAP", "Gap before the cursor bar (px)", G_TEXT, "int", 0, 40, 1),

    # --- Keyboard ---
    Setting("LETTER_ROWS", "Letter rows (top to bottom)", G_KEYS, "strlist",
            lo=14, count=3,
            hint="One entry per row, one key per character."),
    Setting("BLOCK_SIZE", "Keys per group within a row", G_KEYS, "int", 1, 12, 1, True),
    Setting("BACKSPACE_LABEL", "Label on the delete key", G_KEYS, "text", lo=8),
    Setting("FONT_FAMILY", "Font", G_KEYS, "font"),
    Setting("MAX_KEY_FONT_SIZE", "Largest key text size", G_KEYS, "int", 20, 800, 5),
    Setting("MIN_KEY_FONT_SIZE", "Smallest key text size", G_KEYS, "int", 6, 100, 1),
    Setting("CELL_FIT_WIDTH_FRACTION", "Key text width (fraction of key)", G_KEYS,
            "float", 0.4, 1.0, 0.01, True),
    Setting("CELL_FIT_HEIGHT_FRACTION", "Key text height (fraction of key)", G_KEYS,
            "float", 0.3, 1.0, 0.01, True),
    Setting("CELL_MARGIN", "Gap between keys (px)", G_KEYS, "int", 0, 30, 1, True),

    # --- Sound ---
    Setting("AUDIO_ENABLED", "Sound on", G_SOUND, "bool"),
    Setting("TICK_TONE_HZ", "Scan tick pitch (Hz)", G_SOUND, "int", 37, 32767, 10),
    Setting("TICK_TONE_MS", "Scan tick length (ms)", G_SOUND, "int", 10, 2000, 10),
    Setting("ADVANCE_TONE_HZ", "Row/group chosen pitch (Hz)", G_SOUND, "int", 37, 32767, 10),
    Setting("ADVANCE_TONE_MS", "Row/group chosen length (ms)", G_SOUND, "int", 10, 2000, 10),
    Setting("SELECT_TONE_HZ", "Key typed pitch (Hz)", G_SOUND, "int", 37, 32767, 10),
    Setting("SELECT_TONE_MS", "Key typed length (ms)", G_SOUND, "int", 10, 2000, 10),
    Setting("CONFIRM_TONE_HZ", "Needs-confirmation pitch (Hz)", G_SOUND, "int", 37, 32767, 10),
    Setting("CONFIRM_TONE_MS", "Needs-confirmation length (ms)", G_SOUND, "int", 10, 2000, 10),
    Setting("CANCEL_TONE_HZ", "Start-over pitch (Hz)", G_SOUND, "int", 37, 32767, 10),
    Setting("CANCEL_TONE_MS", "Start-over length (ms)", G_SOUND, "int", 10, 2000, 10),

    # --- Colors ---
    Setting("BG_COLOR", "Screen background", G_COLORS, "color"),
    Setting("TEXT_BUFFER_BG", "Text box background", G_COLORS, "color"),
    Setting("TEXT_COLOR", "Typed text", G_COLORS, "color"),
    Setting("CURSOR_COLOR", "Cursor bar", G_COLORS, "color"),
    Setting("KEY_IDLE_BG", "Key (idle) background", G_COLORS, "color"),
    Setting("KEY_IDLE_FG", "Key (idle) text", G_COLORS, "color"),
    Setting("ROW_SCAN_BG", "Row being scanned: background", G_COLORS, "color"),
    Setting("ROW_SCAN_FG", "Row being scanned: text", G_COLORS, "color"),
    Setting("ROW_LOCKED_BG", "Row chosen: background", G_COLORS, "color"),
    Setting("ROW_LOCKED_FG", "Row chosen: text", G_COLORS, "color"),
    Setting("BLOCK_SCAN_BG", "Group being scanned: background", G_COLORS, "color"),
    Setting("BLOCK_SCAN_FG", "Group being scanned: text", G_COLORS, "color"),
    Setting("KEY_SCAN_BG", "Key being scanned: background", G_COLORS, "color"),
    Setting("KEY_SCAN_FG", "Key being scanned: text", G_COLORS, "color"),
    Setting("FLASH_BG", "Key just typed: background", G_COLORS, "color"),
    Setting("FLASH_FG", "Key just typed: text", G_COLORS, "color"),
]

BY_KEY = {s.key: s for s in SCHEMA}

# What config.py says out of the box (captured before any saved overrides).
DEFAULTS = {s.key: copy.deepcopy(getattr(config, s.key)) for s in SCHEMA}


def model_choices():
    try:
        return _models()
    except Exception:
        return ("aac", "care", "social", "brown")


def _decimals(step):
    text = repr(float(step))
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def format_number(setting, value):
    if setting.kind == "int":
        return str(int(value))
    return f"{float(value):.{_decimals(setting.step)}f}"


def coerce(setting, raw):
    """Validate/convert `raw` for this setting. Raises ValueError if it
    can't be made valid; numbers are clamped to range instead."""
    kind = setting.kind
    if kind in ("float", "int"):
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{setting.label}: not a number")
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{setting.label}: not a number")
        number = max(setting.lo, min(setting.hi, number))
        if setting.step:
            number = round(round(number / setting.step) * setting.step, 6)
            number = max(setting.lo, min(setting.hi, number))
        if kind == "int":
            return int(round(number))
        return round(number, _decimals(setting.step) + 2)
    if kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if kind == "color":
        text = str(raw).strip()
        if _HEX3.match(text):
            text = "#" + "".join(c * 2 for c in text[1:])
        if not _HEX6.match(text):
            raise ValueError(f"{setting.label}: use a color like #1a2b3c")
        return text.lower()
    if kind == "choice":
        choices = model_choices() if setting.key == "PREDICTION_MODEL" else setting.choices
        text = str(raw).strip().lower()
        if text not in choices:
            raise ValueError(f"{setting.label}: must be one of {', '.join(choices)}")
        return text
    if kind == "font":
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{setting.label}: choose a font")
        return text
    if kind == "text":
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{setting.label}: can't be empty")
        return text[: int(setting.lo)] if setting.lo else text
    if kind == "keysym":
        text = str(raw).strip()
        if not text or " " in text:
            raise ValueError(f"{setting.label}: not a valid key name")
        return text
    if kind == "strlist":
        if not isinstance(raw, (list, tuple)) or len(raw) != setting.count:
            raise ValueError(f"{setting.label}: needs {setting.count} entries")
        rows = []
        for item in raw:
            row = "".join(str(item).split()).upper()
            if not row:
                raise ValueError(f"{setting.label}: a row can't be empty")
            rows.append(row[: int(setting.lo)] if setting.lo else row)
        return rows
    raise ValueError(f"Unknown setting kind {kind!r}")


def apply(key, raw):
    """Validate and set one setting live. Returns the stored value."""
    value = coerce(BY_KEY[key], raw)
    setattr(config, key, value)
    if key in ("PREDICTION_SLOTS", "LETTER_ROWS"):
        config.LAYOUT = config.build_layout()
    return value


def current(key):
    return copy.deepcopy(getattr(config, key))


def settings_path():
    return paths.user_path(SETTINGS_FILENAME)


def load(path=None):
    """Apply saved overrides on top of the defaults. Bad or unknown
    entries are skipped; a missing/corrupt file is simply ignored.
    Returns the set of keys that were applied."""
    path = path or settings_path()
    applied = set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return applied
    if not isinstance(data, dict):
        return applied
    for key, raw in data.items():
        if key not in BY_KEY:
            continue
        try:
            apply(key, raw)
            applied.add(key)
        except ValueError:
            pass
    config.LAYOUT = config.build_layout()
    return applied


def save(path=None):
    """Write only the settings that differ from the defaults. Returns
    True on success; failure (read-only folder etc.) is non-fatal."""
    path = str(path or settings_path())
    overrides = {
        s.key: current(s.key) for s in SCHEMA if current(s.key) != DEFAULTS[s.key]
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(overrides, fh, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def reset_all():
    """Put every setting back to its default. Returns all keys."""
    for s in SCHEMA:
        setattr(config, s.key, copy.deepcopy(DEFAULTS[s.key]))
    config.LAYOUT = config.build_layout()
    return {s.key for s in SCHEMA}
