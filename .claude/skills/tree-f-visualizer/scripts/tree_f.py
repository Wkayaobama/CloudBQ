#!/usr/bin/env python3
"""tree_f — architecture tree in Windows `tree /f` fashion: directory walk + annotations → manifest, ASCII, HTML.

    python3 tree_f.py --root . --annotations docs/architecture.yaml \
        --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt \
        --out-html docs/architecture_tree.html [--scenario A] [--annotate] [--exclude .git,node_modules]

The walk gives what exists; the annotations YAML (or JSON) adds meaning per path (scenarios, layer, role,
status, parity, notes, recipe) and may name paths that do not exist yet (status: proposed) — they are drawn
dashed in the HTML and tagged in the ASCII when --annotate is set. Nothing in this file is project-specific:
labels, scenarios and layers all come from the annotations file.

Annotations format (YAML):
    project: <name>                      # title of the page
    scenarios: {A: "<label>", B: "<label>"}
    layers: {L0: "<label>", ...}         # optional, shown in the details panel
    nodes:
      path/to/file.py:  {scenarios: [A], layer: L5, role: "...", status: existing|modify|new|proposed,
                         parity: Parallel|Conditional|Divergent, notes: "...", recipe: "path/to/recipe.md"}
      path/to/dir/:     {...}            # trailing slash = directory

`tree /f` rendering rules (Windows): header "Folder PATH listing for volume <v>" + "Volume serial number is <s>",
root line, a directory's files first (prefix + "│   " when the directory also has sub-directories, else four spaces),
then a spacer line (prefix + "│") when files precede sub-directories, then "├───name" / "└───name" with the child
prefix "│   " / "    ", and after a directory that has no sub-directories a spacer line equal to its child prefix
(right-stripped). The algorithm below is also implemented in assets/template.html so "Copy as tree /f" matches.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath

DEFAULT_EXCLUDES = ".git,node_modules,.venv,venv,__pycache__,.pytest_cache,.mypy_cache,.ruff_cache,dist,build,.aider*,.DS_Store"
STATUSES = ("existing", "modify", "new", "proposed")
PARITY = ("Parallel", "Conditional", "Divergent")


# ----------------------------------------------------------------------------- annotations
def load_annotations(path: str | None) -> dict:
    if not path:
        return {"project": "", "scenarios": {}, "layers": {}, "nodes": {}}
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError:  # pragma: no cover
            sys.exit("annotations are YAML but PyYAML is missing: pip install pyyaml (or pass a .json file)")
        data = yaml.safe_load(text) or {}
    data.setdefault("project", ""); data.setdefault("scenarios", {}); data.setdefault("layers", {}); data.setdefault("nodes", {})
    nodes = {}
    for raw_path, ann in (data["nodes"] or {}).items():
        ann = dict(ann or {})
        is_dir = raw_path.endswith("/")
        key = str(PurePosixPath(raw_path.strip("/")))
        ann.setdefault("kind", "dir" if is_dir else "file")
        ann.setdefault("status", "existing")
        if ann["status"] not in STATUSES:
            sys.exit(f"{raw_path}: status must be one of {STATUSES}, got {ann['status']!r}")
        if ann.get("parity") and ann["parity"] not in PARITY:
            sys.exit(f"{raw_path}: parity must be one of {PARITY}, got {ann['parity']!r}")
        scen = ann.get("scenarios") or []
        ann["scenarios"] = [str(s) for s in (scen if isinstance(scen, list) else [scen])]
        nodes[key] = ann
    data["nodes"] = nodes
    return data


# ----------------------------------------------------------------------------- walk
def _excluded(name: str, rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in patterns)


def walk(root: Path, excludes: list[str]) -> dict:
    """Directory tree as nested dicts: {name, kind, path, children}. Directories first, then files, both sorted."""
    def node(p: Path, rel: str) -> dict:
        n = {"name": p.name if rel else root.resolve().name, "kind": "dir", "path": rel, "exists": True, "children": []}
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            entries = []
        for e in entries:
            r = f"{rel}/{e.name}" if rel else e.name
            if _excluded(e.name, r, excludes):
                continue
            if e.is_dir():
                n["children"].append(node(e, r))
            else:
                n["children"].append({"name": e.name, "kind": "file", "path": r, "exists": True})
        return n
    return node(root, "")


def graft_proposed(tree: dict, nodes: dict) -> None:
    """Add annotated paths that are not on disk (status proposed/new) so the architecture shows them."""
    for key, ann in nodes.items():
        parts = key.split("/")
        cur = tree
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            match = next((c for c in cur["children"] if c["name"] == part), None)
            if match is None:
                kind = ann["kind"] if last else "dir"
                match = {"name": part, "kind": kind, "path": "/".join(parts[: i + 1]), "exists": False}
                if kind == "dir":
                    match["children"] = []
                cur["children"].append(match)
                cur["children"].sort(key=lambda c: (c["kind"] != "dir", c["name"].lower()))
            if not last:
                cur = match
                if "children" not in cur:  # a file annotated as a parent: coerce
                    cur["kind"] = "dir"; cur["children"] = []


def annotate(tree: dict, nodes: dict) -> None:
    def visit(n: dict) -> None:
        ann = nodes.get(n["path"])
        if ann:
            n["ann"] = {k: v for k, v in ann.items() if k != "kind"}
            if not n["exists"] and n["ann"].get("status") == "existing":
                n["ann"]["status"] = "proposed"
        for c in n.get("children", []):
            visit(c)
    visit(tree)


def filter_scenario(tree: dict, scenario: str | None, keep_unannotated: bool) -> dict | None:
    """Keep nodes annotated with the scenario (and their ancestors); unannotated nodes only when asked."""
    if not scenario:
        return tree
    def keep(n: dict) -> dict | None:
        ann = n.get("ann")
        mine = bool(ann and scenario in ann.get("scenarios", []))
        if n["kind"] == "dir":
            kids = [k for k in (keep(c) for c in n.get("children", [])) if k]
            if kids or mine or (keep_unannotated and not ann):
                m = dict(n); m["children"] = kids; return m
            return None
        return dict(n) if (mine or (keep_unannotated and not ann)) else None
    out = keep(tree)
    if out is None:
        out = dict(tree); out["children"] = []
    return out


# ----------------------------------------------------------------------------- ascii (tree /f)
def render_ascii(tree: dict, root_label: str, volume: str, serial: str, tags: bool) -> str:
    lines = [f"Folder PATH listing for volume {volume}", f"Volume serial number is {serial}", root_label]

    def tag(n: dict) -> str:
        a = n.get("ann")
        if not tags or not a:
            return ""
        bits = []
        if a.get("scenarios"): bits.append(",".join(a["scenarios"]))
        if a.get("layer"): bits.append(str(a["layer"]))
        if a.get("status") and a["status"] != "existing": bits.append(a["status"])
        if a.get("parity"): bits.append(a["parity"])
        return f"  {{{' · '.join(bits)}}}" if bits else ""

    def emit(d: dict, prefix: str) -> None:
        kids = d.get("children", [])
        files = [c for c in kids if c["kind"] != "dir"]
        dirs = [c for c in kids if c["kind"] == "dir"]
        col = "│   " if dirs else "    "
        for f in files:
            lines.append(f"{prefix}{col}{f['name']}{tag(f)}")
        if dirs:
            if files:
                lines.append(f"{prefix}│")
            for i, sub in enumerate(dirs):
                last = i == len(dirs) - 1
                lines.append(f"{prefix}{'└───' if last else '├───'}{sub['name']}{tag(sub)}")
                emit(sub, prefix + ("    " if last else "│   "))
        else:
            lines.append(prefix.rstrip())

    emit(tree, "")
    return "\n".join(lines).rstrip("\n") + "\n"


# ----------------------------------------------------------------------------- html
def render_html(manifest: dict, template_path: Path) -> str:
    tpl = template_path.read_text(encoding="utf-8")
    payload = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    if "/*__MANIFEST__*/" not in tpl:
        sys.exit(f"{template_path}: missing /*__MANIFEST__*/ placeholder")
    title = manifest.get("project") or manifest["tree"]["name"]
    return tpl.replace("/*__MANIFEST__*/", payload).replace("__TITLE__", f"{title} Architecture Tree")


# ----------------------------------------------------------------------------- main
def build_manifest(root: Path, ann: dict, excludes: list[str], scenario: str | None, keep_unannotated: bool,
                   root_label: str, volume: str, serial: str) -> dict:
    tree = walk(root, excludes)
    graft_proposed(tree, ann["nodes"])
    annotate(tree, ann["nodes"])
    tree = filter_scenario(tree, scenario, keep_unannotated)
    counts = {"dirs": 0, "files": 0, "annotated": 0, "proposed": 0}
    def count(n: dict) -> None:
        counts["dirs" if n["kind"] == "dir" else "files"] += 1
        if n.get("ann"): counts["annotated"] += 1
        if not n.get("exists", True): counts["proposed"] += 1
        for c in n.get("children", []): count(c)
    count(tree)
    return {"project": ann.get("project") or root.resolve().name, "root": str(root), "root_label": root_label,
            "volume": volume, "serial": serial, "scenario_filter": scenario,
            "scenarios": ann.get("scenarios", {}), "layers": ann.get("layers", {}),
            "statuses": list(STATUSES), "parity": list(PARITY), "counts": counts, "tree": tree}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--annotations", help="YAML or JSON annotations (see module doc)")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDES, help="comma-separated glob patterns (name or relative path)")
    ap.add_argument("--scenario", help="keep only nodes annotated with this scenario id (plus ancestors)")
    ap.add_argument("--keep-unannotated", action="store_true", help="with --scenario: also keep nodes without annotation")
    ap.add_argument("--annotate", action="store_true", help="append {scenarios · layer · status · parity} tags in the ASCII")
    ap.add_argument("--root-label", help="root line of the listing (default: the root directory name)")
    ap.add_argument("--volume", help="volume name in the header (default: project name)")
    ap.add_argument("--serial", help="serial in the header (default: derived from the manifest content)")
    ap.add_argument("--out-json"); ap.add_argument("--out-ascii"); ap.add_argument("--out-html")
    ap.add_argument("--template", default=str(Path(__file__).resolve().parent.parent / "assets" / "template.html"))
    a = ap.parse_args(argv)

    root = Path(a.root)
    if not root.is_dir():
        sys.exit(f"--root {a.root} is not a directory")
    ann = load_annotations(a.annotations)
    excludes = [p.strip() for p in a.exclude.split(",") if p.strip()]
    project = ann.get("project") or root.resolve().name
    manifest = build_manifest(root, ann, excludes, a.scenario, a.keep_unannotated,
                              a.root_label or root.resolve().name, a.volume or project, a.serial or "0000-0000")
    if not a.serial:  # deterministic serial from content, so re-runs on the same tree give the same header
        h = hashlib.sha1(json.dumps(manifest["tree"], sort_keys=True).encode()).hexdigest().upper()
        manifest["serial"] = f"{h[:4]}-{h[4:8]}"
    wrote = []
    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"); wrote.append(a.out_json)
    ascii_text = render_ascii(manifest["tree"], manifest["root_label"], manifest["volume"], manifest["serial"], a.annotate)
    if a.out_ascii:
        Path(a.out_ascii).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_ascii).write_text(ascii_text, encoding="utf-8"); wrote.append(a.out_ascii)
    if a.out_html:
        Path(a.out_html).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_html).write_text(render_html(manifest, Path(a.template)), encoding="utf-8"); wrote.append(a.out_html)
    if not wrote:
        sys.stdout.write(ascii_text)
    else:
        c = manifest["counts"]
        print(f"tree_f: {c['dirs']} dirs, {c['files']} files, {c['annotated']} annotated, {c['proposed']} proposed"
              + (f", scenario {a.scenario}" if a.scenario else "") + " → " + ", ".join(wrote))
    return 0


if __name__ == "__main__":
    sys.exit(main())
