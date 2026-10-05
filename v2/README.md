# Scanning Keyboard

A full-screen, high-contrast on-screen keyboard operated with a **single
key** — built for someone who can reliably press only one switch (default:
Enter). This uses row/block/key group scanning, the same technique behind
most AAC (augmentative communication) switch-access devices.

No camera, no pen, no calibration. Just one key.

## How it works

The app is always auto-scanning something, highlighting it for about a
second before moving on:

1. **Rows** are highlighted one at a time, cycling continuously. Press the
   switch (Enter) to lock in whichever row is currently highlighted.
2. Within that row, **blocks of up to 4 keys** are highlighted one at a
   time. Press the switch to lock in the highlighted block. If the row
   already has only 4 keys (prediction row, or SPACE/DEL/ENTER/CLEAR),
   this step is skipped — locking the row starts scanning those keys
   immediately.
3. Within that block, **individual keys** are highlighted one at a time.
   Press the switch to select the highlighted key.

The key is typed, there's a brief green confirmation flash, and scanning
restarts. Letter rows still take 3 presses (row, block, key). The top and
bottom rows take 2 (row, then key). After the first finished word,
scanning restarts on the prediction row so next-word suggestions (HOW →
ARE) are first.

If nothing is pressed, the scan just keeps looping through rows forever —
there's no rush and no wrong state to get stuck in.

Letters are laid out alphabetically (A–J, K–T, U–Z), not in QWERTY order,
so the scan sequence for any letter is predictable without needing to know
a keyboard layout.

### Predictive text

The top row is four word-prediction slots — the same group size as every
other scan block (`BLOCK_SIZE` is 4, and long words would not fit more
slots). It starts blank. Once anything is typed, suggestions are filled by
two combined layers in `predictor.py`:

1. **Conversational model (ranked first).** An n-gram (trigram with
   backoff) trained on `PREDICTION_MODEL`'s seed sentences in
   `aac_sentences.py`, plus anything the user has actually finished typing
   in this session. This is what makes "HOW" suggest "ARE" next, and why
   frequently-used words surface before rare ones.
2. **Offline dictionary (fills remaining slots).** A bundled ~77,000-word
   list (`dictionary_words.txt`, derived from a standard spell-check
   dictionary) is used only to top up empty suggestion slots the
   conversational model doesn't have data for. This fixes short/uncommon
   prefixes returning only 0–1 suggestions even though real words exist —
   e.g. typing `BLU` used to show nothing; it now offers `BLUE`, `BLUR`,
   `BLURRED`, `BLURRY`, etc. Known conversational words always outrank
   dictionary fill-ins; the dictionary never buries something the person
   actually says often.

`PREDICTION_MODEL` in [config.py](config.py) chooses which n-gram corpus
seeds the conversational layer:

- `aac` (default) — modern conversational English for someone who still
  thinks in full sentences: questions, opinions, family, daily life,
  health, and body parts.
