# Recipe — UNIVERSAL_WORKFLOW.md: the team page for the loop and its three execution surfaces (docs block)

/add UNIVERSAL_WORKFLOW.md docs/execution_surfaces_tooling.yaml README.md docs/architecture.yaml
/read-only .claude/skills/aider-scaffold/SKILL.md .claude/skills/tree-f-visualizer/SKILL.md .claude/skills/pass-sequence/SKILL.md .claude/skills/regen-workflow/SKILL.md CONVENTIONS.md

Write the one page a team member reads before touching the repository: how a building block travels recipe → apply → verify →
commit → ledger → tree → workbook → index → review → replay → push, which of the three surfaces (developer shell, CI check, bot
commit) performs each stage, and one section per tool with the same six questions (problem, when, commands, what it writes, how to
read the output, what it did or would have done here).

1. `docs/execution_surfaces_tooling.yaml` — a pass-sequence spec with exactly three surfaces D/C/B, one layer per stage of the loop
   (U0–U11), the loop as Pipeline steps with the one LIVE gate (the push), a Remediation row per failure this project actually met
   (with the commit or test holding the fix), equality checks for every generated artefact. Build
   `docs/EXECUTION_SURFACES_TOOLING.xlsx` with `--verify`; quote every plain scalar containing ": ".
2. `UNIVERSAL_WORKFLOW.md` at the repository root — didactic, copy-pasteable from the root, expected outputs quoted verbatim from the
   tools, every count checked against `git log` and `docs/diffs/INDEX.md`; a worked example end to end; a bootstrapping checklist;
   the verify cheat-sheet; the remediation table; FAQ; glossary. No model or tool identifiers.
3. README: a pointer to the page at the top and in "Read in this order"; architecture nodes for the three new files.

Do not change any tool. Facts only: a number you cannot verify from the repository does not go in.
