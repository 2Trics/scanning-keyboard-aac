"""Word prediction from selectable NLTK n-gram models.

config.PREDICTION_MODEL picks which trained model fills the four prediction
slots. Built-ins:

  aac     — modern conversational English (default)
  care    — needs / comfort / body / environment
  social  — greetings / family / small talk
  brown   — old NLTK Brown corpus (not recommended)

Add another conversation type by registering it in aac_sentences.CORPORA
and setting PREDICTION_MODEL to that name.

Trigram counts are the primary signal, with backoff to bigrams then
unigrams. Prefix matching is applied at every level. Completed lines
(Enter) are folded into that model's live counts only.
"""

from collections import Counter, defaultdict
from pathlib import Path
import pickle
import re

import nltk
from nltk.tokenize import word_tokenize
from nltk.util import ngrams

import config
from aac_sentences import CORPORA
from paths import configure_nltk, is_frozen, resource_dir, user_data_dir

configure_nltk()

CACHE_VERSION = 3
NGRAM_ORDER = 3
PRIORITY_WEIGHT = 8
SEED_WEIGHT = 3
USER_WEIGHT = 5
VOCAB_WEIGHT = 2
_WORD_RE = re.compile(r"^[a-zA-Z]+$")
_MODEL_ID_RE = re.compile(r"^[a-z0-9_]+$")


def available_models():
    """id -> spec. Sentence models come from aac_sentences.CORPORA."""
    models = {
        "brown": {
            "kind": "brown",
            "label": "NLTK Brown corpus (general English)",
        },
    }
    for name, corpus in CORPORA.items():
        key = name.strip().lower()
        if key == "brown":
            raise ValueError("aac_sentences.CORPORA cannot use the reserved id 'brown'.")
        models[key] = {
            "kind": "sentences",
            "label": f"conversation type '{key}'",
            "priority": corpus.get("priority") or [],
            "sentences": corpus.get("sentences") or [],
            "vocab": corpus.get("vocab") or [],
        }
    return models


def _model_spec(model_id):
    models = available_models()
    if model_id not in models:
        known = ", ".join(sorted(models))
        raise ValueError(
            f"Unknown PREDICTION_MODEL {model_id!r}. Known models: {known}."
        )
    return models[model_id]


def _ensure_punkt():
    """Locate bundled/local punkt. Never downloads (app must run offline)."""
    for resource in ("tokenizers/punkt_tab", "tokenizers/punkt"):
        try:
            nltk.data.find(resource)
            return True
        except LookupError:
            continue
    return False


def _ensure_brown():
    try:
        nltk.data.find("corpora/brown")
        return True
    except LookupError:
        return False


def _tokenize_text(text):
    """Letters-only tokens via NLTK word_tokenize, with a regex fallback."""
    cleaned = (text or "").lower().replace("'", " ")
    if not cleaned.strip():
        return []
    tokens = None
    try:
        tokens = word_tokenize(cleaned)
    except LookupError:
        _ensure_punkt()
        try:
            tokens = word_tokenize(cleaned)
        except Exception:
            tokens = None
    except Exception:
        tokens = None
    if tokens is None:
        return re.findall(r"[a-zA-Z]+", cleaned)
    return [t for t in tokens if _WORD_RE.fullmatch(t)]


def _add_tokens(unigrams, bigrams, trigrams, tokens, weight=1):
    if not tokens or weight < 1:
        return
    for _ in range(weight):
        unigrams.update(tokens)
        for a, b in ngrams(tokens, 2):
            bigrams[a][b] += 1
        for a, b, c in ngrams(tokens, NGRAM_ORDER):
            trigrams[(a, b)][c] += 1


def _train_brown():
    """Original general-English trigram from the NLTK Brown corpus."""
    if not _ensure_brown():
        raise RuntimeError(
            "The Brown corpus is not bundled with this app (it also needs "
            "the network to download). Set PREDICTION_MODEL to 'aac', "
            "'care', or 'social' for offline use."
        )
    from nltk.corpus import brown

    unigrams = Counter()
    bigrams = defaultdict(Counter)
    trigrams = defaultdict(Counter)
    for sent in brown.sents():
        tokens = [w.lower() for w in sent if _WORD_RE.fullmatch(w)]
        if not tokens:
            continue
        unigrams.update(tokens)
        for a, b in ngrams(tokens, 2):
            bigrams[a][b] += 1
        for a, b, c in ngrams(tokens, NGRAM_ORDER):
            trigrams[(a, b)][c] += 1
    return {
        "version": CACHE_VERSION,
        "unigrams": unigrams,
        "bigrams": dict(bigrams),
        "trigrams": dict(trigrams),
    }


