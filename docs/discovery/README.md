# Discovery reports (2026-10-05)

Written by the discovery agents before implementation and verified by one adversarial skeptic per scenario (verdicts CONFIRMED /
CONTESTED / REFUTED per gap are summarised in `docs/execution_surfaces.yaml` → Remediation, and in `docs/EXECUTION_SURFACES.md` § 3).
The recipes under `.claude/skills/aider-scaffold/assets/recipes/` and the commit messages cite these files by name.

| File | What it established |
|---|---|
| `scenario_A.md` | Cloud Run function audit against current Google Cloud docs; 17 gaps (11 confirmed); lane cells; building blocks |
| `scenario_B.md` | n8n on Cloud Run as documented by n8n and Google; node capabilities from source; B1 vs B2; 18 gaps (16 confirmed) |
| `scenario_C.md` | HubSpot → BigQuery routes, SQL parity harness (DuckDB, 4,000 deals), batch-update semantics, Breeze/HubSQL limits; 14 gaps |
| `scorer_repos.md` | The JS scorer named in main.py exists in no repository; remote-JS write patterns found in HubSpot-Ruler / Hs-Logic / mir-load |
| `pass_sequence_port.md` | How the mr-load `pass-sequence` skill was ported (generic vs project-specific; scripts proven on the real mr-load spec) |
| `synthesis.md` | How the verified results became the lane workbook spec; the parallel lane; the recommendation |
