"""Build the standalone Windows app (PyInstaller) from the v2 code.

Run from this folder:

    python -m pip install -r requirements-build.txt
    python build_app.py

The result is dist/ScanningKeyboard.exe -- ONE file that needs nothing
else beside it and no internet at runtime. The word dictionary and (if it
could be fetched at build time) NLTK's tokenizer data are packed inside.
Anything the app writes (saved settings, learned sentences) goes to
%LOCALAPPDATA%\\ScanningKeyboard on the machine running it.

After building, the exe is launched once with --selftest to prove the
packaged program really works (see the report it prints).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "v2"
BUNDLE = ROOT / "_bundle"
DIST_NAME = "ScanningKeyboard"
ENTRY = SRC / "main.py"

LOCAL_MODULES = [
    "paths", "config", "scanner", "predictor", "settings", "settings_ui",
    "aac_sentences", "conversational_english",
]


def _run(args):
    print(">", " ".join(str(a) for a in args))
    subprocess.check_call(args, cwd=ROOT)


def prepare_nltk_data():
    """Make sure NLTK's tokenizer data is in the bundle folder. Needs the
    network at *build* time only; if it can't be fetched the app still
    works (it falls back to a built-in tokenizer). Returns True if bundled."""
    dest = BUNDLE / "nltk_data"
    marker = dest / "tokenizers" / "punkt_tab"
    if marker.exists():
        print("tokenizer data already in _bundle (reusing)")
        return True
    try:
        import nltk

        dest.mkdir(parents=True, exist_ok=True)
        nltk.download("punkt_tab", download_dir=str(dest), quiet=True)
    except Exception as exc:  # no network, nltk missing, ...
        print(f"WARNING: could not fetch tokenizer data ({exc}); building without it.")
    if marker.exists():
        print("bundled nltk package: punkt_tab")
        return True
    print("WARNING: tokenizer data not bundled; the app will use its built-in tokenizer.")
    return False


def stage_english_tokenizer():
    """Copy ONLY the English tokenizer data into a clean staging folder.
    The full download holds every language (and older formats), which
    would make the exe tens of MB larger for nothing."""
    source = BUNDLE / "nltk_data" / "tokenizers" / "punkt_tab" / "english"
    # Staged outside the project folder: OneDrive can block deleting
    # folders inside it, which would break re-running the build.
    slim = Path(tempfile.mkdtemp(prefix="sk_nltk_slim_"))
    target = slim / "tokenizers" / "punkt_tab" / "english"
    shutil.copytree(source, target)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"staged English tokenizer data: {size / 1_000_000:.2f} MB")
    return slim


def pyinstaller_cmd(nltk_slim):
    sep = ";" if os.name == "nt" else ":"
    datas = [f"{SRC / 'dictionary_words.txt'}{sep}."]
    if nltk_slim:
        datas.append(f"{nltk_slim}{sep}nltk_data")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name", DIST_NAME,
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(SRC),
        # Our own nltk hook: don't sweep ~/nltk_data into the exe.
        "--additional-hooks-dir", str(ROOT / "build_hooks"),
    ]
    for module in LOCAL_MODULES:
        cmd += ["--hidden-import", module]
    cmd += ["--hidden-import", "nltk", "--hidden-import", "nltk.tokenize"]
    # nltk's PyInstaller hook otherwise drags in numpy/pandas/scipy/etc.
    for name in ("numpy", "pandas", "matplotlib", "scipy", "IPython", "jupyter",
                 "notebook", "PIL", "cv2", "sklearn", "pytest", "setuptools",
                 "pip", "lib2to3", "idlelib", "turtledemo"):
        cmd += ["--exclude-module", name]
    for item in datas:
        cmd += ["--add-data", item]
    cmd.append(str(ENTRY))
    return cmd


def verify(exe):
    """Launch the packaged exe in self-test mode and show its report."""
    report = Path(tempfile.gettempdir()) / "scanning_keyboard_selftest.txt"
    if report.exists():
        report.unlink()
    print(f"\nVerifying {exe.name} ...")
    try:
        result = subprocess.run([str(exe), "--selftest", str(report)], timeout=180)
    except subprocess.TimeoutExpired:
        raise SystemExit("self-test timed out -- the packaged app did not finish starting up")
    text = report.read_text(encoding="utf-8") if report.exists() else "(no report written)"
    print(text)
    if result.returncode != 0:
        raise SystemExit("self-test FAILED -- do not distribute this build")


def main():
    BUNDLE.mkdir(parents=True, exist_ok=True)
    slim = stage_english_tokenizer() if prepare_nltk_data() else None
    _run(pyinstaller_cmd(slim))
    exe = ROOT / "dist" / f"{DIST_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"build finished but {exe} was not created")
    verify(exe)
    print("Done. Send this one file; nothing else is needed:")
    print(f"  {exe}  ({exe.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
