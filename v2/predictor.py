"""
predictor.py — word prediction for the scanning keyboard.

Two layers, combined:
  1. A live n-gram (trigram-with-backoff) model trained on conversational
     AAC sentences (config.PREDICTION_MODEL picks which corpus). This
     ranks words by how naturally they follow the current context, and is
     what makes "HOW" suggest "ARE" next, and learns from what the user
     actually finishes typing (see observe()).
  2. A large bundled offline dictionary (~77k words, dictionary_words.txt,
     derived from a standard spell-check word list) used to fill in
     prefix completions the conversational model hasn't seen enough of.
     This fixes cases like "blu" coming back with 0-1 suggestions even
     though "blue" and "blurry" are perfectly ordinary words — a rare
     prefix is never starved for options just because it's uncommon in
     the seed sentences. Conversational/context-known words are always
     ranked first; the dictionary only fills empty slots.

Everything is 100% offline. NLTK is optional and used only if it's
already installed and its tokenizer data is already cached; if not
available (no install, or no network to fetch it), a small built-in
regex tokenizer and the same n-gram logic are used instead, so the app
still runs with no network and no extra libraries beyond the standard
library plus whatever NLTK cache already exists.
"""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

import config
from aac_sentences import CORPORA

# --------------------------------------------------------------------------
# Optional NLTK — never allowed to block startup or crash if unavailable.
# --------------------------------------------------------------------------

_NLTK_OK = False
try:
    import nltk
    from nltk.tokenize import word_tokenize as _nltk_word_tokenize

    def _ensure_punkt():
        """True if NLTK's tokenizer data is already on this machine. Never
        downloads: the app must not depend on a network connection."""
        for resource in ("tokenizers/punkt_tab", "tokenizers/punkt"):
            try:
                nltk.data.find(resource)
                return True
            except LookupError:
                continue
        return False

    _NLTK_OK = _ensure_punkt()
except Exception:
    _NLTK_OK = False


_WORD_RE = re.compile(r"[A-Za-z']+")


def _tokenize(text: str):
    """Lowercase word tokens. Uses NLTK if it's actually working; falls
    back to a plain regex split otherwise (fine for short AAC sentences,
    and never dependent on a network connection)."""
    if _NLTK_OK:
        try:
            return [w.lower() for w in _nltk_word_tokenize(text) if _WORD_RE.fullmatch(w)]
        except Exception:
            pass
    return [w.lower() for w in _WORD_RE.findall(text)]


# --------------------------------------------------------------------------
# Bundled offline dictionary (fallback vocabulary)
# --------------------------------------------------------------------------

_DICT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictionary_words.txt")


def _load_dictionary(path):
    """Load the bundled word list. Missing file just means the fallback
    layer is empty — the conversational model still works on its own."""
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


_DICTIONARY_WORDS = _load_dictionary(_DICT_PATH)

# Bucketed by first letter so a keystroke doesn't linearly scan all ~77k
# words — only the ones that could possibly match.
_DICTIONARY_BY_LETTER = defaultdict(list)
for _w in _DICTIONARY_WORDS:
    _DICTIONARY_BY_LETTER[_w[0]].append(_w)


# --------------------------------------------------------------------------
# N-gram model
# --------------------------------------------------------------------------

class NGramModel:
    """Trigram-with-backoff predictor, trained from seed sentences and
    grown online from whatever the user finishes typing.

    - unigrams: overall word frequency (fallback ranking, and completions
      of a fresh prefix rank on how often the word has actually been used)
    - bigrams: word -> next word
    - trigrams: (word, word) -> next word
    """

    def __init__(self, weighted_sentences=(), vocab=()):
        self.unigrams = Counter()
        self.bigrams = defaultdict(Counter)
        self.trigrams = defaultdict(Counter)
        self.vocab = set()
        for sentence, weight in weighted_sentences:
            self.observe(sentence, weight)
        for word in vocab:
            w = str(word).lower()
            if _WORD_RE.fullmatch(w):
                self.unigrams[w] += 1
                self.vocab.add(w)

    def observe(self, sentence: str, weight: int = 1):
        tokens = _tokenize(sentence)
        if not tokens:
            return
        for w in tokens:
            self.unigrams[w] += weight
            self.vocab.add(w)
        for i in range(len(tokens) - 1):
            self.bigrams[tokens[i]][tokens[i + 1]] += weight
        for i in range(len(tokens) - 2):
            self.trigrams[(tokens[i], tokens[i + 1])][tokens[i + 2]] += weight

    def next_words(self, context_tokens, n):
        """Rank candidate next words, backing off trigram -> bigram ->
        unigram as context runs out of data."""
        scored = Counter()

        if len(context_tokens) >= 2:
            key = (context_tokens[-2], context_tokens[-1])
            for w, c in self.trigrams.get(key, {}).items():
                scored[w] += c * 1_000_000

        if context_tokens:
            for w, c in self.bigrams.get(context_tokens[-1], {}).items():
                scored[w] += c * 1_000

        if len(scored) < n:
            for w, c in self.unigrams.most_common():
                if w not in scored:
                    scored[w] += c
                if len(scored) >= n * 4:  # plenty of headroom, stop early
                    break

        return [w for w, _ in scored.most_common(n)]

    def prefix_words(self, prefix, n, context_tokens=()):
        """Vocabulary words starting with prefix. Words that follow the
        preceding one or two words rank first (so "I W" favors WANT),
        then most-used overall. Only searches vocab actually seen in
        conversation — the "known and preferred" layer."""
        tri = {}
        bi = {}
        if len(context_tokens) >= 2:
            tri = self.trigrams.get((context_tokens[-2], context_tokens[-1]), {})
        if context_tokens:
            bi = self.bigrams.get(context_tokens[-1], {})
        matches = [w for w in self.vocab if w != prefix and w.startswith(prefix)]
        matches.sort(key=lambda w: (-tri.get(w, 0), -bi.get(w, 0), -self.unigrams[w], len(w), w))
        return matches[:n]


