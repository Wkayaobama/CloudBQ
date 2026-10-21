# Recipe — pass-sequence builder: two to six surface columns (tooling block)

/add .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py .claude/skills/pass-sequence/references/surfaces-spec.md
/read-only docs/execution_surfaces.yaml docs/execution_surfaces_tooling.yaml docs/execution_surfaces_l2.yaml

The workbook producer refused anything but exactly three surfaces (the sheets had three surface columns). A project may need a
fourth lane — CloudBQ's pass 3 made the shared SQL implementation an execution surface of its own — so:

1. One column per id under `surfaces:` on the Layers and Pipeline steps sheets, two to six ids; widths derived from the count.
2. The Overview's COUNTIF formulas and `--verify` locate the Parity column from the header row, so the parity arithmetic never
   depends on the number of surfaces.
3. Equality checks keep two command columns: the first surface vs all the others, keyed by the concatenation of the remaining ids
   ("BC", "BCR", "QW"); "BC" stays accepted as the legacy key.
4. Prove no regression: build the three existing specs and `--compare` each against its committed workbook — identical values.
5. Mirror the script and the reference page in IC-DBT-BQ (the skill is installed there unchanged).

Project-agnostic: nothing in the script names a repository or a lane.
