#!/usr/bin/env python3
"""tree_f — architecture tree in Windows `tree /f` fashion: directory walk + annotations → manifest, ASCII, HTML.

    python3 tree_f.py --root . --annotations docs/architecture.yaml \
        --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt \
        --out-html docs/architecture_tree.html [--scenario A] [--exclude .git,node_modules,.venv]

The walk says what exists; the annotations file (YAML or JSON) says what each path means — scenarios, layer,
role, status, parity, notes, recipe — and may name paths that are not on disk yet (status: proposed). Those are
grafted into the tree, drawn dashed in the HTML and tagged in the ASCII when --annotate is set. Nothing in this
file is project-specific: project name, scenario ids, layer ids and every label come from the annotations file.

`tree /f` rendering (Microsoft tree.com behaviour, Unicode glyphs; --ascii-glyphs gives the /A variant):
  header   "Folder PATH listing for volume <label>" (or "Folder PATH listing" when the volume has no label),
           "Volume serial number is <serial>", then the root line.
  files    a directory's files come first, one per line: prefix + column + name, where column is "│   " when the
           directory also has sub-directories and four spaces when it has none (ReactOS tree.c: "|   %s" / "    %s").
  spacer   when files precede sub-directories, one line prefix + "│".
  dirs     "├───name" for every sub-directory but the last, "└───name" for the last; the sub-directory's own lines use
           child prefix prefix + "│   " (not last) or prefix + "    " (last).
  tail     after a directory that has no sub-directories (files only, or empty) one line equal to its child prefix,
           right-stripped — this is the blank/"│" line that separates sibling directories in a real listing.
  empty    directories with nothing left in them after the excludes are not listed: git ships no empty directory, so a
           listing that showed one could never be reproduced from a clone (and --check would fail there).
  order    tree.com does not sort; NTFS enumerates names case-insensitively by up-cased UTF-16 code unit, so the
           renderer sorts by name.upper() (not .lower(): "__init__.py" lands after "workflow_api.py", as on Windows).
The same algorithm is implemented in assets/template.html so "Copy as tree /f" and --out-ascii are byte-identical.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 2
DEFAULT_EXCLUDES = ".git,node_modules,.venv,venv,__pycache__,.pytest_cache,.mypy_cache,.ruff_cache,dist,build,.aider*,.DS_Store"
STATUSES = ("existing", "modify", "new", "proposed")
PARITY = ("Parallel", "Conditional", "Divergent")
GLYPHS = {
    "unicode": {"branch": "├───", "last": "└───", "vert": "│   ", "blank": "    ", "bar": "│"},
    "ascii": {"branch": "+---", "last": "\\---", "vert": "|   ", "blank": "    ", "bar": "|"},
}
ANN_KEYS = ("scenarios", "layer", "role", "status", "parity", "notes", "recipe", "kind", "layers")


# ----------------------------------------------------------------------------- annotations
def load_annotations(path: str | None) -> dict:
    """Read YAML/JSON annotations into {project, scenarios, layers, nodes}; normalise keys; validate vocabulary."""
    data: dict = {}
    if path:
        text = Path(path).read_text(encoding="utf-8")
        if path.endswith(".json"):
            data = json.loads(text)
        else:
            try:
                import yaml  # type: ignore
            except ImportError:  # pragma: no cover
                sys.exit("annotations are YAML but PyYAML is missing: pip install pyyaml (or pass a .json file)")
            data = yaml.safe_load(text) or {}
    for k, default in (("project", ""), ("scenarios", {}), ("layers", {}), ("nodes", {}), ("header", {}), ("exclude", [])):
        data.setdefault(k, default)                       # exclude: project-level extra glob patterns (e.g. "*.patch"), merged with --exclude
    # scenarios / layers accept a mapping (id → label) or a list of {id, label}; order is preserved
    for key in ("scenarios", "layers"):
        v = data[key]
        if isinstance(v, list):
            data[key] = {str(i["id"]): str(i.get("label", i["id"])) for i in v}
        else:
            data[key] = {str(k): str(lbl) for k, lbl in (v or {}).items()}
    errors: list[str] = []
    nodes: dict[str, dict] = {}
    for raw_path, ann in (data["nodes"] or {}).items():
        ann = dict(ann or {})
        unknown = set(ann) - set(ANN_KEYS)
        if unknown:
            errors.append(f"{raw_path}: unknown keys {sorted(unknown)}")
        is_dir = str(raw_path).endswith("/")
        key = str(PurePosixPath(str(raw_path).strip("/")))
        ann.setdefault("kind", "dir" if is_dir else "file")
        if "layers" in ann:                                   # several layers: keep the list, the first one is the primary `layer`
            ls = ann.pop("layers"); ls = ls if isinstance(ls, list) else [ls]
            ann["layers_list"] = [str(x) for x in ls]; ann.setdefault("layer", ann["layers_list"][0])
        ann.setdefault("status", "existing")
        if ann["status"] not in STATUSES:
            errors.append(f"{raw_path}: status must be one of {STATUSES}, got {ann['status']!r}")
        if ann.get("parity") and ann["parity"] not in PARITY:
            errors.append(f"{raw_path}: parity must be one of {PARITY}, got {ann['parity']!r}")
        scen = ann.get("scenarios") or []
        ann["scenarios"] = [str(s) for s in (scen if isinstance(scen, list) else [scen])]
        for s in ann["scenarios"]:
            if data["scenarios"] and s not in data["scenarios"]:
                errors.append(f"{raw_path}: scenario {s!r} is not declared under `scenarios`")
        if ann.get("layer") is not None:
            ann["layer"] = str(ann["layer"])
            if data["layers"] and ann["layer"] not in data["layers"]:
                errors.append(f"{raw_path}: layer {ann['layer']!r} is not declared under `layers`")
            for L in ann.get("layers_list", []):
                if L not in (data.get("layers") or {}): errors.append(f"{raw_path}: layer {L!r} is not declared under `layers`")
        nodes[key] = ann
    if errors:
        sys.exit("annotations invalid:\n  " + "\n  ".join(errors))
    data["nodes"] = nodes
    return data


# ----------------------------------------------------------------------------- walk
def load_gitignore(root: Path) -> list[str]:
    """Patterns from <root>/.gitignore in the simple subset the walker understands (no negation, no '**' ranges)."""
    f = root / ".gitignore"
    if not f.is_file():
        return []
    pats = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("!"):
            continue
        pats.append(s.rstrip("/"))
    return pats


def _excluded(name: str, rel: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = p.lstrip("/")
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*") or rel.startswith(p + "/"):
            return True
    return False


def ntfs_key(name: str) -> str:
    """NTFS enumerates case-insensitively by up-cased UTF-16 code unit; tree.com prints in that order."""
    return name.upper()


def walk(root: Path, excludes: list[str], label: str | None = None) -> dict:
    """Directory tree as nested dicts {name, kind, path, exists, children}; files and dirs each sorted by ntfs_key.
    The root node is named `label` (the project name) rather than the checkout directory, and directories that are
    empty after the excludes are dropped, so the same commit renders byte-identically in any clone."""
    def node(p: Path, rel: str) -> dict:
        n = {"name": (label or root.resolve().name) if not rel else p.name, "kind": "dir", "path": rel, "exists": True, "children": []}
        try:
            entries = list(p.iterdir())
        except PermissionError:
            entries = []
        entries.sort(key=lambda e: (not e.is_dir(), ntfs_key(e.name)))
        for e in entries:
            r = f"{rel}/{e.name}" if rel else e.name
            if _excluded(e.name, r, excludes):
                continue
            if e.is_dir():
                child = node(e, r)
                if child["children"]:  # an empty directory cannot come out of a clone; leave it out
                    n["children"].append(child)
            else:
                n["children"].append({"name": e.name, "kind": "file", "path": r, "exists": True})
        return n
    return node(root, "")


def _sort_children(n: dict) -> None:
    n["children"].sort(key=lambda c: (c["kind"] != "dir", ntfs_key(c["name"])))


def graft_proposed(tree: dict, nodes: dict) -> None:
    """Add annotated paths that are not on disk so the architecture shows the proposal, not only the present."""
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
                _sort_children(cur)
            if not last:
                if "children" not in match:  # a file annotated as a parent: coerce to dir
                    match["kind"] = "dir"; match["children"] = []
                cur = match


def annotate(tree: dict, nodes: dict) -> None:
    def visit(n: dict) -> None:
        ann = nodes.get(n["path"])
        if ann:
            n["ann"] = {k: v for k, v in ann.items() if k != "kind" and v not in (None, "", [])}
            if not n["exists"] and n["ann"].get("status", "existing") in ("existing", "modify"):
                n["ann"]["status"] = "proposed"  # cannot be existing if it is not on disk
        for c in n.get("children", []):
            visit(c)
    visit(tree)


def filter_scenario(tree: dict, scenario: str | None, keep_unannotated: bool) -> dict:
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


def build_lanes(tree: dict, layers: dict, scenarios: dict) -> dict:
    """layer id → scenario id → [paths]: the cross-tab the surfaces workbook also shows (layers × lanes)."""
    lanes = {L: {s: [] for s in scenarios} for L in layers}
    def visit(n: dict) -> None:
        a = n.get("ann")
        if a:
            for L in (a.get("layers_list") or [a.get("layer")]):      # a block may sit on several layers
                if L in lanes:
                    for s in a.get("scenarios", []):
                        if s in lanes[L]:
                            lanes[L][s].append(n["path"])
        for c in n.get("children", []):
            visit(c)
    visit(tree)
    return lanes


# ----------------------------------------------------------------------------- ascii (tree /f)
def header_lines(volume: str, serial: str, root_label: str) -> list[str]:
    first = f"Folder PATH listing for volume {volume}" if volume else "Folder PATH listing"
    return [first, f"Volume serial number is {serial}", root_label]


def render_ascii(tree: dict, root_label: str, volume: str, serial: str, tags: bool = False, glyphs: str = "unicode",
                 header: bool = True) -> str:
    g = GLYPHS[glyphs]
    lines = header_lines(volume, serial, root_label) if header else [root_label]

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
        col = g["vert"] if dirs else g["blank"]
        for f in files:
            lines.append(f"{prefix}{col}{f['name']}{tag(f)}")
        if dirs:
            if files:
                lines.append(f"{prefix}{g['bar']}")
            for i, sub in enumerate(dirs):
                last = i == len(dirs) - 1
                lines.append(f"{prefix}{g['last'] if last else g['branch']}{sub['name']}{tag(sub)}")
                emit(sub, prefix + (g["blank"] if last else g["vert"]))
        else:
            lines.append(prefix.rstrip())

    emit(tree, "")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- html
def render_html(manifest: dict, template_path: Path, standalone: bool = True) -> str:
    tpl = template_path.read_text(encoding="utf-8")
    for marker in ("__MANIFEST__", "__TITLE__", "<!--__BODY__-->"):
        if marker not in tpl:
            sys.exit(f"{template_path}: missing {marker} marker")
    payload = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    title = f"{manifest.get('project') or manifest['tree']['name']} Architecture Tree"
    page = tpl.replace("__MANIFEST__", payload).replace("__TITLE__", title)
    head, body = page.split("<!--__BODY__-->", 1)
    if not standalone:  # artifact page contract: no doctype/html/head/body; title + style first
        return head.rstrip() + "\n" + body.lstrip("\n")
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"{head.strip()}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n")


# ----------------------------------------------------------------------------- manifest
def build_manifest(root: Path, ann: dict, excludes: list[str], scenario: str | None, keep_unannotated: bool,
                   root_label: str, volume: str, serial: str | None) -> dict:
    tree = walk(root, excludes, root_label)
    graft_proposed(tree, ann["nodes"])
    annotate(tree, ann["nodes"])
    tree = filter_scenario(tree, scenario, keep_unannotated)
    counts = {"dirs": 0, "files": 0, "annotated": 0, "proposed": 0, "by_status": {s: 0 for s in STATUSES},
              "by_scenario": {s: 0 for s in ann["scenarios"]}}
    index = {}
    def count(n: dict) -> None:
        counts["dirs" if n["kind"] == "dir" else "files"] += 1
        a = n.get("ann")
        if a:
            counts["annotated"] += 1
            counts["by_status"][a.get("status", "existing")] += 1
            for s in a.get("scenarios", []):
                if s in counts["by_scenario"]: counts["by_scenario"][s] += 1
            index[n["path"]] = dict(a, kind=n["kind"], exists=n["exists"])
        if not n.get("exists", True): counts["proposed"] += 1
        for c in n.get("children", []): count(c)
    count(tree)
    if not serial:  # deterministic serial from the tree, in tree.com's "%08X %04X:%04X" shape → byte-identical re-runs
        h = hashlib.sha1(json.dumps(tree, sort_keys=True, ensure_ascii=False).encode()).hexdigest().upper()
        serial = f"{h[:8]} {h[8:12]}:{h[12:16]}"
    return {"schema_version": SCHEMA_VERSION, "project": ann.get("project") or root.resolve().name, "root": str(root),
            "root_label": root_label, "volume": volume, "serial": serial, "scenario_filter": scenario,
            "scenarios": ann["scenarios"], "layers": ann["layers"], "statuses": list(STATUSES), "parity": list(PARITY),
            "counts": counts, "lanes": build_lanes(tree, ann["layers"], ann["scenarios"]), "index": index, "tree": tree}


def verify_capture(ascii_text: str, capture: Path) -> int:
    """Compare body lines (after the three header lines) with a Windows capture; report the first difference."""
    ours = ascii_text.splitlines()[3:]
    theirs = capture.read_text(encoding="utf-8-sig", errors="replace").splitlines()[3:]
    for i, (a, b) in enumerate(zip(ours, theirs)):
        if a.rstrip() != b.rstrip():
            print(f"capture differs at body line {i + 1}:\n  ours   : {a!r}\n  capture: {b!r}"); return 1
    if len(ours) != len(theirs):
        print(f"capture has {len(theirs)} body lines, ours {len(ours)}"); return 1
    print("capture matches"); return 0


# ----------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--annotations", help="YAML or JSON annotations (see module doc)")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDES, help="comma-separated glob patterns (name or relative path)")
    ap.add_argument("--no-gitignore", action="store_true", help="do not add <root>/.gitignore patterns to --exclude")
    ap.add_argument("--scenario", help="keep only nodes annotated with this scenario id (plus ancestors)")
    ap.add_argument("--keep-unannotated", action="store_true", help="with --scenario: also keep nodes without annotation")
    ap.add_argument("--annotate", action="store_true", help="append {scenarios · layer · status · parity} tags in the ASCII")
    ap.add_argument("--ascii-glyphs", action="store_true", help="tree /f /a glyphs (+--- \\--- |) instead of box drawing")
    ap.add_argument("--root-label", help="root line of the listing (default: the project name from the annotations, else the root directory name; Windows prints 'C:.')")
    ap.add_argument("--volume", help="volume label in the header (default: project name; '' → 'Folder PATH listing')")
    ap.add_argument("--serial", help="serial in the header (default: derived from the tree content)")
    ap.add_argument("--out-json"); ap.add_argument("--out-ascii"); ap.add_argument("--out-html")
    ap.add_argument("--artifact", action="store_true", help="write --out-html in artifact page form (no doctype/html/body)")
    ap.add_argument("--template", default=str(Path(__file__).resolve().parent.parent / "assets" / "template.html"))
    ap.add_argument("--check", action="store_true", help="exit 1 if any --out-* file on disk differs from what would be written")
    ap.add_argument("--verify-capture", help="path of a real `tree /f > capture.txt`; compare body lines and exit 1 on difference")
    a = ap.parse_args(argv)

    root = Path(a.root)
    if not root.is_dir():
        sys.exit(f"--root {a.root} is not a directory")
    ann = load_annotations(a.annotations)
    excludes = [p.strip() for p in a.exclude.split(",") if p.strip()] + [str(x) for x in (ann.get("exclude") or [])]
    if not a.no_gitignore:
        excludes += load_gitignore(root)
    project = ann.get("project") or root.resolve().name
    volume = project if a.volume is None else a.volume
    manifest = build_manifest(root, ann, excludes, a.scenario, a.keep_unannotated,
                              a.root_label or project, volume, a.serial)
    glyphs = "ascii" if a.ascii_glyphs else "unicode"
    ascii_text = render_ascii(manifest["tree"], manifest["root_label"], manifest["volume"], manifest["serial"], a.annotate, glyphs)
    outputs: dict[str, str] = {}
    if a.out_json: outputs[a.out_json] = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    if a.out_ascii: outputs[a.out_ascii] = ascii_text
    if a.out_html: outputs[a.out_html] = render_html(manifest, Path(a.template), standalone=not a.artifact)
    if a.verify_capture:
        return verify_capture(ascii_text, Path(a.verify_capture))
    if a.check:
        stale = [p for p, text in outputs.items() if not Path(p).is_file() or Path(p).read_text(encoding="utf-8") != text]
        print("tree_f --check: " + ("up to date" if not stale else "stale: " + ", ".join(stale)))
        return 1 if stale else 0
    for p, text in outputs.items():
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(text, encoding="utf-8")
    if not outputs:
        sys.stdout.write(ascii_text)
    else:
        c = manifest["counts"]
        print(f"tree_f: {c['dirs']} dirs, {c['files']} files, {c['annotated']} annotated, {c['proposed']} proposed"
              + (f", scenario {a.scenario}" if a.scenario else "") + " → " + ", ".join(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
