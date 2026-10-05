"""Build an offline Windows app (PyInstaller).

Run from this folder:

    python -m pip install -r requirements-build.txt
    python build_app.py

The result is dist/ScanningKeyboard.exe — a single file you can send.
Double-click it on the other machine. No internet is needed at runtime:
tokenizer data and the n-gram caches are inside the exe.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "_bundle"
DIST_NAME = "ScanningKeyboard"
ENTRY = ROOT / "main.py"


def _run(args, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    print(">", " ".join(str(a) for a in args))
    subprocess.check_call(args, cwd=ROOT, env=env)


def prepare_nltk_data():
    """Download tokenizer files into the bundle at *build* time only."""
    import nltk

    dest = BUNDLE / "nltk_data"
    dest.mkdir(parents=True, exist_ok=True)
    for package in ("punkt", "punkt_tab"):
        nltk.download(package, download_dir=str(dest), quiet=True)
        print(f"bundled nltk package: {package}")
    os.environ["NLTK_DATA"] = str(dest)


def train_offline_caches():
    """Train sentence models from local files (no Brown / no network)."""
    sys.path.insert(0, str(ROOT))
    os.environ["NLTK_DATA"] = str(BUNDLE / "nltk_data")
    from predictor import NgramPredictor, _cache_paths

    for model_id in ("aac", "care", "social"):
        print(f"training n-gram cache: {model_id}")
        NgramPredictor(model_id)
        _bundled, writable = _cache_paths(model_id)
        if not writable.exists():
            raise SystemExit(f"expected cache missing after train: {writable}")
        target = BUNDLE / writable.name
        shutil.copy2(writable, target)
        print(f"  copied {target.name}")


def pyinstaller_cmd():
    nltk_data = BUNDLE / "nltk_data"
    sep = ";" if os.name == "nt" else ":"
    datas = [
        f"{nltk_data}{sep}nltk_data",
    ]
    for pkl in sorted(BUNDLE.glob(".ngram_cache_*.pkl")):
        datas.append(f"{pkl}{sep}.")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name", DIST_NAME,
        "--paths", str(ROOT),
        "--hidden-import", "nltk",
        "--hidden-import", "nltk.tokenize",
        "--hidden-import", "nltk.tokenize.punkt",
        "--hidden-import", "nltk.util",
        "--hidden-import", "paths",
        "--hidden-import", "config",
        "--hidden-import", "scanner",
        "--hidden-import", "predictor",
        "--hidden-import", "aac_sentences",
        "--hidden-import", "conversational_english",
        # nltk's PyInstaller hook otherwise pulls numpy/pandas/scipy/etc.
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "IPython",
        "--exclude-module", "jupyter",
        "--exclude-module", "notebook",
        "--exclude-module", "PIL",
        "--exclude-module", "cv2",
        "--exclude-module", "sklearn",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
    ]
    for item in datas:
        cmd.extend(["--add-data", item])
    cmd.append(str(ENTRY))
    return cmd


def write_user_readme(dist_dir: Path):
    text = (
        "Scanning Keyboard\n"
        "=================\n\n"
        "Double-click ScanningKeyboard.exe to start.\n\n"
        "This app works fully offline. Press Escape twice to quit.\n"
        "The switch key is Enter unless the person who built this "
        "changed it.\n"
    )
    (dist_dir / "README.txt").write_text(text, encoding="utf-8")


def main():
    BUNDLE.mkdir(parents=True, exist_ok=True)
    prepare_nltk_data()
    train_offline_caches()
    _run(pyinstaller_cmd())
    exe = ROOT / "dist" / f"{DIST_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"build finished but {exe} was not created")
    write_user_readme(ROOT / "dist")
    print("\nDone. Send this one file:")
    print(f"  {exe}")
    print("The other person double-clicks it. First launch may take a few extra seconds.")


if __name__ == "__main__":
    main()
