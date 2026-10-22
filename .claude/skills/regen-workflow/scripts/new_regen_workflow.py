#!/usr/bin/env python3
"""new_regen_workflow.py — write a GitHub Actions workflow of the "run a generator, commit what changed" family.

    S=.claude/skills/regen-workflow/scripts
    python3 $S/new_regen_workflow.py --name "Update README" --run "python3 update_readme.py" --paths README.md \
        --on push:main --on workflow_dispatch                                   # self-contained workflow (default: --mode inline)
    python3 $S/new_regen_workflow.py --name "Update README" --run "…" --paths README.md --mode local        # calls ./.github/workflows/regenerate.yml
    python3 $S/new_regen_workflow.py --name "Update README" --run "…" --paths README.md --mode Owner/Repo@v1     # calls a shared copy
    python3 $S/new_regen_workflow.py --emit-reusable                            # writes .github/workflows/regenerate.yml (the shared one)

Three ways to the same job (checkout → toolchains → run → commit-or-check), one commit step (assets/commit_if_changed.sh):
  inline   everything in the file; no dependency on another workflow — works in any repository as is
  local    a thin caller of ./.github/workflows/regenerate.yml in the same repository (emit it once with --emit-reusable)
  Owner/Repo@ref   a thin caller of that repository's regenerate.yml (a private host repository must allow access: Settings →
           Actions → General → Access → "Accessible from repositories owned by …")
Triggers: --on push[:branch[,branch]] · --on pull_request[:branch] (forces mode check: a PR cannot be pushed to) · --on schedule:"cron"
· --on workflow_dispatch. Commits made with GITHUB_TOKEN do not trigger workflows, so a push-triggered regeneration never loops;
store a PAT as the `REGEN_TOKEN` secret when the regenerated commit must itself run CI. Project-agnostic: nothing here names a repository.
Needs only the standard library; with PyYAML installed the generated file is parsed before it is written (pip install pyyaml).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml                                   # optional: only proves the generated file parses before it is written
except ImportError:                               # pragma: no cover
    yaml = None

HERE = Path(__file__).resolve().parent
COMMIT_SH = (HERE.parent / "assets" / "commit_if_changed.sh").read_text(encoding="utf-8")
BOT_NAME, BOT_EMAIL = "github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "regenerate"


def indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + l if l.strip() else l for l in text.splitlines())


def on_block(specs: list[str]) -> str:
    """--on push:main,release  --on pull_request  --on schedule:'0 6 * * 1'  --on workflow_dispatch  →  the `on:` mapping."""
    kinds: dict[str, list[str]] = {}                                      # one key per kind: a repeated --on push merges its branches
    for spec in specs or ["push:main", "workflow_dispatch"]:
        kind, _, arg = spec.partition(":")
        if kind in ("push", "pull_request"):
            kinds.setdefault(kind, []).extend(b for b in arg.split(",") if b)
        elif kind == "schedule":
            if not arg: raise SystemExit("--on schedule needs a cron expression: --on schedule:'0 6 * * 1'")
            kinds.setdefault(kind, []).append(arg)
        elif kind == "workflow_dispatch":
            kinds.setdefault(kind, [])
        else:
            raise SystemExit(f"unknown trigger {spec!r} (push | pull_request | schedule:<cron> | workflow_dispatch)")
    out = []
    for kind, args in kinds.items():
        if kind in ("push", "pull_request"):
            out.append(f"  {kind}:\n    branches: [{', '.join(dict.fromkeys(args) or ['main'])}]")
        elif kind == "schedule":
            out.append("  schedule:\n" + "\n".join(f"    - cron: '{c}'" for c in args))
        else:
            out.append("  workflow_dispatch:")
    return "on:\n" + "\n".join(out)


def toolchain_steps(python: str, node: str, install: str, concrete: bool) -> str:
    """Setup steps; in the reusable workflow they are conditional on the inputs, inline they are emitted only when asked for."""
    s = []
    if concrete:
        if python: s.append(f"      - name: Set up Python\n        uses: actions/setup-python@v7\n        with:\n          python-version: '{python}'")
        if node: s.append(f"      - name: Set up Node\n        uses: actions/setup-node@v7\n        with:\n          node-version: '{node}'")
        if install: s.append(f"      - name: Install\n        run: python -m pip install -q {install}")
    else:
        s.append("      - name: Set up Python\n        if: inputs.python-version != ''\n        uses: actions/setup-python@v7\n        with:\n          python-version: ${{ inputs.python-version }}")
        s.append("      - name: Set up Node\n        if: inputs.node-version != ''\n        uses: actions/setup-node@v7\n        with:\n          node-version: ${{ inputs.node-version }}")
        s.append("      - name: Install\n        if: inputs.install != ''\n        run: python -m pip install -q ${{ inputs.install }}")
    return "\n".join(s)


def commit_step(paths: str, message: str, mode: str, concrete: bool) -> str:
    env = (f"          PATHS: {yaml_str(paths)}\n          MESSAGE: {yaml_str(message)}\n"
           f"          MODE: ${{{{ github.event_name == 'pull_request' && 'check' || {yaml_str(mode)} }}}}") if concrete else (
           "          PATHS: ${{ inputs.paths }}\n          MESSAGE: ${{ inputs.message }}\n"
           "          MODE: ${{ github.event_name == 'pull_request' && 'check' || inputs.mode }}\n"
           "          BOT_NAME: ${{ inputs.bot-name }}\n          BOT_EMAIL: ${{ inputs.bot-email }}")
    return ("      - name: Commit or check\n        env:\n" + env + "\n          BRANCH: ${{ github.head_ref || (github.ref_type == 'branch' && github.ref_name) || '' }}\n"
            "        run: |\n" + indent(COMMIT_SH, 10))


def yaml_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def inline_workflow(a) -> str:
    runs = "\n".join(f"      - name: Regenerate{'' if len(a.run) == 1 else f' ({i})'}\n        working-directory: {yaml_str(a.working_directory)}\n        run: |\n{indent(r, 10)}" for i, r in enumerate(a.run, 1))
    return f"""name: {yaml_str(a.name)}
