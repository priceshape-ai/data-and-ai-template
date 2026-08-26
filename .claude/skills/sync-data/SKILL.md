---
name: sync-data
description: Get datasets or model weights into or out of this project — pulling data for a fresh clone, adding a new dataset, publishing data to S3, or fixing DVC when `make dvc-pull` returns nothing, reports missing files, or the data directories are empty. Use whenever the user mentions DVC, .data, .models, a dataset, model weights, S3 buckets, or asks why data is missing, why nothing pulled, or how to version a new dataset.
---

# Getting data in and out

One command covers every situation: **`make dvc-pull`**. It inspects this project's
prefix in each bucket and does whatever fits.

| What it finds | What it does |
| --- | --- |
| `.data.dvc` committed | pulls from the DVC cache |
| plain files staged in S3 | downloads them and starts tracking them |
| S3 empty, data sitting in `.data/` | starts tracking that |
| nothing anywhere | creates `.data/` and `.models/` to fill |

So the first-run loop is: `make dvc-pull` creates the directories, you add data,
`make dvc-pull` again tracks it, `make dvc-push` publishes it.

## Adding a new dataset

```bash
make dvc-pull                             # be current first
cp ~/new-data.jsonl .data/raw/
# point the loader at it in src/{{PACKAGE_NAME}}/config/hyperparameters.py:
#   source: str = "raw/new-data.jsonl"
make dvc-add                              # re-hash
make dvc-push                             # upload — BEFORE committing
git add .data.dvc src/*/config/hyperparameters.py && git commit && git push
uv run pipeline
```

Changing `source` changes the loader's cache key, so every downstream node
recomputes on its own.

## The two failures worth recognising

**`dvc pull` cannot fetch plain uploads.** A DVC remote is a content-addressed
cache, not a mirror: objects sit at `files/md5/<hash>` and are found by resolving
hashes out of `.dvc` files. Files someone uploaded by hand are invisible to it.
`make dvc-pull` bridges that by downloading them and then tracking them.

**"missing files" means the pointer was committed without a push.** `.data.dvc`
names content that reached no bucket. The only real fix is `make dvc-push` from a
machine that still has the files; if none does, the data is gone and the pointer
must be deleted. This is why push comes before commit, always.

## Never

Commit anything inside `.data/` or `.models/`, including a `.gitkeep` — DVC then
refuses to manage the directory at all. Hand-edit a `.dvc` file — use `make
dvc-add`, which also keeps the per-output remote pin that stops datasets landing in
the models bucket.