def _train_sentences(priority, sentences, vocab=None):
    """Trigram counts from conversation sentences, plus extra unigram vocab."""
    _ensure_punkt()
    unigrams = Counter()
    bigrams = defaultdict(Counter)
    trigrams = defaultdict(Counter)
    seen = set()
    for sent in priority:
        tokens = _tokenize_text(sent)
        _add_tokens(unigrams, bigrams, trigrams, tokens, PRIORITY_WEIGHT)
        seen.add(sent.strip().lower())
    for sent in sentences:
        if sent.strip().lower() in seen:
            continue
        tokens = _tokenize_text(sent)
        _add_tokens(unigrams, bigrams, trigrams, tokens, SEED_WEIGHT)
    for word in vocab or []:
        token = str(word).lower()
        if _WORD_RE.fullmatch(token):
            unigrams[token] += VOCAB_WEIGHT
    return {
        "version": CACHE_VERSION,
        "unigrams": unigrams,
        "bigrams": dict(bigrams),
        "trigrams": dict(trigrams),
    }


def _train_spec(spec):
    if spec["kind"] == "brown":
        return _train_brown()
    return _train_sentences(spec["priority"], spec["sentences"], spec.get("vocab"))


def _cache_paths(model_id):
    name = f".ngram_cache_{model_id}.pkl"
    return resource_dir() / name, user_data_dir() / name


def _load_or_train(model_id, spec):
    bundled, writable = _cache_paths(model_id)
    for cache_path in (writable, bundled):
        if not cache_path.exists():
            continue
        try:
            with cache_path.open("rb") as fh:
                payload = pickle.load(fh)
            if payload.get("version") == CACHE_VERSION and "unigrams" in payload:
                return payload
        except Exception:
            pass
    payload = _train_spec(spec)
    try:
        writable.parent.mkdir(parents=True, exist_ok=True)
        with writable.open("wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return payload


def _read_user_sentences(path):
    if not path.exists():
        return []
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception:
        return []


def _append_user_sentence(path, text):
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text.strip() + "\n")
    except Exception:
        pass


def _parse_text(text):
    """Return (context_words, current_prefix) from the typed buffer.

    A trailing space/newline means the current word is finished and we should
    predict the *next* word. Otherwise the last token is an unfinished prefix.
    """
    if not text:
        return [], ""
    line = text.split("\n")[-1]
    if not line.strip():
        return [], ""
    if line.endswith(" "):
        return [w.lower() for w in line.split()], ""
    parts = line.split()
    prefix = parts[-1].lower()
    context = [w.lower() for w in parts[:-1]]
    return context, prefix


def _take(counter, prefix, exclude, needed):
    if needed <= 0 or not counter:
        return []
    picked = []
    items = counter.most_common() if hasattr(counter, "most_common") else sorted(
        counter.items(), key=lambda kv: (-kv[1], kv[0])
    )
    for word, _count in items:
        if word in exclude or not _WORD_RE.fullmatch(word):
            continue
        if prefix and not word.startswith(prefix):
            continue
        picked.append(word)
        if len(picked) >= needed:
            break
    return picked


class NgramPredictor:
    """Trigram-with-backoff predictor. suggest() always returns `k` strings."""

    def __init__(self, model=None):
        model_id = (model if model is not None else config.PREDICTION_MODEL)
        model_id = str(model_id).strip().lower()
        if not _MODEL_ID_RE.fullmatch(model_id):
            raise ValueError(
                f"PREDICTION_MODEL must be a lowercase id like 'aac' or 'brown' "
                f"(got {model_id!r})."
            )
        spec = _model_spec(model_id)
        self.model_id = model_id
        self._user_path = user_data_dir() / f"user_sentences_{model_id}.txt"
        payload = _load_or_train(model_id, spec)
        self.unigrams = payload["unigrams"]
        self.bigrams = defaultdict(Counter, payload["bigrams"])
        self.trigrams = defaultdict(Counter, payload["trigrams"])
        for sent in _read_user_sentences(self._user_path):
            _add_tokens(
                self.unigrams, self.bigrams, self.trigrams,
                _tokenize_text(sent), USER_WEIGHT,
            )

    def observe(self, line):
        """Fold a finished utterance into this model's live n-gram counts."""
        tokens = _tokenize_text(line)
        if not tokens:
            return
        _add_tokens(self.unigrams, self.bigrams, self.trigrams, tokens, USER_WEIGHT)
        _append_user_sentence(self._user_path, " ".join(tokens))

    def suggest(self, text, k=4):
        if not text or not text.strip():
            return [""] * k

        context, prefix = _parse_text(text)
        if not context and not prefix:
            return [""] * k

        chosen = []
        exclude = set()

        def fill(counter):
            extra = _take(counter, prefix, exclude, k - len(chosen))
            chosen.extend(extra)
            exclude.update(extra)

        if len(context) >= 2:
            fill(self.trigrams[(context[-2], context[-1])])
        if len(chosen) < k and context:
            fill(self.bigrams[context[-1]])
        if len(chosen) < k:
            fill(self.unigrams)

        chosen = [w.upper() for w in chosen[:k]]
        while len(chosen) < k:
            chosen.append("")
        return chosen
