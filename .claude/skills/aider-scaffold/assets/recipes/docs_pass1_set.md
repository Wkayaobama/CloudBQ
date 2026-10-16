# Recipe — the pass-1 documentation set (pass-sequence order)

/add docs/PASS1_SEQUENCE.md docs/EXECUTION_SURFACES.md docs/execution_surfaces.yaml docs/SCENARIOS.md docs/architecture.yaml README.md cloud_function_new_deals/README.md
/read-only .claude/skills/pass-sequence/SKILL.md .claude/skills/pass-sequence/references/surfaces-spec.md

Produce the four artefacts in the skill's order, documentation only: (1) PASS1_SEQUENCE.md from the template — preconditions, one bash
block of `deploy.sh` steps with look inserts, the dry-run gate, the branch points (delivery via n8n / none; write-back only in C), the
produces/look table, an empty Evidence section until the first run, pitfalls; (2) EXECUTION_SURFACES.md — motions, the parity vocabulary
(outcome parity, stated), the principle, an append-only timeline citing commits, per-lane operations, what stays open; (3)
execution_surfaces.yaml per surfaces-spec.md with the three scenarios as columns, L0–L17, the deploy steps, remediation from the verified
gaps, equality checks, then `build_surfaces_xlsx.py --verify`; (4) SCENARIOS.md condensing the lanes and the recommendation; annotate every
block in docs/architecture.yaml with the same parity words as the layer rows and regenerate the tree. Never compose evidence.
