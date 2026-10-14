"""Where files live: bundled read-only resources vs. writable user data.

When run from source, everything sits next to the code. When packaged into
a single .exe with PyInstaller, read-only resources (the dictionary, the
NLTK tokenizer data) are unpacked to a temporary folder at launch, and
anything the app *writes* (saved settings, learned sentences) goes to the
user's local AppData folder instead -- the .exe itself never needs any
other file beside it, and the app still runs if nothing can be written.
"""

import os
import sys
from pathlib import Path

APP_NAME = "ScanningKeyboard"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_dir():
    """Read-only files shipped with the app."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def resource_path(name):
    return str(resource_dir() / name)


def user_data_dir():
    """Writable per-user folder (saved settings, learned sentences)."""
    if not is_frozen():
        return Path(__file__).resolve().parent
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / APP_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # writes will fail quietly later; the app still runs
    return path


def user_path(name):
    return user_data_dir() / name


def configure_nltk(nltk_module):
    """Point NLTK at tokenizer data bundled inside the app, if any.
    Never downloads anything."""
    bundled = resource_dir() / "nltk_data"
    if bundled.is_dir() and str(bundled) not in nltk_module.data.path:
        nltk_module.data.path.insert(0, str(bundled))
