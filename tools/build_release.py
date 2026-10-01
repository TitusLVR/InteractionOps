"""Build the distributable InteractionOps zip.

Stages the addon files into ``<out>/InteractionOps`` and zips them to
``<out>/InteractionOps_<version>.zip`` so the archive installs straight into
Blender (top-level folder = package name). The version comes from ``bl_info``
in the root ``__init__.py``.

Usage::

    python tools/build_release.py [--out dist] [--native SRC=DEST ...]

``--native`` copies a freshly compiled extension into the staged tree, e.g.::

    --native rust/target/release/mesh_uv_shortest_mark_lib.dll=operators/mesh_uv_shortest_mark_lib.pyd

Prints ``version=<ver>`` and ``zip=<path>`` on stdout (ready for
``$GITHUB_OUTPUT``); diagnostics go to stderr.
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_NAME = "InteractionOps"

# Everything the addon needs at runtime. Docs, tests, tooling and Rust sources stay out.
INCLUDE = [
    "__init__.py",
    "README.md",
    "license",
    "operators",
    "prefs",
    "presets",
    "ui",
    "utils",
    "widgets",
]
EXCLUDE_NAMES = {"__pycache__", "hotkeys_user.py"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".old"}


def read_version() -> str:
    src = (ROOT / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*\(([^)]*)\)', src)
    if not match:
        sys.exit("bl_info version not found in __init__.py")
    parts = [int(p) for p in match.group(1).split(",") if p.strip()]
    return ".".join(str(p) for p in parts)


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in EXCLUDE_NAMES or Path(n).suffix in EXCLUDE_SUFFIXES}


def stage(out: Path, natives: list[str]) -> Path:
    dst = out / ADDON_NAME
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in INCLUDE:
        src = ROOT / name
        if not src.exists():
            print(f"warning: {name} missing, skipped", file=sys.stderr)
            continue
        if src.is_dir():
            shutil.copytree(src, dst / name, ignore=_ignore)
        else:
            shutil.copy2(src, dst / name)
    for spec in natives:
        src_rel, sep, dst_rel = spec.partition("=")
        if not sep:
            sys.exit(f"--native expects SRC=DEST, got {spec!r}")
        src = ROOT / src_rel
        if not src.is_file():
            sys.exit(f"native extension not found: {src}")
        shutil.copy2(src, dst / dst_rel)
    return dst


def zip_dir(staged: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(staged.parent).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    parser.add_argument("--native", action="append", default=[], metavar="SRC=DEST",
                        help="copy a compiled extension into the staged addon")
    args = parser.parse_args()

    version = read_version()
    out = (ROOT / args.out).resolve()
    staged = stage(out, args.native)
    zip_path = out / f"{ADDON_NAME}_{version}.zip"
    zip_dir(staged, zip_path)

    size_kb = zip_path.stat().st_size // 1024
    print(f"built {zip_path.name} ({size_kb} KB)", file=sys.stderr)
    print(f"version={version}")
    print(f"zip={zip_path.as_posix()}")


if __name__ == "__main__":
    main()
