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


def pyinstaller_cmd(with_nltk_data):
    sep = ";" if os.name == "nt" else ":"
    datas = [f"{SRC / 'dictionary_words.txt'}{sep}."]
    if with_nltk_data:
        datas.append(f"{BUNDLE / 'nltk_data'}{sep}nltk_data")
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
    ]
    for module in LOCAL_MODULES:
        cmd += ["--hidden-import", module]
    cmd += ["--hidden-import", "nltk", "--hidden-import", "nltk.tokenize"]
    # nltk's PyInstaller hook otherwise drags in numpy/pandas/scipy/etc.
    for name in ("numpy", "pandas", "matplotlib", "scipy", "IPython", "jupyter",
                 "notebook", "PIL", "cv2", "sklearn", "pytest", "setuptools"):
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
    with_nltk = prepare_nltk_data()
    _run(pyinstaller_cmd(with_nltk))
    exe = ROOT / "dist" / f"{DIST_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"build finished but {exe} was not created")
    verify(exe)
    print("Done. Send this one file; nothing else is needed:")
    print(f"  {exe}  ({exe.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
