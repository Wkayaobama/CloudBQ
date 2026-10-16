#!/usr/bin/env python3
"""The notebook that mirrors the Pass-1 sequence stays valid, compilable, complete and output-free.

    python3 tests/test_notebook.py     or     python3 -m pytest tests -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks" / "cloudbq_deploy_and_witness.ipynb"
STEPS = ["check-env", "enable-apis", "iam", "tables", "secret", "deploy", "invoker", "dry", "run SEALSQ", "run ICALPS", "probe", "enable", "status"]


def _nb():
    return json.loads(NB.read_text(encoding="utf-8"))


def _code(cell):
    return "".join(cell["source"])


def test_notebook_is_valid():
    nb = _nb()
    assert nb["nbformat"] == 4 and nb["metadata"]["kernelspec"]["language"] == "python"
    try:
        import nbformat
    except ImportError:
        return
    nbformat.validate(nbformat.reads(NB.read_text(encoding="utf-8"), as_version=4))


def test_code_cells_compile():
    for i, c in enumerate(_nb()["cells"]):
        if c["cell_type"] == "code":
            src = "\n".join(l for l in _code(c).splitlines() if not l.lstrip().startswith(("!", "%")))   # IPython magics stripped
            compile(src, f"{NB.name}#cell{i}", "exec")


def test_every_deploy_step_is_mirrored_in_order():
    text = "\n".join(_code(c) for c in _nb()["cells"] if c["cell_type"] == "code")
    assert "DRYRUN=1 bash {D} all" in text
    positions = [text.find(f'bash {{D}} {s}"') for s in STEPS]   # closing quote: `enable` must not match `enable-apis`
    assert all(p >= 0 for p in positions), [s for s, p in zip(STEPS, positions) if p < 0]
    assert positions == sorted(positions), "steps out of the deploy.sh order"


def test_enable_is_flag_guarded_and_secret_is_prompted():
    cells = [_code(c) for c in _nb()["cells"] if c["cell_type"] == "code"]
    enable = next(c for c in cells if 'bash {D} enable"' in c)
    assert enable.index("assert ") < enable.index('bash {D} enable"')
    secret = next(c for c in cells if "bash {D} secret" in c)
    assert "getpass" in secret and 'env={"HUBSPOT_TOKEN"' in secret


def test_no_outputs_and_no_secrets_committed():
    for c in _nb()["cells"]:
        if c["cell_type"] == "code":
            assert c["outputs"] == [] and c["execution_count"] is None, "commit the notebook without outputs"
    text = NB.read_text(encoding="utf-8")
    assert not re.search(r"pat-(na|eu)\d-[0-9a-f-]{20,}", text), "HubSpot token pattern in the notebook"


if __name__ == "__main__":
    for t in (test_notebook_is_valid, test_code_cells_compile, test_every_deploy_step_is_mirrored_in_order, test_enable_is_flag_guarded_and_secret_is_prompted, test_no_outputs_and_no_secrets_committed):
        t()
    print("notebook OK")
