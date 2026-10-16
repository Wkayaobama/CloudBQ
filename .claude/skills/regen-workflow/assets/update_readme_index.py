#!/usr/bin/env python3
"""update_readme_index.py — keep an index of the markdown files of one or more directories inside README.md, between markers.

    python3 update_readme_index.py --readme README.md --dir docs --dir notebooks          # write (idempotent)
    python3 update_readme_index.py --readme README.md --dir docs --check                  # exit 1 if the block is stale
    python3 update_readme_index.py --readme README.md --dir docs --exclude 'docs/diffs/*'  # leave generated sub-trees out

The block lives between `<!-- regen:docs-index start -->` and `<!-- regen:docs-index end -->`; when the markers are absent a
"## Documents" section with them is appended once. Each entry is `- [title](path)` where the title is the file's first `# ` heading
(else the file name); entries are sorted by path; the README itself is never listed. Project-agnostic: no names inside.
"""
from __future__ import annotations

import argparse
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

START, END = "<!-- regen:{name} start -->", "<!-- regen:{name} end -->"


def title_of(path: Path) -> str:
    """First H1 outside fenced code (``` or ~~~): an ATX `# Title`, or a setext title underlined with `===`; else the file name."""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    fence = None
    for i, line in enumerate(lines):
        s = line.strip()
        if fence:
            if s.startswith(fence): fence = None
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]; continue
        if line.startswith("# "):
            return line[2:].strip()
        if s and i + 1 < len(lines) and re.fullmatch(r"=+", lines[i + 1].strip()):
            return s
    return path.name


def build_block(readme: Path, dirs: list[Path], name: str, heading: str, excludes: list[str] = ()) -> str:
    root = readme.resolve().parent
    rows = []
    for d in dirs:
        for f in sorted(d.rglob("*.md"), key=lambda p: (len(p.relative_to(d).parts), p.as_posix().lower())):   # files of d first, then its sub-directories; case-insensitive
            if f.resolve() == readme.resolve():
                continue
            if any(part.startswith(".") for part in f.relative_to(d).parts):   # .venv, .git, caches below the given dir
                continue
            try:
                rel = f.resolve().relative_to(root).as_posix()
            except ValueError:
                raise SystemExit(f"{f} is outside {root}: --dir must be under the README's directory")
            if any(fnmatch(rel, pat) for pat in excludes):
                continue
            rows.append(f"- [{title_of(f)}]({rel})")
    body = "\n".join(rows) if rows else "_(no documents yet)_"
    return f"{START.format(name=name)}\n{body}\n{END.format(name=name)}"


def splice(text: str, block: str, name: str, heading: str) -> str:
    pattern = re.compile(re.escape(START.format(name=name)) + r".*?" + re.escape(END.format(name=name)), re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text)
    sep = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
    return f"{text}{sep}## {heading}\n\n{block}\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--dir", action="append", required=True, help="directory to index (repeatable)")
    ap.add_argument("--name", default="docs-index", help="marker name (several blocks can coexist)")
    ap.add_argument("--exclude", action="append", default=[], help="glob on the README-relative path to leave out (repeatable), e.g. 'docs/diffs/*'")
    ap.add_argument("--heading", default="Documents", help="section heading used when the markers are first appended")
    ap.add_argument("--check", action="store_true", help="exit 1 when the block would change; write nothing")
    a = ap.parse_args(argv)
    readme = Path(a.readme)
    raw = readme.read_bytes().decode("utf-8") if readme.exists() else ""
    crlf = "\r\n" in raw                                                  # keep the README's line endings
    text = raw.replace("\r\n", "\n")
    new = splice(text, build_block(readme, [Path(d) for d in a.dir], a.name, a.heading, a.exclude), a.name, a.heading)
    if new == text:
        print(f"{readme}: unchanged"); return 0
    if a.check:
        print(f"{readme}: the {a.name} block is stale"); return 1
    readme.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8")); print(f"{readme}: updated"); return 0


if __name__ == "__main__":
    sys.exit(main())
