# Windows `tree /f` — the format reproduced by `scripts/tree_f.py`

Observed on Windows 10/11 (`tree /f` in cmd.exe, Unicode glyphs; `/a` would swap them for `|`, `+`, `\`, `-`).

```
Folder PATH listing for volume OS
Volume serial number is 1234-ABCD
C:.
│   README.md
│   package.json
│
├───src
│   │   index.js
│   │
│   └───lib
│           util.js
│
└───test
        index.test.js
```

Rules, as the renderer applies them (`emit(dir, prefix)` with the child prefix of the current directory):

1. Two header lines, then the root line (`C:.` for the current directory, or the path given). The
   renderer prints the root directory name (or `--root-label`) and a serial derived from the content.
2. A directory's **files come first**, each on its own line: `prefix + column + name`, where the column
   is `│   ` when the directory also has sub-directories and four spaces when it has none.
3. When a directory has both files and sub-directories, one spacer line `prefix + │` follows the files.
4. Sub-directories follow, each introduced by `prefix + ├───name`, the last one by `prefix + └───name`.
   The sub-directory's own content is emitted with child prefix `prefix + │   ` (not last) or
   `prefix + "    "` (last).
5. After a directory that has **no sub-directories** (files only, or empty), one spacer line equal to its
   child prefix, right-stripped (`│   │` → `│   │`, `│       ` → `│`, `        ` → an empty line).
6. Directories sort before files; both case-insensitively by name (Windows sorts by name only; the
   renderer separates kinds for readability — set `--no-dirs-first` is not offered on purpose, the
   workbook and page assume this order).

With `--annotate`, tags are appended after the name: `name  {A,B · L5 · proposed · Parallel}`. Windows
has no such thing; the tagged form is for review, the plain form for fidelity.