# --------------------------------------------------------------------------
# Public predictor
# --------------------------------------------------------------------------

PRIORITY_WEIGHT = 8
SEED_WEIGHT = 3
USER_WEIGHT = 5

_HERE = os.path.dirname(os.path.abspath(__file__))


class Predictor:
    def __init__(self, model_name=None):
        model_name = (model_name or getattr(config, "PREDICTION_MODEL", "aac")).strip().lower()
        self.model_name = model_name
        self.slots = getattr(config, "PREDICTION_SLOTS", 4)
        self.dictionary_enabled = getattr(config, "DICTIONARY_FALLBACK", True)
        self._user_path = os.path.join(_HERE, f"user_sentences_{model_name}.txt")

        weighted, vocab = self._seed(model_name)
        weighted += [(s, USER_WEIGHT) for s in self._read_user_sentences()]
        self.model = NGramModel(weighted, vocab)

    @staticmethod
    def _seed(model_name):
        """(weighted_sentences, vocab) for a model. CORPORA entries are dicts
        of priority sentences, regular sentences, and extra vocabulary."""
        if model_name == "brown":
            # Legacy option: NLTK's Brown corpus, only if it's already on
            # this machine. Never downloaded — falls back to aac otherwise.
            try:
                import nltk
                from nltk.corpus import brown

                nltk.data.find("corpora/brown")
                return [(" ".join(s), 1) for s in brown.sents()], []
            except Exception:
                model_name = "aac"

        corpus = CORPORA.get(model_name, CORPORA["aac"])
        priority = corpus.get("priority") or []
        sentences = corpus.get("sentences") or []
        seen = {s.strip().lower() for s in priority}
        weighted = [(s, PRIORITY_WEIGHT) for s in priority]
        weighted += [(s, SEED_WEIGHT) for s in sentences if s.strip().lower() not in seen]
        return weighted, corpus.get("vocab") or []

    def _read_user_sentences(self):
        try:
            with open(self._user_path, encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except OSError:
            return []

    def observe(self, sentence: str):
        """Learn from a sentence the user actually finished typing, and
        save it so it's remembered next launch."""
        tokens = _tokenize(sentence)
        if not tokens:
            return
        self.model.observe(sentence, USER_WEIGHT)
        try:
            with open(self._user_path, "a", encoding="utf-8") as f:
                f.write(" ".join(tokens) + "\n")
        except OSError:
            pass

    def suggest(self, typed_text: str, k: int | None = None):
        """Up to k (default PREDICTION_SLOTS) suggestions for the current
        line of text.

        - Nothing typed on this line: all slots blank.
        - Ends mid-word (no trailing space): suggestions COMPLETE that
          prefix. Words already seen in conversation rank first (context
          first, then most used); the bundled dictionary fills any
          remaining slots so a rare-but-ordinary prefix is never left
          nearly empty.
        - Ends with a space: suggestions predict the NEXT word given the
          preceding one or two words.
        """
        n = k or self.slots
        line = (typed_text or "").split("\n")[-1]
        if not line.strip():
            return [""] * n

        if line.endswith(" "):
            context = _tokenize(line)
            results = self.model.next_words(context, n)
            return self._finish(results, n, typed_text)

        words = line.split()
        prefix_lower = words[-1].lower()
        context = _tokenize(" ".join(words[:-1]))

        # Layer 1 — known-good: words actually used in conversation.
        results = self.model.prefix_words(prefix_lower, n, context)

        # Layer 2 — dictionary fallback fills any remaining slots.
        if len(results) < n and self.dictionary_enabled:
            seen = set(results)
            seen.add(prefix_lower)
            candidates = _DICTIONARY_BY_LETTER.get(prefix_lower[0], ())
            extra = [w for w in candidates if w.startswith(prefix_lower) and w not in seen]
            # Shorter, more common-looking completions surface before
            # obscure long ones when there's no usage data to rank by.
            extra.sort(key=lambda w: (len(w), w))
            results.extend(extra[: n - len(results)])

        return self._finish(results, n, typed_text)

    def _finish(self, results, n, typed_text):
        results = list(results[:n])
        while len(results) < n:
            results.append("")
        # This keyboard's layout and buffer are uppercase-only (no shift
        # key); match that everywhere suggestions are shown.
        return [w.upper() if w else w for w in results]
