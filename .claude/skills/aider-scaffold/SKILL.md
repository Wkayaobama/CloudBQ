---
name: aider-scaffold
description: Scaffold building blocks with aider as reviewable, auto-committed steps and keep a diff ledger so every AI suggestion can be read with `git diff`. Use when the user wants aider as the scaffolder, wants "git diff for every change the assistant suggests", or needs a per-commit patch trail for review. Project-agnostic (repo root discovered with git); works without an LLM key in a degraded, documented mode.
---

# aider-scaffold

Two scripts and a convention. The suggestion is the commit; the ledger is the review surface.

```bash
S=.claude/skills/aider-scaffold/scripts
python3 $S/aider_scaffold.py assets/recipes/<block>.md path/to/file [more files] [--dry-run]
python3 $S/diff_ledger.py                     # docs/diffs/NNNN-<sha>-<slug>.patch + INDEX.md, idempotent
python3 $S/diff_ledger.py --aider-only        # only aider's commits
python3 $S/diff_ledger.py --check             # exit 1 if commits are missing from the ledger (pre-push)
```

## How a suggestion becomes a diff

1. `aider_scaffold.py` refuses a dirty tree (so a commit holds one suggestion), then runs
   `aider --yes-always --no-stream --message-file <recipe> [--read CONVENTIONS.md] <files>` with the
   repo's `.aider.conf.yml` (auto-commits on, attribution on, show-diffs on) and a `--commit-prompt`
   that adds the trailer `Recipe: <recipe path>`.
2. aider commits each edit itself. In 0.86.x the author and committer names end in ` (aider)`;
   `--attribute-co-authored-by` adds `Co-authored-by: aider (<model>) <aider@aider.chat>`;
   `--attribute-commit-message-author` prefixes the subject with `aider: `. The ledger recognises all three.
3. `diff_ledger.py` writes one `.patch` per new commit (full `git show --format=fuller --patch --stat`)
   and appends a row to `docs/diffs/INDEX.md` (n · sha · date · author · aider? · recipe · files · +/−).
   Re-running adds only commits whose sha is not yet in the index. `git diff <sha>~1 <sha>` and the patch
   file show the same thing; the patch survives rebases and squashes.

## Without an LLM key

The wrapper detects the absence of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
`OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` (or `--model`), prints the recipe, the files and the exact
command, and exits 2. Apply the recipe by hand and commit with the trailers
`Recipe: <recipe>` and `Scaffolded-by: hand (no LLM key)`; the ledger row then says `recipe: hand (no LLM key)`.
Nothing else changes, so the review trail is identical whichever path produced the commit.

## Recipes

A recipe is a markdown file aider receives as its message: the block's purpose, the files to create or
change, the contract (inputs, outputs, idempotency rule, gate), and what *not* to do. One recipe per
building block; the architecture annotations (`docs/architecture.yaml`) point at it. Keep recipes
self-contained — aider sees only the recipe, the added files and `CONVENTIONS.md`.

## Install into a repo

Copy this directory to `.claude/skills/aider-scaffold/`, copy `assets/aider.conf.yml` to the repo root
as `.aider.conf.yml`, `assets/aiderignore` as `.aiderignore`, and write a `CONVENTIONS.md` (start from
`assets/CONVENTIONS.template.md`). Add `.aider*` history files to `.gitignore` (the ignore file does).
`references/aider-0.86-commit-signature.md` records how the detection rules were verified.
