#!/usr/bin/env python3
"""First-time DVC setup: start tracking .data/ and .models/. Run once per project.

    make dvc-init

Creates the two directories, runs `dvc add` on each, and pins each output to its
own remote. After this, `.data.dvc` and `.models.dvc` exist and are the files to
commit; from then on `make dvc-add` is enough.

Why a script rather than two `dvc add` calls in the Makefile: `dvc add` has no way
to pin an output's remote (`--remote` only applies together with `--to-remote`,
which uploads instead of tracking locally). The pin is what stops a bare
`dvc push` from sending datasets to the models bucket, so it has to be written in
afterwards. `dvc add` preserves it on every subsequent run, so this only has to
happen once.

Why the template does not ship `.data.dvc` and `.models.dvc` pre-made: a `.dvc`
file with no hash reads as a pending change forever. `dvc status` reports
`deleted: .data` (or `modified:`), and the VS Code DVC extension shows the project
as dirty from the moment it is created. Generating them here means a new
repository starts clean.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# (directory, remote name in .dvc/config)
TARGETS: tuple[tuple[str, str], ...] = (
    (".data", "datasets"),
    (".models", "models"),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def pin_remote(dvc_file: Path, remote: str) -> bool:
    """Add `remote: <name>` beside the output's `path:`. Returns True if it changed.

    Both layouts have to work. A hand-written out leads with the path:

        outs:
        - path: .data

    while `dvc add` writes the hash first and the path last:

        outs:
        - md5: 995c...
          size: 41
          path: .data

    So the anchor is the `path:` key wherever it appears, and the insertion is
    indented to match its siblings — which is one level in from the `- ` when the
    path leads the block, and the same level otherwise.

    Raises:
        ValueError: If no `path:` key was found. Silently failing here would leave
            an unpinned output, and an unpinned output is exactly how datasets end
            up in the models bucket.
    """
    lines = dvc_file.read_text().splitlines()
    if any(line.strip().startswith("remote:") for line in lines):
        return False

    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        stripped = line.lstrip()
        leading = len(line) - len(stripped)
        if stripped.startswith("- "):
            key, key_indent = stripped[2:], leading + 2
        else:
            key, key_indent = stripped, leading
        if key.startswith("path:") and not inserted:
            out.append(" " * key_indent + f"remote: {remote}")
            inserted = True

    if not inserted:
        raise ValueError(
            f"{dvc_file.name}: no `path:` key found, so the remote could not be "
            f"pinned. Add `remote: {remote}` under the output by hand."
        )

    dvc_file.write_text("\n".join(out) + "\n")
    return True


def main() -> int:
    root = repo_root()

    if not (root / ".dvc").is_dir():
        print("No .dvc/ directory — run `dvc init` first.", file=sys.stderr)
        return 1

    tracked: list[str] = []

    for directory, remote in TARGETS:
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)

        # DVC will not track an empty directory, and it will not track one that git
        # already tracks something inside. Both cases are silent-ish failures, so
        # say what happened rather than leaving a half-configured project.
        if not any(path.iterdir()):
            print(f"{directory}/ is empty — skipping. Put data in it, then re-run.")
            continue

        result = subprocess.run(["dvc", "add", directory], cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"dvc add {directory} failed:\n{result.stderr.strip()}", file=sys.stderr)
            return result.returncode

        dvc_file = root / f"{directory}.dvc"
        pinned = pin_remote(dvc_file, remote)
        tracked.append(f"{directory}.dvc")
        print(
            f"Tracking {directory}/ → remote '{remote}'"
            f"{' (remote pinned)' if pinned else ' (remote already pinned)'}"
        )

    if not tracked:
        print("\nNothing was tracked, so there is nothing to commit yet.")
        return 0

    print(f"\nNext:\n  git add {' '.join(tracked)} .gitignore\n  make dvc-push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
