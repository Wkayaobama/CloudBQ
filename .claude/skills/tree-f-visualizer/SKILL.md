---
name: tree-f-visualizer
description: Render a project's architecture (what exists on disk plus what is proposed) as a Windows `tree /f` listing — plain text, a JSON manifest, and a single-file interactive HTML with scenario and status filters, parity colours and a details panel. Use when someone wants to "see the architecture in tree /f fashion", compare scenarios' building blocks, or publish the tree as an artifact. Project-agnostic: all labels come from an annotations file.
---

# tree-f-visualizer

One script, three outputs, no project strings inside the skill.

```bash
S=.claude/skills/tree-f-visualizer/scripts
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml \
  --out-json docs/architecture.manifest.json \
  --out-ascii docs/ARCHITECTURE_TREE.txt \
  --out-html docs/architecture_tree.html
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml --scenario B        # one lane, to stdout
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml --annotate          # tags {A,B · L5 · proposed · Parallel}
```

## The annotations file is the architecture

`docs/architecture.yaml` says what each path *means*; the walk says what *exists*. Paths that are
annotated but absent are grafted into the tree as **proposed** nodes (dashed in the HTML), so the
page shows the proposal, not just the present.

```yaml
project: <name>
scenarios: {A: "<label>", B: "<label>", C: "<label>"}
layers: {L0: "<label>", …}                      # optional, shown in the details panel
nodes:
  path/to/file.py:
    scenarios: [A, C]                             # which lanes use this block
    layer: L5                                     # execution layer (pass-sequence vocabulary)
    role: "one sentence"
    status: existing | modify | new | proposed    # proposed = not on disk yet
    parity: Parallel | Conditional | Divergent    # optional; same words as the surfaces workbook
    notes: "…"
    recipe: .claude/skills/aider-scaffold/assets/recipes/<block>.md
  path/to/dir/: {…}                               # trailing slash = directory
```

Status and parity words are validated; anything else stops the build.

## What the HTML does

Collapsible monospace listing with the real `tree /f` glyphs; scenario chips (All / A / B / C)
hide blocks outside the chosen lane; status chips hide existing/modify/new/proposed; a path filter;
a details panel (role, scenarios, layer, status, parity, notes, recipe); **Copy as tree /f** copies
the exact ASCII of the current view; light and dark themes from the viewer's setting. The page is a
single file with the manifest embedded, so it works offline, in a repo, or published as an
artifact (it follows the artifact page contract: no doctype, title + style first, tokens on
`:root`).

## The `tree /f` rules the renderer follows

`references/tree-f-format.md` states them; in short: header (`Folder PATH listing for volume …`,
`Volume serial number is …`), root line, a directory's files first (`│   ` column when the directory
also has sub-directories, four spaces otherwise), a `│` spacer between files and sub-directories,
`├───`/`└───` connectors, child prefix `│   `/`    `, and a spacer equal to the child prefix after a
directory without sub-directories. The serial is derived from the tree content, so a re-run on an
unchanged tree is byte-identical (good for diffs).

## Rhythm

Regenerate after every building block (the implementation agent does this), commit the three
outputs with the block, and publish `docs/architecture_tree.html` when the operator wants to look.
Keep `docs/architecture.yaml` as the single place where a block's role and lane are stated; the
surfaces workbook (`pass-sequence`) and this page should agree on scenarios, layers and parity words.
