#!/usr/bin/env python3
"""Get `.data/` and `.models/` into the right state, whatever that state is.

    make dvc-pull

One command, because which of the three situations you are in is something the
script can work out faster than you can. For each directory it looks at the
matching S3 prefix under this project's name and then:

* `.data.dvc` is committed  ->  `dvc pull`, the ordinary path.
* plain files are staged there  ->  download them and start tracking them, so the
  next `make dvc-push` publishes them and everyone after you just pulls.
* the prefix is empty  ->  create the directory and say so. Put data in it and run
  `make dvc-push`.

The middle case is the one that needs explaining, because `dvc pull` cannot do it. A
DVC remote is a content-addressed cache, not a mirror: objects sit at
`files/md5/<first-2>/<rest-of-hash>` and DVC locates them by resolving hashes
recorded in `.dvc` files, which reach you through git. Files someone uploaded by hand
are therefore invisible to it — nothing names them. Compare:

    plain uploads    <project>/vendor_66bd29b5.db.tar.gz        dvc pull cannot see this
    a DVC remote     <project>/files/md5/0c/b3547c9cb4c508...   what dvc pull reads

Downloading uses `dvc get-url`, a plain fetch that creates no `.dvc` file and needs no
extra dependency, since DVC already speaks S3. Credentials resolve exactly as they do
for every other dvc command.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# (local directory, remote name in .dvc/config)
TARGETS: tuple[tuple[str, str], ...] = (
    (".data", "datasets"),
    (".models", "models"),
)

# DVC keeps everything it stores under this single top-level key. It is filtered out
# of anything we download rather than merely detected: after the first `dvc push` the
# cache sits at the same prefix as the plain uploads, and pouring hash-named blobs
# into `.data/` would be worse than useless.
CACHE_DIR = "files"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def remote_urls(root: Path) -> dict[str, str]:
    """Remote name -> URL, from `dvc remote list`.

    Asked of DVC rather than parsed out of `.dvc/config`, so there is one source of
    truth and no second INI parser to keep in step with DVC's own.
    """
    result = run("dvc", "remote", "list", cwd=root)
    if result.returncode != 0:
        sys.exit(f"`dvc remote list` failed:\n{result.stderr.strip()}")

    urls: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls[parts[0]] = parts[1]
    return urls


def classify(url: str, root: Path) -> tuple[str, list[str]]:
    """Return ("empty" | "cache-only" | "plain" | "error", entries worth fetching).

    The returned list never contains `files`, so callers can fetch it blindly.
    """
    result = run("dvc", "list-url", url, cwd=root)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Match against the whole of stderr, and display the ERROR: line rather
        # than the last one — dvc signs off with "Having any troubles? Hit us up
        # at ...", so the last line is a support footer, never the diagnosis.
        lowered = stderr.lower()
        detail = next(
            (ln.strip() for ln in stderr.splitlines() if ln.strip().startswith("ERROR:")),
            stderr.splitlines()[-1] if stderr else "unknown error",
        )

        # Order matters. A missing BUCKET also says "does not exist", so it has to
        # be caught before the empty-prefix check — otherwise a typo'd or
        # not-yet-created bucket looks like a new project, and the failure surfaces
        # much later at `dvc push` instead of here.
        if "nosuchbucket" in lowered or "specified bucket does not exist" in lowered:
            return "no-bucket", [detail]
        if "unable to locate credentials" in lowered:
            return "no-credentials", [detail]
        if "forbidden" in lowered or "accessdenied" in lowered or "(403)" in detail:
            return "forbidden", [detail]

        # A prefix nobody has written to yet does not exist as far as S3 is
        # concerned. That is the ordinary state of a new project, not a fault.
        if "does not exist" in detail or "nosuchkey" in lowered:
            return "empty", []
        return "error", [detail]

    entries = [e for e in result.stdout.split() if e not in (".", "./")]
    if not entries:
        return "empty", []

    plain = [e for e in entries if e.rstrip("/") != CACHE_DIR]
    if not plain:
        return "cache-only", []
    return "plain", plain


def fetch(url: str, target: Path, entries: list[str], root: Path) -> int:
    """Download `entries` from `url` into `target`. Returns files written.

    Entry by entry into a staging directory, then moved into place. `dvc get-url URL
    DIR` maps the prefix contents straight into a DIR that does not exist, but nests
    them under a prefix-named subdirectory when it does; staging makes the result the
    same either way, and makes an interrupted run resumable.
    """
    target.mkdir(parents=True, exist_ok=True)
    staging = root / f"{target.name}.sync-tmp"
    written = 0

    for entry in entries:
        name = entry.rstrip("/")
        destination = target / name
        if destination.exists():
            print(f"    {name} — already here, left alone")
            continue

        if staging.exists():
            shutil.rmtree(staging)
        result = run("dvc", "get-url", f"{url.rstrip('/')}/{name}", str(staging), cwd=root)
        if result.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            sys.exit(f"`dvc get-url {url}/{name}` failed:\n{result.stderr.strip()}")

        shutil.move(str(staging), str(destination))
        if destination.is_dir():
            written += sum(1 for f in destination.rglob("*") if f.is_file())
        else:
            written += 1
        print(f"    {name} — downloaded")

    shutil.rmtree(staging, ignore_errors=True)
    return written


def pin_remote(dvc_file: Path, remote: str) -> bool:
    """Add `remote: <name>` beside the output's `path:`. True if the file changed.

    `dvc add` cannot do this (`--remote` only applies with `--to-remote`, which
    uploads instead of tracking locally), and the pin is what stops a bare `dvc push`
    sending datasets to the models bucket. It survives every later `dvc add`.

    Both key orders have to work: a hand-written out leads with `- path:`, while
    `dvc add` writes the hash first and `path:` last.
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