# generated by .claude/skills/regen-workflow (new_regen_workflow.py --mode inline); self-contained — edit freely or regenerate
{on_block(a.on)}

concurrency:
  group: regenerate-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: false

jobs:
  regenerate:
    runs-on: ubuntu-latest
    if: ${{{{ github.event_name != 'push' || !contains(github.event.head_commit.message, 'Regenerated-by:') }}}}   # a PAT push of the bot commit must not re-run this
    permissions:
      contents: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
        with:
          fetch-depth: {a.fetch_depth}
          token: ${{{{ secrets.REGEN_TOKEN || github.token }}}}
          persist-credentials: true   # the commit step pushes with the checkout's credentials
{toolchain_steps(a.python, a.node, a.install, True)}
{runs}
{commit_step(a.paths, a.message, a.mode_value, True)}
"""


def caller_workflow(a, uses: str) -> str:
    run = "\n".join(a.run)
    # least privilege in both modes: the reusable workflow reads one secret, so one is passed (never `secrets: inherit`)
    secrets = "    secrets:\n      REGEN_TOKEN: ${{ secrets.REGEN_TOKEN }}   # the only secret the reusable workflow reads\n"
    opt = ""
    if a.node: opt += f"      node-version: {yaml_str(a.node)}\n"
    if a.install: opt += f"      install: {yaml_str(a.install)}\n"
    return f"""name: {yaml_str(a.name)}
# generated by .claude/skills/regen-workflow (new_regen_workflow.py --mode {a.mode}); the steps live in the reusable workflow it calls
{on_block(a.on)}

concurrency:
  group: regenerate-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: false

jobs:
  regenerate:
    uses: {uses}
    if: ${{{{ github.event_name != 'push' || !contains(github.event.head_commit.message, 'Regenerated-by:') }}}}   # a PAT push of the bot commit must not re-run this
    permissions:
      contents: write
{secrets}    with:
      run: |
{indent(run, 8)}
      paths: {yaml_str(a.paths)}
      message: {yaml_str(a.message)}
      mode: {yaml_str(a.mode_value)}
      python-version: {yaml_str(a.python)}
      working-directory: {yaml_str(a.working_directory)}
      fetch-depth: {a.fetch_depth}
{opt}"""


def reusable_workflow() -> str:
    return f"""name: Regenerate and commit
# generated by .claude/skills/regen-workflow (new_regen_workflow.py --emit-reusable). A reusable workflow: run a generator, then
# commit what changed (mode commit) or fail if anything changed (mode check; forced on pull_request, whose merge ref cannot be pushed to).
# Callers in this repository: uses: ./.github/workflows/regenerate.yml · elsewhere: uses: <owner>/<repo>/.github/workflows/regenerate.yml@<ref>
# No concurrency group here: the caller declares it. A called workflow that claims the caller's group is cancelled by GitHub
# ("deadlock detected for concurrency group … between a top level workflow and '<job>'").
on:
  workflow_call:
    inputs:
      run:
        description: Command(s) that regenerate files (multi-line allowed)
        required: true
        type: string
      paths:
        description: Paths to stage, space-separated git pathspecs (deletions inside them are staged too)
        required: true
        type: string
      message:
        description: Commit subject
        required: false
        type: string
        default: 'chore: regenerate generated files'
      mode:
        description: commit (push the result) or check (fail when regeneration changes anything)
        required: false
        type: string
        default: commit
      python-version:
        description: Python to set up ('' to skip)
        required: false
        type: string
        default: '3.12'
      node-version:
        description: Node to set up ('' to skip)
        required: false
        type: string
        default: ''
      install:
        description: pip install arguments, e.g. '-r requirements.txt pyyaml' ('' to skip)
        required: false
        type: string
        default: ''
      working-directory:
        description: Directory the run command executes in
        required: false
        type: string
        default: '.'
      fetch-depth:
        description: Git history depth for the checkout (0 = full; scripts that read history need it)
        required: false
        type: number
        default: 1
      bot-name:
        required: false
        type: string
        default: '{BOT_NAME}'
      bot-email:
        required: false
        type: string
        default: '{BOT_EMAIL}'
    secrets:
      REGEN_TOKEN:
        description: Optional PAT; with it the regenerated commit triggers workflows (GITHUB_TOKEN pushes never do)
        required: false

