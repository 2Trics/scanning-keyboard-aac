"""Folders for source runs vs a frozen PyInstaller app.

Bundled files (nltk data, pre-trained n-gram caches) live next to the
code. Learned sentences must be writable, so a frozen build stores those
under the user's local AppData instead of inside the install folder.
"""

from pathlib import Path
import os
import sys


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_dir():
    """Read-only files shipped with the app (PyInstaller extract dir)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def user_data_dir():
    """Writable per-user data (learned sentences, extra caches)."""
    if not is_frozen():
        return Path(__file__).resolve().parent
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / "AppData" / "Local"
    path = root / "ScanningKeyboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_nltk():
    """Prefer bundled tokenizer data. Never requires the network."""
    import nltk

    bundled = resource_dir() / "nltk_data"
    if bundled.is_dir():
        path = str(bundled)
        if path not in nltk.data.path:
            nltk.data.path.insert(0, path)
    env = os.environ.get("NLTK_DATA")
    if env:
        for part in env.split(os.pathsep):
            if part and part not in nltk.data.path:
                nltk.data.path.insert(0, part)
