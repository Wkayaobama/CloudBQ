#!/usr/bin/env python3
"""regen-workflow skill: the generator's three shapes parse and carry the right job; the commit step behaves in a real repository;
the README index is idempotent; the diff ledger skips Regenerated-by commits.

    python3 -m pytest tests/test_regen_workflow.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "regen-workflow"
GEN = SKILL / "scripts" / "new_regen_workflow.py"
COMMIT = SKILL / "assets" / "commit_if_changed.sh"
INDEX = SKILL / "assets" / "update_readme_index.py"
LEDGER = ROOT / ".claude" / "skills" / "aider-scaffold" / "scripts" / "diff_ledger.py"


def gen(*args: str) -> dict:
    out = subprocess.run([sys.executable, str(GEN), "--print", *args], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    doc = yaml.safe_load(out)
    return {"text": out, "doc": doc, "on": doc.get("on", doc.get(True))}


def test_inline_workflow_shape():
    g = gen("--name", "Update README", "--run", "python3 update_readme.py", "--paths", "README.md", "--on", "push:main", "--on", "workflow_dispatch")
    job = g["doc"]["jobs"]["regenerate"]
    assert g["on"]["push"]["branches"] == ["main"] and "workflow_dispatch" in g["on"]
    assert job["permissions"] == {"contents": "write"} and job["runs-on"] == "ubuntu-latest"
    names = [s.get("name") for s in job["steps"]]
    assert names == ["Checkout repository", "Set up Python", "Regenerate", "Commit or check"], names
    assert "ref" not in job["steps"][0]["with"], "the event's default ref: a local branch on push, the merge ref on pull_request (forks included)"
    assert job["steps"][0]["uses"] == "actions/checkout@v7" and job["steps"][0]["with"]["persist-credentials"] is True
    assert "Regenerated-by:" in job["if"] and "github.ref_type == 'branch'" in job["steps"][-1]["env"]["BRANCH"]
    assert "git diff --staged --quiet" in job["steps"][-1]["run"] and "No changes to commit" in job["steps"][-1]["run"]
    assert job["steps"][-1]["env"]["PATHS"] == "README.md" and "pull_request" in job["steps"][-1]["env"]["MODE"]


def test_local_and_remote_callers():
    local = gen("--name", "Trees", "--run", "python3 tree.py", "--paths", "docs/*.txt", "--mode", "local", "--check")["doc"]["jobs"]["regenerate"]
    assert local["uses"] == "./.github/workflows/regenerate.yml" and local["permissions"] == {"contents": "write"}
    assert local["with"]["paths"] == "docs/*.txt" and local["with"]["mode"] == "check" and local["with"]["run"].strip() == "python3 tree.py"
    assert "Regenerated-by:" in local["if"]
    assert local["secrets"] == "inherit"
    g = gen("--name", "Trees", "--run", "python3 tree.py", "--paths", "docs", "--mode", "Owner/Repo@v1")
    remote = g["doc"]["jobs"]["regenerate"]
    assert remote["uses"] == "Owner/Repo/.github/workflows/regenerate.yml@v1"
    assert remote["secrets"] == {"REGEN_TOKEN": "${{ secrets.REGEN_TOKEN }}"}, "a shared workflow in another repository never inherits every secret"
    assert g["doc"]["concurrency"]["group"].startswith("regenerate-")


def test_triggers_merge_by_kind():
    on = gen("--name", "x", "--run", "true", "--paths", "a", "--on", "push:main", "--on", "push:dev,main", "--on", "schedule:0 6 * * 1", "--on", "schedule:0 18 * * 5", "--on", "workflow_dispatch")["on"]
    assert on["push"]["branches"] == ["main", "dev"] and [s["cron"] for s in on["schedule"]] == ["0 6 * * 1", "0 18 * * 5"] and "workflow_dispatch" in on
    assert list(on) == ["push", "schedule", "workflow_dispatch"]
    assert gen("--name", "x", "--run", "true", "--paths", "a", "--on", "pull_request")["on"]["pull_request"]["branches"] == ["main"]


def test_reusable_workflow_shape():
    g = gen("--emit-reusable")
    call = g["on"]["workflow_call"]
    assert set(call["inputs"]) >= {"run", "paths", "message", "mode", "python-version", "node-version", "install", "working-directory", "fetch-depth"}
    assert call["inputs"]["run"]["required"] and call["inputs"]["paths"]["required"]
    assert "REGEN_TOKEN" in call["secrets"] and call["secrets"]["REGEN_TOKEN"]["required"] is False
    job = g["doc"]["jobs"]["regenerate"]
    assert job["permissions"] == {"contents": "write"} and job["steps"][-1]["name"] == "Commit or check"
    assert COMMIT.read_text().splitlines()[-1].strip() in job["steps"][-1]["run"], "the shell is embedded verbatim"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp: Path) -> Path:
    origin = tmp / "origin.git"; subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp / "work"; subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.com"); _git(work, "config", "user.name", "t"); _git(work, "checkout", "-q", "-b", "main")
    (work / "README.md").write_text("# demo\n"); _git(work, "add", "README.md"); _git(work, "commit", "-q", "-m", "init"); _git(work, "push", "-q", "-u", "origin", "main")
    return work


def _commit_step(work: Path, mode: str, paths: str = "README.md generated.txt", **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    env.update({"PATHS": paths, "MESSAGE": "chore: regenerate demo", "MODE": mode}); env.update(extra)
    return subprocess.run(["bash", str(COMMIT)], cwd=work, env=env, capture_output=True, text=True)


def test_commit_step_in_a_repository():
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t))
        r = _commit_step(work, "commit"); assert r.returncode == 0 and "No changes to commit" in r.stdout, r.stdout + r.stderr
        (work / "generated.txt").write_text("v1\n")
        r = _commit_step(work, "commit"); assert r.returncode == 0 and "pushed to main" in r.stdout, r.stdout + r.stderr
        body = _git(work, "log", "-1", "--format=%s%n%b", "origin/main")
        assert body.startswith("chore: regenerate demo") and "Regenerated-by:" in body and _git(work, "log", "-1", "--format=%an", "origin/main") == "github-actions[bot]"
        (work / "generated.txt").write_text("v2\n")
        r = _commit_step(work, "check"); assert r.returncode == 1 and "regeneration changed" in r.stderr, r.stdout + r.stderr
        assert _git(work, "log", "-1", "--format=%s", "origin/main") == "chore: regenerate demo", "check mode must not push"


def test_commit_step_actions_shape():
    """The trailer names the run; a run started from a tag, or a detached checkout without BRANCH, refuses to push (exit 2)."""
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t))
        (work / "generated.txt").write_text("v1\n")
        r = _commit_step(work, "commit", GITHUB_RUN_ID="42", GITHUB_WORKFLOW="Update README", GITHUB_REPOSITORY="o/r", GITHUB_SERVER_URL="https://github.com", BRANCH="main")
        assert r.returncode == 0 and "pushed to main" in r.stdout, r.stdout + r.stderr
        assert "Regenerated-by: Update README (https://github.com/o/r/actions/runs/42)" in _git(work, "log", "-1", "--format=%b", "origin/main")
        (work / "generated.txt").write_text("v2\n")
        r = _commit_step(work, "commit", GITHUB_REF_TYPE="tag", BRANCH="main"); assert r.returncode == 2 and "not a branch" in r.stderr, r.stdout + r.stderr
        _git(work, "reset", "-q", "--hard", "origin/main"); _git(work, "checkout", "-q", "--detach")
        (work / "generated.txt").write_text("v3\n")
        r = _commit_step(work, "commit"); assert r.returncode == 2 and "detached HEAD" in r.stderr, r.stdout + r.stderr
        assert _git(work, "log", "-1", "--format=%b", "origin/main").count("Regenerated-by") == 1, "neither refused run may push"


def test_commit_step_globs_stage_deletions():
    """A glob in PATHS reaches git unexpanded, so a file the generator removed is committed as a deletion."""
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t)); (work / "docs").mkdir()
        for n in "ab": (work / "docs" / f"{n}.txt").write_text(f"{n}\n")
        _git(work, "add", "docs"); _git(work, "commit", "-q", "-m", "docs"); _git(work, "push", "-q", "origin", "main")
        (work / "docs" / "b.txt").unlink(); (work / "docs" / "a.txt").write_text("a2\n")
        r = _commit_step(work, "commit", paths="docs/*.txt missing/*.json"); assert r.returncode == 0 and "pushed to main" in r.stdout and "nothing matched missing/*.json" in r.stdout, r.stdout + r.stderr
        assert _git(work, "ls-tree", "--name-only", "origin/main", "docs/") == "docs/a.txt"


def test_commit_step_reports_git_errors():
    """Only an unmatched pathspec is tolerated; any other `git add` failure fails the step instead of reading as 'No changes'."""
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t)); (work / "README.md").write_text("# demo\n\nchanged\n")
        (work / ".git" / "index.lock").write_text("")
        r = _commit_step(work, "commit"); assert r.returncode == 1 and "index.lock" in r.stderr and "No changes" not in r.stdout, r.stdout + r.stderr


def test_commit_step_retries_a_race_and_stops_on_a_refusal():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); work = _repo(tmp); origin = tmp / "origin.git"
        other = tmp / "other"; subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        _git(other, "config", "user.email", "o@example.com"); _git(other, "config", "user.name", "o")
        (other / "other.txt").write_text("o\n"); _git(other, "add", "other.txt"); _git(other, "commit", "-q", "-m", "other"); _git(other, "push", "-q", "origin", "main")
        (work / "generated.txt").write_text("v1\n")                              # work is now one commit behind origin
        r = _commit_step(work, "commit"); assert r.returncode == 0 and "rebasing" in r.stdout and "pushed to main" in r.stdout, r.stdout + r.stderr
        assert _git(work, "log", "--format=%s", "origin/main").splitlines() == ["chore: regenerate demo", "other", "init"]
        hook = origin / "hooks" / "pre-receive"; hook.write_text("#!/bin/sh\necho refused by policy >&2\nexit 1\n"); hook.chmod(0o755)
        (work / "generated.txt").write_text("v2\n")
        r = _commit_step(work, "commit"); assert r.returncode == 1 and "did not move" in r.stderr and r.stdout.count("push attempt") == 0, r.stdout + r.stderr


def test_check_mode_exit_code_on_a_large_diff():
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t)); (work / "generated.txt").write_text("".join(f"line {i}\n" for i in range(20000)))
        r = _commit_step(work, "check"); assert r.returncode == 1 and "regeneration changed" in r.stderr, (r.returncode, r.stderr[-300:])


def test_readme_index_titles_hidden_dirs_and_line_endings():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); docs = d / "docs"; docs.mkdir(); (docs / ".cache").mkdir()
        (docs / "fence.md").write_text("```bash\n# install deps first\n```\n\n# Real Heading\n")
        (docs / "bom.md").write_bytes(b"\xef\xbb\xbf# BOM Title\n")
        (docs / "setext.md").write_text("Setext Title\n============\n\ntext\n")
        (docs / ".cache" / "x.md").write_text("# Hidden\n")
        readme = d / "README.md"; readme.write_bytes(b"# Demo\r\n\r\nintro\r\n")
        run = lambda *a: subprocess.run([sys.executable, str(INDEX), "--readme", str(readme), *a], capture_output=True, text=True)
        assert run("--dir", str(docs)).returncode == 0
        raw = readme.read_bytes(); text = raw.decode()
        assert raw.count(b"\r\n") == raw.count(b"\n"), "CRLF README stays CRLF"
        assert "[Real Heading](docs/fence.md)" in text and "[BOM Title](docs/bom.md)" in text and "[Setext Title](docs/setext.md)" in text and "Hidden" not in text
        assert run("--dir", str(docs), "--check").returncode == 0
        fresh = d / "NEW.md"; assert subprocess.run([sys.executable, str(INDEX), "--readme", str(fresh), "--dir", str(docs)], capture_output=True).returncode == 0
        assert fresh.read_text().startswith("## Documents\n"), repr(fresh.read_text()[:40])
        outside = d / "elsewhere"; outside.mkdir(); (outside / "z.md").write_text("# Z\n")
        r = subprocess.run([sys.executable, str(INDEX), "--readme", str(d / "sub" / "README.md"), "--dir", str(outside)], capture_output=True, text=True)
        assert r.returncode != 0 and "outside" in r.stderr, r.stderr


def test_readme_index_is_idempotent():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); (d / "docs").mkdir(); (d / "docs" / "b.md").write_text("# Second\n"); (d / "docs" / "a.md").write_text("no heading\n")
        readme = d / "README.md"; readme.write_text("# Demo\n\nintro\n")
        run = lambda *a: subprocess.run([sys.executable, str(INDEX), "--readme", str(readme), "--dir", str(d / "docs"), *a], capture_output=True, text=True)
        r = run(); assert r.returncode == 0 and "updated" in r.stdout, r.stdout + r.stderr
        text = readme.read_text()
        assert "<!-- regen:docs-index start -->" in text and "- [a.md](docs/a.md)" in text and "- [Second](docs/b.md)" in text and "## Documents" in text
        assert run("--check").returncode == 0 and readme.read_text() == text, "second run changes nothing"
        (d / "docs" / "c.md").write_text("# Third\n")
        assert run("--check").returncode == 1, "a new file makes the block stale"
        assert run().returncode == 0 and "- [Third](docs/c.md)" in readme.read_text()


def test_ledger_skips_regenerated_commits():
    with tempfile.TemporaryDirectory() as t:
        work = _repo(Path(t))
        (work / "a.txt").write_text("a\n"); _git(work, "add", "a.txt"); _git(work, "commit", "-q", "-m", "feat: a")
        (work / "gen.txt").write_text("g\n"); _git(work, "add", "gen.txt"); _git(work, "commit", "-q", "-m", "chore: regenerate", "-m", "Regenerated-by: Update README (https://example/run/1)")
        r = subprocess.run([sys.executable, str(LEDGER)], cwd=work, capture_output=True, text=True, check=True)
        index = (work / "docs" / "diffs" / "INDEX.md").read_text()
        assert "feat: a" in r.stdout or "feat-a" in r.stdout
        rows = [l for l in index.splitlines() if ".patch](" in l]
        assert len(rows) == 2 and "init" in rows[0] and "feat-a" in rows[1] and not any("regenerate" in r.lower() for r in rows), rows
        _git(work, "add", "docs"); _git(work, "commit", "-q", "-m", "docs: diff ledger update")
        assert subprocess.run([sys.executable, str(LEDGER), "--check"], cwd=work, capture_output=True, text=True).returncode == 0


if __name__ == "__main__":
    for name, f in sorted(globals().items()):
        if name.startswith("test_") and callable(f):
            f()
    print("regen-workflow OK")
