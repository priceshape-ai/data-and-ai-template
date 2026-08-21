"""MLflow experiment tracking. Development and CI only.

Lives outside src/ because production must never import it — the serving image
has no mlflow installed, and the import-linter contract in pyproject.toml fails
the build if `data_and_ai_template` ever reaches in here.
"""
