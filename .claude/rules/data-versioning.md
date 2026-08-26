---
paths:
  - "*.dvc"
  - ".dvc/**"
  - "scripts/dvc_sync.py"
  - ".gitignore"
---

# Data and model versioning

## A DVC remote is a cache, not a mirror

Objects live at `files/md5/<first-2>/<rest-of-hash>` and DVC finds them by
resolving hashes recorded in `.dvc` files, which reach you through git. Plain files
someone uploaded to the bucket by hand are invisible to `dvc pull` — nothing names
them. `make dvc-pull` handles that case by downloading them and then tracking them.

## Order matters: push, then commit

`.data.dvc` records hashes. The content reaches S3 only via `make dvc-push`. Commit
the pointer without pushing and every later clone gets a `dvc pull` that fails on
content that exists nowhere — and if no machine still holds the files, the data is
gone and the pointer has to be deleted.

```bash
make dvc-add     # re-hash
make dvc-push    # upload — this one first
git add .data.dvc .models.dvc .gitignore && git commit
```

## Never git-track anything inside `.data/` or `.models/`

Not even a `.gitkeep`. DVC refuses to manage a directory git tracks anything
inside: `dvc add .data` fails with `output '.data' is already tracked by SCM`.
Both directories are git-ignored wholesale and
`tests/test_smoke.py::test_data_dirs_are_not_git_tracked` fails if that changes.

## Each output pins its own remote

`.dvc/config` sets no default remote on purpose, so a bare `dvc push` cannot send
datasets to the models bucket. The pin lives in the `.dvc` file as `remote:`.
`dvc add` preserves it but never writes it, which is why `make dvc-add` goes
through `scripts/dvc_sync.py --add` rather than calling `dvc add` directly.

Do not hand-edit a `.dvc` file. Use the make targets.
