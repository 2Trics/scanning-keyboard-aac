"""Row -> block -> key scanning state machine for a switch-accessible
keyboard. Pure logic, no GUI dependency, so it's independently testable.

At all times exactly one thing is auto-advancing (call tick() on a timer):
rows, then (once a row is locked) blocks of up to BLOCK_SIZE keys within
that row, then (once a block is locked) the individual keys within that
block. A single switch press (call select()) locks in whatever is
currently highlighted and drops one level deeper.

If a row is already a single block (len(row) <= BLOCK_SIZE) -- the
prediction row and the SPACE/DEL/ENTER/CLEAR row -- locking the row skips
the group stage and starts scanning keys immediately. Those keys take 2
presses (row, then key). Longer rows still take 3 (row, block, key).

Recovering from an accidental lock: once a row or block is locked in,
there's no direct "go back one level" -- instead, if the scan completes
AUTO_CANCEL_CYCLES full passes through the current block/key list with no
press, the whole thing resets back to scanning rows from the top, same as
if nothing had ever been locked in. This is the same rule at both levels --
a row locked with no block chosen in time, or a block locked with no key
chosen in time, both just start over from the top row. This avoids having
to complete a wrong selection (and backspace it out) just to recover from
locking the wrong row or block.
"""

import config

STAGE_ROW = "row"
STAGE_BLOCK = "block"
STAGE_KEY = "key"


class Scanner:
    def __init__(self, layout):
        """layout: list of rows, each row a list of key labels."""
        self._validate(layout)
        self.layout = [list(row) for row in layout]
        self.reset()

    @staticmethod
    def _validate(layout):
        """Fails fast with a clear message on a bad LAYOUT/BLOCK_SIZE in
        config.py, instead of an unrelated-looking ZeroDivisionError or
        ValueError surfacing later, mid-scan, from deep inside tick()."""
        if not layout:
            raise ValueError("config.LAYOUT must have at least one row.")
        for i, row in enumerate(layout):
            if not row:
                raise ValueError(
                    f"config.LAYOUT row {i} is empty -- every row needs at least one key."
                )
        if config.BLOCK_SIZE < 1:
            raise ValueError(
                f"config.BLOCK_SIZE must be at least 1 (got {config.BLOCK_SIZE})."
            )

    def reset(self, dwell=False):
        self.stage = STAGE_ROW
        self.row_index = 0
        self.block_index = 0
        self.key_index = 0
        self.laps_at_stage = 0
        # If True, the next tick() leaves the highlight where it is so the
        # starting row gets a full scan interval instead of being skipped.
        self._dwell = dwell

    def blocks_for_row(self, row_index):
        row = self.layout[row_index]
        size = config.BLOCK_SIZE
        return [row[i:i + size] for i in range(0, len(row), size)]

    def is_single_block_row(self, row_index):
        return len(self.blocks_for_row(row_index)) == 1

    def start_at_prediction_row(self):
        """Restart row-scan on the top (prediction) row and give it a full
        dwell so the first timer tick does not skip past it."""
        self.reset(dwell=True)

    def tick(self):
        """Advances the scan by one step. Call this on a timer. Returns
        "reset" if this tick's timeout reset scanning all the way back to
        the top row (see module docstring), or None for a normal step."""
        if self._dwell:
            self._dwell = False
            return None

        if self.stage == STAGE_ROW:
            self.row_index = (self.row_index + 1) % len(self.layout)
            return None

        if self.stage == STAGE_BLOCK:
            blocks = self.blocks_for_row(self.row_index)
            self.block_index = (self.block_index + 1) % len(blocks)
            wrapped = self.block_index == 0
        else:  # STAGE_KEY
            block = self.blocks_for_row(self.row_index)[self.block_index]
            self.key_index = (self.key_index + 1) % len(block)
            wrapped = self.key_index == 0

        if not wrapped:
            return None

        self.laps_at_stage += 1
        if self.laps_at_stage < config.AUTO_CANCEL_CYCLES:
            return None

        self.reset()
        return "reset"

    def select(self):
        """Handles one switch press at the current stage. Returns the
        selected key label once a key has been chosen, or None if this
        press only locked in a row/block (and scanning has moved one
        level deeper). A single-block row skips the group stage."""
        if self.stage == STAGE_ROW:
            self.block_index = 0
            self.key_index = 0
            self.laps_at_stage = 0
            if self.is_single_block_row(self.row_index):
                self.stage = STAGE_KEY
            else:
                self.stage = STAGE_BLOCK
            return None
        if self.stage == STAGE_BLOCK:
            self.stage = STAGE_KEY
            self.key_index = 0
            self.laps_at_stage = 0
            return None
        # STAGE_KEY
        block = self.blocks_for_row(self.row_index)[self.block_index]
        selected = block[self.key_index]
        self.reset()
        return selected

    def current_highlight(self):
        """Returns {'stage', 'row', 'block', 'key'} describing what should
        be visually highlighted right now. 'block'/'key' are None until
        that level is being scanned."""
        return {
            "stage": self.stage,
            "row": self.row_index,
            "block": self.block_index if self.stage != STAGE_ROW else None,
            "key": self.key_index if self.stage == STAGE_KEY else None,
        }
