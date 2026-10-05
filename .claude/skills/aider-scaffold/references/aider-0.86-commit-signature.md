# How aider 0.86.x marks its commits (verified in `aider/repo.py` of the installed package)

| Option (default) | Effect on the commit |
|---|---|
| `--attribute-author` (on) | author name becomes `<git user.name> (aider)` for AI edits |
| `--attribute-committer` (on) | committer name becomes `<git user.name> (aider)` |
| `--attribute-co-authored-by` (off) | trailer `Co-authored-by: aider (<model>) <aider@aider.chat>`; when on and author not explicit, the author name is left unsuffixed |
| `--attribute-commit-message-author` / `-committer` (off) | subject prefixed with `aider: ` |

`scripts/diff_ledger.py` marks a commit as aider's when any of: author or committer name ends with `(aider)`,
the body contains a line starting `Co-authored-by: aider (`, or the subject starts with `aider: `.
Checked against repo.py lines 165–273 (docstring and `commit()`), aider 0.86.2, 2026-10-05.