- `brown` — leftover general-English trigram from NLTK's Brown corpus, if
  already cached locally (old newspaper wording; not recommended, and
  silently falls back to `aac` if the corpus isn't available offline).
- `care` / `social` — narrower slices. Add more in `aac_sentences.CORPORA`.

Set `DICTIONARY_FALLBACK = False` in `config.py` to disable the dictionary
layer entirely and go back to conversational-only suggestions.

Completed lines (Enter) are added to **that model's** live counts only.

- Mid-word, they complete the current prefix (`TH` → THE, THAT, THANK, …,
  falling back to the dictionary for anything past what's been said
  before).
- After a space, they suggest the next word given what came before
  (conversational model only — the dictionary has no sense of what word
  naturally follows another, so it never contributes here).

Selecting a suggestion replaces the unfinished word (or appends after a
finished one) and adds a trailing space, then scanning restarts from the
top like any other key. Blank slots can still be scanned but insert
nothing if selected.

### The cursor

A solid bar is always shown right after the last typed character (or at
the very start, if nothing's been typed yet). This is what makes a SPACE
visible: a trailing space is otherwise just blank canvas, indistinguishable
from nothing having happened, but the cursor visibly jumps right when one's
typed. It's static, not blinking, so it's easy to spot at a glance from
across a room without any flashing on screen.

### Recovering from an accidental lock

Locking in the wrong row or block (an early or mistimed press) used to mean
either completing a wrong selection and backspacing it out, or waiting for
someone to intervene. Now, if 2 full sweeps pass with **no press at all**,
scanning automatically resets all the way back to the top row — same rule
whichever level it happens at, a row locked with no block chosen, or a
block locked with no key chosen (a low double-beep marks it). No button
needed to "go back"; just don't press, and it starts over on its own.

### Other safety behaviors

A few more things guard against realistic accidents, given how much effort
typing anything here represents and how the app is meant to run unattended
for long stretches:

- **Quitting needs two Escape presses** within 2 seconds — one stray
  keypress near the machine can't silently kill an otherwise-unattended
  session. The first press just beeps; nothing happens until the second.
- **The window fights to keep keyboard focus** (`KIOSK_MODE` in
  `config.py`, on by default): it stays on top and immediately reclaims
  focus if anything else steals it (an OS notification, a screensaver,
  an accidental click elsewhere). Without this, switch presses would
  silently go to whatever else has focus instead — no error, just an
  unresponsive keyboard with no indication why. Turn `KIOSK_MODE` off if
  the same machine is also used for other things between sessions, since
  it will otherwise fight you for focus.
- **A misconfigured layout fails immediately with a clear message**
  instead of crashing later mid-scan. If `config.py` is edited (e.g. while
  extending this into `scanning-keyboard2`) and ends up with an empty row
  or an invalid `BLOCK_SIZE`, the app refuses to start and says exactly
  what's wrong, rather than crashing unpredictably during actual use.
- **Fully offline, always.** If NLTK or its tokenizer data isn't
  installed/cached, prediction quietly falls back to a built-in tokenizer
  instead of trying (and hanging on) a network download — startup is
  never delayed by a missing internet connection.

## Run it

```bash
cd scanning-keyboard/v2
python -m pip install -r requirements.txt
python main.py
```

The first launch trains the n-gram model (and tries, briefly and
non-blockingly, to use NLTK's `punkt` tokenizer if it's already cached);
later launches reuse a local cache. Tkinter and `winsound` remain
standard-library; **nltk** is an optional extra — if it isn't installed or
there's no cached tokenizer data, a built-in tokenizer is used instead and
everything still works fully offline.

Press **Escape** to quit the full-screen window.

## Using a different switch

The switch key is whatever a connected USB assistive switch is configured
to send — currently Enter. To use a different key, change `SWITCH_KEYSYM`
in [config.py](config.py) — it accepts any Tk keysym name, e.g. `"space"`
for the space bar, or `"F1"`.

## Tuning

Everything is a named constant in [config.py](config.py):

- `SCAN_INTERVAL_SECONDS` (default 2s) — how long each row/block/key is
  highlighted before automatically moving to the next.
- `AFTER_LOCK_SECONDS` (default 2.5s) — extra/fresh dwell on the **first**
  option after locking a row or block. The old timer kept running through
  the press, so the first word could vanish almost immediately. The switch
  still works during this wait. Raise it if reaction after a press is slow.
- `SWITCH_DEBOUNCE_SECONDS` (default 0.35s) — minimum gap between accepted
  presses. This is what prevents a held-down key (OS key-repeat) or a
  tremor-driven double-tap from registering as two separate presses.
- `SELECT_PAUSE_SECONDS` (default 0.9s) — after a key is chosen, scanning
  pauses this long (with a green flash and confirmation tone) before
  restarting, and any switch press during that window is ignored so a
  reflexive extra press right after selecting doesn't start a new
  selection early.
- `BLOCK_SIZE` (default 4) — how many keys are grouped per block in the
  second scan stage, per your original spec. Smaller blocks mean more
  presses to reach far rows/positions but fewer keys to visually track at
  the third (individual-key) stage.
- `AUTO_CANCEL_CYCLES` (default 2) — how many full passes through a locked
  block/key list with no press before that level gives up (see above).
  Lower it to recover from a mistake faster; raise it if it's giving up
  before there's been a real chance to react and press.
- `LAYOUT` — the keyboard itself: a list of rows, each a list of key
  labels. Row 0 is the four-slot prediction row. `SPACE`, `BACKSPACE`,
  `ENTER`, and `CLEAR` are handled specially; every other label is typed
  literally.
- `PREDICTION_SLOTS` (default 4) — how many word suggestions to show.
  Kept at 4 so the prediction row is exactly one scan block (`BLOCK_SIZE`).
- `PREDICTION_MODEL` (default `"aac"`) — which n-gram fills those slots:
  `"aac"`, `"brown"`, `"care"`, `"social"`, or any extra key you add in
  `aac_sentences.CORPORA`. Restart after changing it.
- `DICTIONARY_FALLBACK` (default `True`) — whether the bundled ~77k-word
  offline dictionary tops up empty prediction slots when the
  conversational model doesn't have enough data for the current prefix.
  Set to `False` to show only words actually seen in conversation.
- `QUIT_CONFIRM_WINDOW_SECONDS` (default 2.0) — how long a second Escape
  press has to arrive after the first to actually quit.
- `KIOSK_MODE` (default True) — keeps the window always-on-top and
  reclaims keyboard focus if it's lost. Set to False if this machine is
  shared with other uses between sessions.
- Colors, fonts, and audio tones are all there too.

## Project layout

- `scanner.py` — the row/block/key state machine: `tick()` advances the
  auto-scan, `select()` handles a switch press. Pure logic, no GUI code, so
  it's testable on its own (and was — including wraparound at all three
  levels and every key across the layout selecting in exactly 3 presses).
- `predictor.py` — word prediction: an NLTK-tokenized (with a built-in
  fallback tokenizer) n-gram model for conversational ranking, combined
  with a bundled offline dictionary (`dictionary_words.txt`) that fills
  in prefix completions the conversational model hasn't seen, so short or
  uncommon prefixes still return real word options instead of going
  nearly empty.
- `dictionary_words.txt` — bundled offline word list (~77,000 entries)
  used as the fallback vocabulary layer in `predictor.py`. Plain text, one
  lowercase word per line; safe to edit or extend by hand.
- `aac_sentences.py` — seed conversational training sentences.
- `main.py` — the Tkinter full-screen UI: renders the keyboard and text
  buffer on a canvas, redrawn on every scan tick and every press, and wires
  up the switch key with debounce and the post-selection pause.
- `config.py` — every tunable value described above.
- `requirements.txt` — `nltk` (optional; the app runs fully offline
  without it, using a built-in tokenizer instead).
