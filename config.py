"""Tunables for the switch-scanning virtual keyboard."""

# --- Keyboard layout ---
# Rows of keys; each row is scanned in chunks of BLOCK_SIZE for the second
# scan stage. Row/chunk lengths don't need to divide evenly -- the last
# chunk in a row just has fewer keys.
# Row 0 is the predictive-text row: four slots (one scan block) that start
# blank and fill with n-gram word suggestions as text is typed. Labels use
# PRED_PREFIX so a predicted English word can never collide with SPACE /
# ENTER / CLEAR / a letter key.
PRED_PREFIX = "__PRED__:"
PREDICTION_SLOTS = 4
# Which n-gram fills the prediction row. Restart the app after changing this.
#   "aac"    — modern conversational English (recommended default)
#   "brown"  — original general-English model (NLTK Brown corpus)
#   "care"   — needs / comfort / body / environment
#   "social" — greetings / yes-no / family / small talk
# Add another conversation type in aac_sentences.CORPORA, then put its name here.
PREDICTION_MODEL = "aac"
LAYOUT = [
    [PRED_PREFIX] * PREDICTION_SLOTS,
    list("ABCDEFGHIJ"),
    list("KLMNOPQRS"),
    list("TUVWXYZ"),
    ["SPACE", "BACKSPACE", "ENTER", "CLEAR"],
]
BLOCK_SIZE = 4
# After this many finished words on the current line, scanning restarts
# on the prediction row (so next-word suggestions are first). 0 turns
# this off. Default 1: after "HOW " the bar is waiting with ARE / IS / ...
PRED_FOCUS_AFTER_WORDS = 1

# What to actually draw for a key, if different from its LAYOUT/logic name.
# "BACKSPACE" is far longer than its row-mates (SPACE/ENTER/CLEAR), which
# would force every key's font size down to fit it -- a shorter label lets
# the whole keyboard render bigger. Plain ASCII on purpose (not a symbol
# glyph like an erase arrow), since not every font/system is guaranteed to
# have one, and a missing glyph shows up as an unreadable box. The LAYOUT
# value is still what main.py's key-handling logic matches against, so this
# is display-only.
DISPLAY_LABELS = {
    "BACKSPACE": "DEL",
}


def display_label(label):
    """What to draw on a key. Prediction slots show the word (or blank)."""
    if label.startswith(PRED_PREFIX):
        return label[len(PRED_PREFIX):]
    return DISPLAY_LABELS.get(label, label)

# --- Switch input ---
# The single key that acts as the "switch". Pressing it advances the
# selection: row -> block -> key. Tkinter keysym name (see Tk docs) -- e.g.
# "space" for the space bar, "Return" for Enter.
SWITCH_KEYSYM = "Return"
# Minimum time between accepted switch presses. Filters out OS key-repeat
# from a held-down key, and accidental rapid double-presses from tremor.
SWITCH_DEBOUNCE_SECONDS = 0.35

# --- Scan timing ---
# Seconds each row/block/key is highlighted before the scan automatically
# moves to the next one.
SCAN_INTERVAL_SECONDS = 2.1
# After locking a row or a block, wait this long on the *first* option of
# the new stage before auto-advancing. The scan clock used to keep running
# across the press, so the first word/key could get only a fraction of a
# second. This timer starts fresh on every lock. The switch still works
# during this wait (unlike SELECT_PAUSE_SECONDS). Raise it if reaction
# after a press needs more time; SCAN_INTERVAL_SECONDS still controls
# every step after the first.
AFTER_LOCK_SECONDS = 2.5
# After a key is selected, pause scanning (and ignore further switch
# presses) for this long so the selection is clearly visible/audible before
# scanning resumes from the top row.
SELECT_PAUSE_SECONDS = 0.9

# --- Auto-cancel (recovering from an accidental row/block lock) ---
# If the scan completes this many full passes through the current block or
# key list with no switch press, scanning resets all the way back to the
# top row -- same rule whether a row was locked with no block chosen, or a
# block was locked with no key chosen. No wrong selection needs to be
# completed and backspaced out just to recover from locking onto the wrong
# row or block. Counted in full laps (not raw ticks) so it always allows a
# full look at every option in the segment, however many there are, before
# giving up -- stays correct even if SCAN_INTERVAL_SECONDS is changed later.
AUTO_CANCEL_CYCLES = 2