jobs:
  regenerate:
    runs-on: ubuntu-latest
    if: ${{{{ github.event_name != 'push' || !contains(github.event.head_commit.message, 'Regenerated-by:') }}}}   # a PAT push of the bot commit must not re-run this
    permissions:
      contents: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
        with:
          fetch-depth: ${{{{ inputs.fetch-depth }}}}
          token: ${{{{ secrets.REGEN_TOKEN || github.token }}}}
          persist-credentials: true   # the commit step pushes with the checkout's credentials
{toolchain_steps('', '', '', False)}
      - name: Regenerate
        working-directory: ${{{{ inputs.working-directory }}}}
        run: ${{{{ inputs.run }}}}
{commit_step('', '', '', False)}
"""


def origin_head() -> str | None:
    """The clone's idea of the remote default branch (origin/HEAD), or None when unknown."""
    try:
        ref = subprocess.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        return ref.split("/", 1)[1] if ref.startswith("origin/") else ref
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="workflow name, e.g. 'Update README'")
    ap.add_argument("--run", action="append", default=[], help="command that regenerates files (repeatable → steps)")
    ap.add_argument("--paths", help="paths to stage, space-separated")
    ap.add_argument("--message", help="commit subject (default: 'chore: <name>')")
    ap.add_argument("--on", action="append", default=[], help="push[:branches] | pull_request[:branches] | schedule:<cron> | workflow_dispatch (repeatable; default push:main + workflow_dispatch)")
    ap.add_argument("--python", default="3.12", help="Python version ('' to skip)")
    ap.add_argument("--node", default="", help="Node version ('' to skip)")
    ap.add_argument("--install", default="", help="pip install arguments ('' to skip)")
    ap.add_argument("--working-directory", default=".")
    ap.add_argument("--fetch-depth", type=int, default=1)
    ap.add_argument("--check", action="store_true", help="mode check instead of commit (fail when regeneration changes files)")
    ap.add_argument("--mode", default="inline", help="inline | local | <owner>/<repo>@<ref>")
    ap.add_argument("--emit-reusable", action="store_true", help="write the reusable workflow itself (.github/workflows/regenerate.yml)")
    ap.add_argument("--out", help="output path (default .github/workflows/<slug>.yml)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    ap.add_argument("--print", action="store_true", help="print instead of writing")
    a = ap.parse_args(argv)

    if a.emit_reusable:
        text, out = reusable_workflow(), Path(a.out or ".github/workflows/regenerate.yml")
    else:
        for req in ("name", "paths"):
            if not getattr(a, req): ap.error(f"--{req} is required")
        if not a.run: ap.error("--run is required (repeatable)")
        a.message = a.message or f"chore: {a.name.lower()}"
        a.mode_value = "check" if a.check else "commit"
        if a.mode == "inline": text = inline_workflow(a)
        elif a.mode == "local": text = caller_workflow(a, "./.github/workflows/regenerate.yml")
        elif re.fullmatch(r"[\w.-]+/[\w.-]+@[\w./-]+", a.mode):
            owner_repo, ref = a.mode.split("@", 1); text = caller_workflow(a, f"{owner_repo}/.github/workflows/regenerate.yml@{ref}")
        else: ap.error("--mode must be inline, local or <owner>/<repo>@<ref>")
        out = Path(a.out or f".github/workflows/{slug(a.name)}.yml")
    if yaml is not None:                                                  # the file must parse before it is written
        doc = yaml.safe_load(text)
        assert "jobs" in doc and (True in doc or "on" in doc), "generated workflow lacks on:/jobs:"
    else:
        print("note: PyYAML is not installed, so the generated file was not parse-checked (pip install pyyaml)", file=sys.stderr)
    if not a.emit_reusable:
        implicit = [s for s in (a.on or ["push:main"]) if s.partition(":")[0] in ("push", "pull_request") and not s.partition(":")[2]]
        head = origin_head()
        if (implicit or not a.on) and head and head != "main":
            print(f"note: triggers were written for branch 'main'; this clone's origin/HEAD is '{head}' — pass --on push:{head} if that is the default branch", file=sys.stderr)
    if a.print:
        if a.mode == "local" and not Path(".github/workflows/regenerate.yml").exists():
            print("note: ./.github/workflows/regenerate.yml does not exist here — the caller needs it (run --emit-reusable)", file=sys.stderr)
        sys.stdout.write(text); return 0
    if out.exists() and not a.force:
        sys.exit(f"{out} exists (use --force to overwrite)")
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    reusable = out.parent / "regenerate.yml"
    if a.mode == "local" and not reusable.exists():                       # a caller without its callee fails on GitHub at parse time
        reusable.write_text(reusable_workflow(), encoding="utf-8"); print(f"wrote {reusable} (the caller needs it; emitted once)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
