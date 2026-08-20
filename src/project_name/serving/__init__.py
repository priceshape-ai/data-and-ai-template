"""The production API. The only subtree the serving image executes.

Nothing under here may import mlflow, dvc, streamlit or kfp, nor the `pipelines`,
`tracking` or `viz` roots — none of those are installed in the image. The
import-linter contracts in pyproject.toml and the prod-import job in CI both fail
if that ever stops being true.
"""
