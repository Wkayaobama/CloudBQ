#!/usr/bin/env python3
"""Docs stay consistent with each other and with the repo.

    python3 tests/test_docs_consistency.py     or     python3 -m pytest tests -q

- every annotated block's parity word equals the parity of its primary layer row in docs/execution_surfaces.yaml;
- every new/modify block under the scenario directories names a recipe, and every named recipe exists;
- every layer id used in annotations is declared; parity words are the three allowed ones.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIRS = ("cloud_function_new_deals/", "deploy/", "workflows/", "sql/", "writeback/", "scoring/", "tests/")


def _load():
    arch = yaml.safe_load((ROOT / "docs" / "architecture.yaml").read_text())
    spec = yaml.safe_load((ROOT / "docs" / "execution_surfaces.yaml").read_text())
    return arch, {L["id"]: L["parity"] for L in spec["layers"]}


def test_annotation_parity_matches_layer_rows():
    arch, lp = _load(); bad = []
    for path, ann in arch["nodes"].items():
        layer = (ann.get("layers") or [ann.get("layer")])[0]
        if ann.get("parity") and layer in lp and ann["parity"] != lp[layer]: bad.append((path, layer, ann["parity"], lp[layer]))
    assert not bad, bad


def test_every_scenario_block_has_an_existing_recipe():
    arch, _ = _load(); missing, dangling = [], []
    for path, ann in arch["nodes"].items():
        if path.startswith(SCENARIO_DIRS) and ann.get("status") in ("new", "modify") and not ann.get("recipe"): missing.append(path)
        if ann.get("recipe") and not (ROOT / ann["recipe"]).exists(): dangling.append((path, ann["recipe"]))
    assert not missing, missing
    assert not dangling, dangling


def test_layers_and_words_are_declared():
    arch, _ = _load(); declared = set(arch["layers"]); bad = []
    for path, ann in arch["nodes"].items():
        for L in (ann.get("layers") or [ann.get("layer")]):
            if L not in declared: bad.append((path, L))
        if ann.get("parity") not in (None, "Parallel", "Conditional", "Divergent"): bad.append((path, ann.get("parity")))
    assert not bad, bad


if __name__ == "__main__":
    test_annotation_parity_matches_layer_rows(); test_every_scenario_block_has_an_existing_recipe(); test_layers_and_words_are_declared()
    print("docs consistency OK")