# --- Destructive-action confirmation ---
# CLEAR wipes the whole typed message, which can represent real effort --
# every character here costs 3 presses plus scan wait time -- so a single
# accidental selection shouldn't be able to destroy it. The first CLEAR
# selection only arms a pending confirmation (distinct amber flash/tone,
# nothing cleared yet); selecting CLEAR again actually clears. Selecting
# any other key first cancels the pending clear and proceeds normally.
# CLEAR_CONFIRM_WINDOW_SECONDS is a generous safety-net expiry, not the
# primary mechanism -- reaching CLEAR a second time on purpose takes a full
# row->block->key re-scan, which can take longer than a short window.
CLEAR_CONFIRM_WINDOW_SECONDS = 60

# Quitting the fullscreen app (Escape) is similarly guarded: one press just
# arms a confirmation; a second Escape within this window actually quits.
# Protects an unattended session from being silently killed by a single
# stray keypress near the machine.
QUIT_CONFIRM_WINDOW_SECONDS = 2.0

# --- Focus (keeping the switch actually reaching this window) ---
# If any other window/dialog on the machine steals keyboard focus (an OS
# notification, a screensaver, an accidental click), switch presses would
# silently go nowhere -- no error, no feedback, just an unresponsive
# keyboard. KIOSK_MODE keeps this window always on top and immediately
# reclaims focus if it's lost. Turn this off (False) if the same machine is
# also used for other things between sessions, since it will otherwise
# fight you for focus.
KIOSK_MODE = True

# --- Audio feedback (Windows only, via the stdlib winsound module; no-ops
# silently on any platform where it's unavailable) ---
AUDIO_ENABLED = True
TICK_TONE_HZ = 480
TICK_TONE_MS = 60
ADVANCE_TONE_HZ = 700
ADVANCE_TONE_MS = 90
SELECT_TONE_HZ = 900
SELECT_TONE_MS = 180
# Played once for an action that's only pending confirmation (first CLEAR
# press, first Escape press) -- higher and shorter than SELECT_TONE so it
# reads as "waiting for you to confirm", not "done".
CONFIRM_TONE_HZ = 550
CONFIRM_TONE_MS = 140
# Played twice, back to back, when an auto-cancel timeout resets scanning
# all the way back to the top row -- deliberately the lowest-pitched cue in
# the app so it's unmistakably "gave up, starting over" rather than a
# normal scan step.
CANCEL_TONE_HZ = 260
CANCEL_TONE_MS = 110

# --- Appearance ---
# Tuned for viewing a TV from ~10 feet: pure black background, maximally
# saturated highlight colors (same logic as road/hazard signage), and text
# color chosen per-background so it's always the darker or lighter extreme
# rather than a blanket "white on everything" (white gets washed out on the
# brighter highlight colors like yellow/orange).
BG_COLOR = "#000000"
TEXT_BUFFER_BG = "#141414"
TEXT_COLOR = "#ffffff"

KEY_IDLE_BG = "#202020"
KEY_IDLE_FG = "#ffffff"

ROW_SCAN_BG = "#0074ff"      # a row is currently being auto-scanned
ROW_SCAN_FG = "#ffffff"
ROW_LOCKED_BG = "#00305e"    # this row is locked in; other keys in it while scanning blocks/keys
ROW_LOCKED_FG = "#ffffff"

BLOCK_SCAN_BG = "#ff8c00"    # the block currently being auto-scanned within the locked row
BLOCK_SCAN_FG = "#000000"

KEY_SCAN_BG = "#ffff00"      # the single key currently being auto-scanned within the locked block
KEY_SCAN_FG = "#000000"

FLASH_BG = "#00e64d"         # brief confirmation flash on the key that was just selected
FLASH_FG = "#000000"
CONFIRM_FLASH_BG = "#ff9500" # flash for an action that's only pending confirmation (e.g. first CLEAR press)
CONFIRM_FLASH_FG = "#000000"

FONT_FAMILY = "Segoe UI"
# Key/text labels are auto-sized per cell at render time (see main.py) to
# always fill as much of the available space as possible, on any screen --
# these are just the search bounds and safety margin for that fit.
MAX_KEY_FONT_SIZE = 400
MIN_KEY_FONT_SIZE = 16
MAX_TEXT_FONT_SIZE = 120
CELL_FIT_WIDTH_FRACTION = 0.88   # leave a little breathing room, don't fill 100% of cell width
CELL_FIT_HEIGHT_FRACTION = 0.72  # font linespace includes ascent/descent taller than visible glyphs
CELL_MARGIN = 6                  # gap (px) between adjacent key cells, for a clearer boundary at a distance
