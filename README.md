# DISCLAIMER
AI vibe coded. It works, and that's all that matters. 

The best version is in the v2 folder, just download the folder and run main. A more intuitive version is located in dist folder in the form of an application, but hasn't been updated with the latest version of the code yet.

I hope this project will help those who need it. 

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

### Predictive text

The top row is four word-prediction slots — the same group size as every
other scan block (`BLOCK_SIZE` is 4, and long words would not fit more
slots). It starts blank. Once anything is typed, an NLTK trigram model
fills those four slots. `PREDICTION_MODEL` in [config.py](config.py) chooses
which n-gram to use:

- `aac` (default) — modern conversational English for someone who still
  thinks in full sentences: questions, opinions, family, daily life,
  health, and body parts. Plus a large everyday vocabulary so prefixes
  can complete many more words than the old short seed list.
- `brown` — leftover general-English trigram from NLTK's Brown corpus
  (old newspaper wording; not recommended).
- `care` / `social` — narrower slices. Add more in `aac_sentences.CORPORA`.

Completed lines (Enter) are added to **that model's** live counts only.

- Mid-word, they complete the current prefix (`TH` → THE, THAT, THANK, …).
- After a space, they suggest the next word given what came before.

Selecting a suggestion replaces the unfinished word (or appends after a
finished one) and adds a trailing space, then scanning restarts from the
top like any other key. Blank slots can still be scanned but insert
nothing if selected.

### Recovering from an accidental lock

Locking in the wrong row or block (an early or mistimed press) used to mean
either completing a wrong selection and backspacing it out, or waiting for
someone to intervene. Now, if 3 full sweeps pass with **no press at all**,
scanning automatically resets all the way back to the top row — same rule
whichever level it happens at, a row locked with no block chosen, or a
block locked with no key chosen (a low double-beep marks it). No button
needed to "go back"; just don't press, and it starts over on its own.

### Other safety behaviors

A few more things guard against realistic accidents, given how much effort
typing anything here represents and how the app is meant to run unattended
for long stretches:

- **CLEAR requires confirmation.** Selecting CLEAR the first time doesn't
  erase anything yet — it arms a pending confirmation (amber flash, a
  higher "waiting" tone instead of the normal select tone). Selecting
  CLEAR again actually clears; selecting anything else first cancels the
  pending clear and proceeds normally. One accidental CLEAR selection can
  no longer destroy a whole typed message.
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

## Run it (from source)

```bash
cd scanning-keyboard
python -m pip install -r requirements.txt
python main.py
```

The first source launch trains the n-gram model from local sentence files
and reuses a cache after that. **nltk** is the extra Python dependency;
Tkinter and `winsound` are standard-library. Nothing is downloaded at
runtime — the tokenizer is either already on the machine, bundled in the
packaged app, or the app falls back to a simple offline splitter.

Press **Escape** twice to quit the full-screen window.

## Packaged app (offline, no Python)

To give this to someone else as a double-click Windows app:

```bash
python -m pip install -r requirements-build.txt
python build_app.py
```

That builds a single file, `dist/ScanningKeyboard.exe`. Send just that
`.exe`. The other computer does not need Python or the internet: tokenizer
data and the trained word-prediction caches are packed inside. Double-click
to launch (the first start can take a few extra seconds while it unpacks).

Windows may show a SmartScreen warning on an unsigned app — choose
**More info** → **Run anyway** if that appears.

Learned sentences (Enter) are saved under the user's
`%LOCALAPPDATA%\ScanningKeyboard` folder so they survive app updates.

## Using a different switch

The switch key is whatever a connected USB assistive switch is configured
to send — currently Enter. To use a different key, change `SWITCH_KEYSYM`
in [config.py](config.py) — it accepts any Tk keysym name, e.g. `"space"`
for the space bar, or `"F1"`.

## Tuning

Everything is a named constant in [config.py](config.py):

- `SCAN_INTERVAL_SECONDS` (default 2.1s) — how long each row/block/key is
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
- `AUTO_CANCEL_CYCLES` (default 3) — how many full passes through a locked
  block/key list with no press before that level gives up (see above).
  Lower it to recover from a mistake faster; raise it if it's giving up
  before there's been a real chance to react and press.
- `LAYOUT` — the keyboard itself: a list of rows, each a list of key
  labels. Row 0 is the four-slot prediction row. `SPACE`, `BACKSPACE`,
  `ENTER`, and `CLEAR` are handled specially; every other label is typed
  literally.
- `PREDICTION_SLOTS` (default 4) — how many word suggestions to show.
  Kept at 4 so the prediction row is exactly one scan block (`BLOCK_SIZE`).
- `PRED_FOCUS_AFTER_WORDS` (default 1) — after this many finished words
  on the current line, scanning restarts on the prediction row. Set to 0
  to turn that off.
- `PREDICTION_MODEL` (default `"aac"`) — which n-gram fills those slots:
  `"aac"`, `"brown"`, `"care"`, `"social"`, or any extra key you add in
  `aac_sentences.CORPORA`. Restart after changing it.
- `QUIT_CONFIRM_WINDOW_SECONDS` (default 2.0) — how long a second Escape
  press has to arrive after the first to actually quit.
- `CLEAR_CONFIRM_WINDOW_SECONDS` (default 60) — a generous safety-net
  expiry for a pending CLEAR confirmation; rarely needs changing since
  selecting any other key already cancels it immediately.
- `KIOSK_MODE` (default True) — keeps the window always-on-top and
  reclaims keyboard focus if it's lost. Set to False if this machine is
  shared with other uses between sessions.
- Colors, fonts, and audio tones are all there too.

## Project layout

- `scanner.py` — the row/block/key state machine: `tick()` advances the
  auto-scan, `select()` handles a switch press. Pure logic, no GUI code, so
  it's testable on its own (and was — including wraparound at all three
  levels and every key across the layout selecting in exactly 3 presses).
- `predictor.py` — NLTK n-gram word prediction (trigram with backoff).
- `aac_sentences.py` / `conversational_english.py` — modern conversation
  sentences, body-part language, and everyday vocabulary.
- `main.py` — the Tkinter full-screen UI: renders the keyboard and text
  buffer on a canvas, redrawn on every scan tick and every press, and wires
  up the switch key with debounce and the post-selection pause.
- `config.py` — every tunable value described above.
- `build_app.py` — PyInstaller offline Windows build.
- `requirements-build.txt` — `nltk` plus PyInstaller.
