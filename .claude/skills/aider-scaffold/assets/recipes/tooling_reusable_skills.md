# Recipe — the reusable tooling (aider-scaffold, tree-f-visualizer, pass-sequence, agents)

/add .claude/skills/aider-scaffold/SKILL.md .claude/skills/aider-scaffold/scripts/aider_scaffold.py .claude/skills/aider-scaffold/scripts/diff_ledger.py .claude/skills/tree-f-visualizer/SKILL.md .claude/skills/tree-f-visualizer/scripts/tree_f.py .claude/skills/tree-f-visualizer/assets/template.html .claude/skills/pass-sequence/SKILL.md .claude/agents/discovery-agent.md .claude/agents/implementation-agent.md

Three project-agnostic skills plus two agent definitions, installable into any repo by copying `.claude/`:
- aider-scaffold: `aider_scaffold.py <recipe> [files]` reads leading `/add` and `/read-only` lines of the recipe, refuses a dirty tree,
  runs aider with auto-commits and a `Recipe:` trailer (or prints the recipe and exits 2 without an LLM key); `diff_ledger.py` writes one
  `.patch` per commit + `INDEX.md`, idempotent, `--check` for pre-push, `--aider-only` filter using aider 0.86's commit marks.
- tree-f-visualizer: `tree_f.py` walks the repo, grafts proposed nodes from an annotations file (scenarios, layer(s), status, parity,
  recipe), renders Windows `tree /f` text (tree.com serial format, NTFS sort order), a JSON manifest with a layers × lanes cross-tab, and a
  single-file HTML page (filters, lane view, copy as tree /f, light/dark); `--check` gate; `--artifact` fragment form.
- pass-sequence: the documentation method (sequence page → record → YAML → workbook with live parity counts) made generic: columns may be
  execution surfaces or candidate scenarios; the parallel lane = layers Parallel across all columns.
No project names inside scripts or templates; labels come from the annotations/spec files. Tests: screenshots at 1280/400 px both themes,
`node --check`, round trip of the real mr-load workbook, ledger behaviour in a throwaway repo.
