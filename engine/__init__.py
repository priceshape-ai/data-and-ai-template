"""The machinery: the DAG engine, the runner, tracking, and the backends.

Development only — never present in the production image. `docker/Dockerfile`
copies only `src/`, and `.dockerignore` excludes this directory outright.

Nothing in here is meant to be edited while building a project. The files you
work in are `pipelines/build.py` (the graph), `src/<package>/components/` (the
steps) and `src/<package>/config/hyperparameters.py` (their settings). The one
exception worth knowing about is `engine/kubeflow/`, which decides how a run is
assembled into cluster tasks — see TEMPLATE_GUIDE.md.
"""
