#!/usr/bin/env python3
"""diff_ledger — one reviewable patch per commit, so every AI suggestion can be read with `git diff`.

    python3 diff_ledger.py                      # append patches for commits not yet in the ledger (current branch)
    python3 diff_ledger.py --aider-only         # only commits aider made (author/committer " (aider)", trailer, "aider: " prefix)
    python3 diff_ledger.py --since <rev>        # restrict to <rev>..HEAD
    python3 diff_ledger.py --check              # exit 1 when commits are missing from the ledger (CI / pre-push)
    python3 diff_ledger.py --ledger docs/diffs  # where patches and INDEX.md live (default)

Each commit becomes docs/diffs/NNNN-<shortsha>-<slug>.patch (full `git show --format=... --patch`), and INDEX.md gets
one row: n · sha · date · author · recipe (from a `Recipe:` or `Scaffolded-by:` trailer when present) · files · +/-.
Idempotent: commits already listed (by full sha in INDEX.md) are skipped; nothing is rewritten. Commits that touch only the ledger
and commits carrying a `Regenerated-by:` trailer (made by a regen workflow) are never listed. Works in any git repo
(the root is discovered with `git rev-parse --show-toplevel`); no project-specific strings.

aider 0.86.x marks its commits with: author or committer name ending in " (aider)" (default --attribute-author/
--attribute-committer), optionally the trailer "Co-authored-by: aider (<model>) <aider@aider.chat>"
(--attribute-co-authored-by) and optionally the message prefix "aider: " (--attribute-commit-message-author). The
--aider-only filter accepts any of the three.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SEP = "\x1f"
AIDER_NAME = re.compile(r"\(aider\)\s*$")
AIDER_TRAILER = re.compile(r"^Co-authored-by: aider \(", re.M)
RECIPE_TRAILER = re.compile(r"^(?:Recipe|Scaffolded-by):\s*(.+)$", re.M | re.I)
REGEN_TRAILER = re.compile(r"^Regenerated-by:\s*\S", re.M | re.I)   # commits a regen workflow made (regen-workflow skill): generated files, not suggestions


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def repo_root() -> Path:
    try:
        return Path(git("rev-parse", "--show-toplevel").strip())
    except subprocess.CalledProcessError:
        sys.exit("diff_ledger: not inside a git repository")


def commits(root: Path, since: str | None, ledger_rel: str) -> list[dict]:
    rng = f"{since}..HEAD" if since else "HEAD"
    fmt = SEP.join(["%H", "%h", "%aI", "%an", "%cn", "%s", "%b"]) + "\x1e"
    raw = git("log", "--reverse", "--no-merges", f"--format={fmt}", rng, cwd=root)
    out = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, short, date, an, cn, subject, body = rec.split(SEP, 6)
        files = git("show", "--name-only", "--format=", sha, cwd=root).split()
        if files and all(f.startswith(ledger_rel.rstrip("/") + "/") for f in files):
            continue  # the ledger's own commits are not ledgered (otherwise --check could never pass)
        if REGEN_TRAILER.search(body):
            continue  # a regen workflow's commit (Regenerated-by: trailer) carries generated files, not a suggestion
        out.append({"sha": sha, "short": short, "date": date[:10], "author": an, "committer": cn, "subject": subject, "body": body})
    return out


def is_aider(c: dict) -> bool:
    return bool(AIDER_NAME.search(c["author"]) or AIDER_NAME.search(c["committer"]) or AIDER_TRAILER.search(c["body"]) or c["subject"].startswith("aider: "))


def recipe_of(c: dict) -> str:
    m = RECIPE_TRAILER.search(c["body"])
    return m.group(1).strip() if m else ""


def slug(s: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s[:n] or "change").rstrip("-")


def stats(root: Path, sha: str) -> tuple[int, int, int]:
    raw = git("show", "--numstat", "--format=", sha, cwd=root)
    files = add = rem = 0
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            files += 1
            add += int(parts[0]) if parts[0].isdigit() else 0
            rem += int(parts[1]) if parts[1].isdigit() else 0
    return files, add, rem


def existing(index: Path) -> set[str]:
    if not index.exists():
        return set()
    return set(re.findall(r"\b([0-9a-f]{40})\b", index.read_text(encoding="utf-8")))


HEADER = "# Diff ledger\n\nOne patch per commit; read any suggestion with `git show <sha>` or open the `.patch`. Rows are appended by `diff_ledger.py`; never edit by hand. Commits that touch only this ledger directory are not listed (otherwise `--check` could never pass). The `recipe` column shows the commit's `Recipe:` or `Scaffolded-by:` trailer.\n\n| # | commit | date | author | aider | recipe | files | +/- | patch |\n|---|---|---|---|---|---|---|---|---|\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default="docs/diffs", help="directory for patches and INDEX.md (repo-relative)")
    ap.add_argument("--since", help="only commits after this revision (exclusive)")
    ap.add_argument("--aider-only", action="store_true", help="only commits aider made")
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if any commit is missing from the ledger")
    a = ap.parse_args(argv)

    root = repo_root()
    ledger = root / a.ledger
    index = ledger / "INDEX.md"
    seen = existing(index)
    todo = [c for c in commits(root, a.since, a.ledger) if c["sha"] not in seen and (is_aider(c) if a.aider_only else True)]
    if a.check:
        for c in todo:
            print(f"missing: {c['short']} {c['subject']}")
        print(f"diff_ledger --check: {len(todo)} commit(s) not in {index.relative_to(root)}")
        return 1 if todo else 0
    if not todo:
        print("diff_ledger: nothing new")
        return 0
    ledger.mkdir(parents=True, exist_ok=True)
    if not index.exists():
        index.write_text(HEADER, encoding="utf-8")
    n = len(seen)
    rows = []
    for c in todo:
        n += 1
        name = f"{n:04d}-{c['short']}-{slug(c['subject'])}.patch"
        patch = git("show", "--format=fuller", "--patch", "--stat", c["sha"], cwd=root)
        (ledger / name).write_text(patch, encoding="utf-8")
        files, add, rem = stats(root, c["sha"])
        rows.append(f"| {n} | `{c['short']}` {c['sha']} | {c['date']} | {c['author']} | {'yes' if is_aider(c) else 'no'} | {recipe_of(c) or '—'} | {files} | +{add}/−{rem} | [{name}]({name}) |\n")
        print(f"ledger +{name}")
    with index.open("a", encoding="utf-8") as f:
        f.writelines(rows)
    print(f"diff_ledger: {len(rows)} patch(es) appended to {index.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
