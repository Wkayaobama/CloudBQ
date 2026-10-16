#!/usr/bin/env python3
"""aider_scaffold — run one scaffold recipe through aider as a reviewable, auto-committed step, then update the diff ledger.

    python3 aider_scaffold.py <recipe.md> [file ...] [--read FILE ...] [--model MODEL] [--dry-run] [--no-ledger]

What it does
  1. Finds the repo root (git rev-parse) and refuses to run on a dirty tree unless --allow-dirty (aider's own dirty
     commit would mix your edits with the suggestion and break "one commit per suggestion").
  2. Builds the aider command from the repo's .aider.conf.yml (auto-commits, attribution, show-diffs) and the recipe:
       aider --yes-always --no-stream --message-file <recipe> [--read CONVENTIONS.md] <files…>
     and runs it in the foreground. Every edit aider makes lands as its own commit, author "<you> (aider)", with a
     "Recipe: <recipe path>" trailer added by --commit-prompt so the ledger can name the recipe.
  3. Runs diff_ledger.py so docs/diffs/ gains one .patch per new commit — `git diff HEAD~1` or the patch file shows
     exactly what the assistant proposed.

Without an LLM key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY / DEEPSEEK_API_KEY, or
--model with its own key) aider cannot answer; this wrapper then prints the recipe, the files it would add and the exact
command, and exits 2. Apply the recipe by hand, commit with the trailer `Scaffolded-by: hand (no LLM key)` and
`Recipe: <recipe>`, then run diff_ledger.py — the ledger treats both paths the same.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "AIDER_MODEL")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe", help="markdown recipe passed to aider as --message-file")
    ap.add_argument("files", nargs="*", help="files aider may edit (added to the chat)")
    ap.add_argument("--read", action="append", default=[], help="read-only context files (default: CONVENTIONS.md if present)")
    ap.add_argument("--model", help="aider model id (else aider's default / AIDER_MODEL)")
    ap.add_argument("--dry-run", action="store_true", help="aider --dry-run: show edits, write nothing")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--ledger", default="docs/diffs")
    a = ap.parse_args(argv)

    try:
        root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
    except subprocess.CalledProcessError:
        sys.exit("aider_scaffold: not inside a git repository")
    recipe = Path(a.recipe)
    if not recipe.exists():
        sys.exit(f"aider_scaffold: recipe not found: {recipe}")
    # a recipe may start with aider-style "/add path…" and "/read-only path…" lines: they become the file lists (so the recipe stands alone)
    files, reads = list(a.files), list(a.read)
    for line in recipe.read_text(encoding="utf-8").splitlines():
        if line.startswith("/add "): files += [f for f in line[5:].split() if f not in files]
        elif line.startswith("/read-only "): reads += [f for f in line[11:].split() if f not in reads]
    a.files = files
    if not reads and (root / "CONVENTIONS.md").exists(): reads = [str(root / "CONVENTIONS.md")]
    for f in a.files:
        if not Path(f).exists():
            Path(f).parent.mkdir(parents=True, exist_ok=True)  # aider creates new files when they are named; keep parents ready
    before = git("rev-parse", "HEAD", cwd=root).strip()

    dirty = git("status", "--porcelain", "--untracked-files=no", cwd=root).strip()
    if dirty and not a.allow_dirty:
        sys.exit("aider_scaffold: working tree has uncommitted changes; commit or stash them first (or --allow-dirty)\n" + dirty)

    aider = shutil.which("aider") or str(Path.home() / ".local" / "bin" / "aider")
    cmd = [aider, "--yes-always", "--no-stream", "--no-check-update", "--no-analytics", "--message-file", str(recipe),
           "--commit-prompt", f"Write a conventional one-line summary of the change, then a blank line, then the trailer line 'Recipe: {recipe.as_posix()}'."]
    if a.model:
        cmd += ["--model", a.model]
    if a.dry_run:
        cmd += ["--dry-run"]
    for r in reads:
        cmd += ["--read", r]
    cmd += a.files

    have_key = any(os.environ.get(k) for k in KEY_VARS) or a.model
    if not have_key or not Path(aider).exists():
        why = "no LLM API key in the environment" if Path(aider).exists() else f"aider not found at {aider}"
        print(f"aider_scaffold: cannot run aider ({why}).\n\nRecipe {recipe}:\n" + "-" * 72)
        print(recipe.read_text(encoding="utf-8").rstrip())
        print("-" * 72 + f"\nFiles: {', '.join(a.files) or '(none named)'}\nRead-only context: {', '.join(reads) or '(none)'}")
        print("Command that would run:\n  " + " ".join(cmd))
        print("\nApply the recipe by hand, then:\n  git commit -m '<summary>' -m 'Recipe: " + recipe.as_posix() + "' -m 'Scaffolded-by: hand (no LLM key)'\n  python3 "
              + str(Path(__file__).with_name("diff_ledger.py")) + f" --ledger {a.ledger}")
        return 2

    print("aider_scaffold: " + " ".join(cmd))
    rc = subprocess.run(cmd, cwd=root).returncode
    after = git("rev-parse", "HEAD", cwd=root).strip()
    print(f"aider_scaffold: aider exit {rc}; HEAD {before[:7]} → {after[:7]}" + (" (no commit)" if before == after else ""))
    if not a.no_ledger and before != after:
        subprocess.run([sys.executable, str(Path(__file__).with_name("diff_ledger.py")), "--ledger", a.ledger, "--since", before], cwd=root, check=False)
    return rc


if __name__ == "__main__":
    sys.exit(main())