def track(directory: str, remote: str, root: Path) -> bool:
    """`dvc add` the directory and pin its remote. False if DVC refused."""
    result = run("dvc", "add", directory, cwd=root)
    if result.returncode != 0:
        print(f"    could not track it: {result.stderr.strip().splitlines()[-1]}")
        return False
    pin_remote(root / f"{directory}.dvc", remote)
    print(f"    tracking it — {directory}.dvc written, remote pinned to '{remote}'")
    return True


def sync_one(directory: str, remote: str, url: str, root: Path) -> str:
    """Bring one directory into the right state. Returns what happened."""
    target = root / directory
    pointer = root / f"{directory}.dvc"

    if pointer.exists():
        result = run("dvc", "pull", str(pointer.name), cwd=root)
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
            # By far the most common cause, and the bare error URL says none of it:
            # someone ran `dvc add` and committed the pointer, but never pushed the
            # cache, so the hashes in it name content that exists nowhere.
            if "missing-files" in detail or "missing" in detail.lower():
                print(f"    {pointer.name} is committed, but its contents were never")
                print(f"    pushed — nothing at {url} matches the hashes it records.")
                print("    Whoever added it needs to run `make dvc-push` from the")
                print("    machine that still has the files. If nobody has them, the")
                print(f"    data is gone: `git rm {pointer.name}`, commit, and start again")
                print("    with `make dvc-pull`.")
            else:
                print(f"    dvc pull failed: {detail}")
            return "failed"
        files = sum(1 for f in target.rglob("*") if f.is_file()) if target.exists() else 0
        print(f"    pulled from the DVC cache — {files} file(s) on disk")
        return "pulled"

    kind, entries = classify(url, root)

    if kind == "plain":
        print(f"    {len(entries)} item(s) staged there, not yet under DVC:")
        count = fetch(url, target, entries, root)
        if count and track(directory, remote, root):
            return "adopted"
        return "fetched" if count else "empty"

    # Nothing to bring down. Either the local directory already holds data the user
    # put there — in which case start tracking it, so `make dvc-push` has something
    # to publish — or it is genuinely empty and needs creating.
    target.mkdir(parents=True, exist_ok=True)
    local_files = sum(1 for f in target.rglob("*") if f.is_file())

    if kind in ("no-bucket", "no-credentials", "forbidden", "error"):
        if kind == "no-bucket":
            bucket = url.split("/")[2] if url.startswith("s3://") else url
            print(f"    the bucket {bucket} does not exist.")
            print("    A per-project prefix needs no creating — S3 makes those on")
            print("    first write — but the bucket does. Ask whoever administers")
            print("    AWS to create it, or fix the name in .dvc/config.")
        elif kind == "no-credentials":
            print("    no AWS credentials found.")
            print("    Set AWS_PROFILE (PriceShape uses the 'data' profile) or put")
            print("    AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env.")
        elif kind == "forbidden":
            print("    credentials found, but they cannot read this bucket (403).")
            print("    Check you are on the right AWS profile and have access.")
        else:
            print(f"    cannot read the remote: {entries[0]}")

        if not local_files:
            print(f"    created {directory}/ so you can work locally meanwhile.")
            return "unreachable"
        print("    Not tracking anything until the remote is reachable — a pointer")
        print("    you cannot push is worse than none.")
        return "unreachable"

    elif kind == "cache-only":
        print("    holds a DVC cache but no plain files, and this project has no")
        print(f"    {directory}.dvc to resolve it against. The cache is hash-named")
        print("    blobs, so it is meaningless without that file — `git pull` to get")
        print("    it. If nobody committed it, whoever ran `dvc push` still needs to.")
        if not local_files:
            return "cache-only"

    if local_files:
        print(f"    {local_files} local file(s) here and nothing tracking them yet.")
        if track(directory, remote, root):
            return "tracked-local"
        return "untracked"

    print(f"    nothing there yet — created {directory}/.")
    print("    Put your data in it, then run `make dvc-pull` again to track it.")
    return "empty"


