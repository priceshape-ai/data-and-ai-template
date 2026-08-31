---
name: diagnose-tracking
description: Work out why a pipeline run did not appear in MLflow. Use whenever the user says nothing shows up in MLflow, runs are not being logged, they see "MLflow logging failed", an HTML or JSON parse error, a 401 or 403, "Cannot set a deleted experiment", or asks how to point this project at the tracking server, what MLFLOW_TRACKING_URI should be, or why experiment tracking is silent.
---

# Why the run did not reach MLflow

The pipeline never fails because tracking failed — the run completes and its results
land in `runs/` regardless. So a missing run is always a warning in the log, and the
warning names which of these it was.

## The browser URL is not the API URL

`https://mlflow.data.priceshape.io` sits behind the platform's SSO proxy. An API
call gets a 302 to a login page, MLflow parses the HTML, and you see:

```
response body was not in a valid JSON format. Response body: '<!DOCTYPE html>'
```

**No username or password gets past this** — the proxy wants an OAuth session, not
HTTP basic auth, and the server runs no basic-auth plugin. Reach it directly:

```bash
# From inside the cluster — no auth needed
MLFLOW_TRACKING_URI=http://mlflow.mlflow.svc.cluster.local

# From a laptop. The server enforces a Host allowlist, so the hostname must
# survive the tunnel — map it to localhost for the session.
sudo sh -c 'echo "127.0.0.1 mlflow.data.priceshape.io" >> /etc/hosts'
kubectl port-forward -n mlflow svc/mlflow 5000:80
MLFLOW_TRACKING_URI=http://mlflow.data.priceshape.io:5000
```

A plain port-forward to `localhost:5000` gets `403 Invalid Host header`.

## "Cannot set a deleted experiment"

Deleting an experiment in the UI only soft-deletes it: the name stays reserved and
every later run fails. Restore it:

```bash
uv run python -c "from mlflow import MlflowClient; c=MlflowClient(); \
c.restore_experiment(c.get_experiment_by_name('<name>').experiment_id)"
```

Or set `MLFLOW_EXPERIMENT` in `.env` to a different name.

## Nothing logged at all, no warning

`MLFLOW_TRACKING_URI` is empty, which disables tracking deliberately. The runner
says so at INFO: `MLFLOW_TRACKING_URI is unset — skipping run logging.`

## The run logged but looks identical to the last one

Check whether anything actually recomputed. Every node reporting
`[cache hit: disk]` means the run reused cached results, so identical metrics are
correct. `uv run pipeline --no-cache` forces a real one.

## What gets logged

Hyperparameters as params, `NodeResult.metrics` as `<node>.<metric>`, git
provenance as tags, and `runs/<timestamp>/` as artefacts. Infrastructure sections —
paths, mlflow, serving — are deliberately skipped, so the same experiment
run from two machines does not look like two configurations.