def retrack(root: Path) -> int:
    """Re-hash both trees and keep their remotes pinned. Backs `make dvc-add`.

    A bare `dvc add` would do the re-hash, but it does not write the `remote:`
    pin — and an output with no pin is exactly how a dataset ends up in the models
    bucket, because `dvc push` then falls back to whatever default it can find.
    `dvc add` preserves a pin that is already there, so this only has to notice the
    ones that are missing.
    """
    for directory, remote in TARGETS:
        target = root / directory
        if not target.exists() or not any(target.iterdir()):
            print(f"{directory}/ — empty or absent, nothing to re-hash.")
            continue
        print(f"{directory}/")
        track(directory, remote, root)
    return 0


def main() -> int:
    root = repo_root()

    if "--add" in sys.argv[1:]:
        if not (root / ".dvc").is_dir():
            print("No .dvc/ directory — run `dvc init` first.", file=sys.stderr)
            return 1
        return retrack(root)

    if not (root / ".dvc").is_dir():
        print("No .dvc/ directory — run `dvc init` first.", file=sys.stderr)
        return 1

    urls = remote_urls(root)
    outcomes: dict[str, str] = {}

    for directory, remote in TARGETS:
        url = urls.get(remote)
        if not url:
            print(f"{directory}/  —  no remote named '{remote}' in .dvc/config, skipping.")
            continue
        print(f"{directory}/  ←  {url}")
        outcomes[directory] = sync_one(directory, remote, url, root)

    fresh = [d for d, o in outcomes.items() if o in ("adopted", "tracked-local")]
    if fresh:
        pointers = " ".join(f"{d}.dvc" for d in fresh)
        print(
            f"\n{', '.join(fresh)} is now tracked by DVC."
            "\nPublish it so the next person just pulls:"
            f"\n  make dvc-push"
            f"\n  git add {pointers} .gitignore && git commit"
        )
    elif outcomes and all(o == "empty" for o in outcomes.values()):
        print(
            "\nNothing in S3 for this project yet, and nothing local either."
            "\nPut data in .data/ and models in .models/, then run `make dvc-pull` again."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
