"""Pipeline orchestration. Development only — never present in the production image.

This root exists outside src/ so the separation is physical: docker/Dockerfile
copies only src/, and .dockerignore excludes this directory outright. It is still
a first-class importable package locally, via `dev-mode-dirs` in pyproject.toml.
"""
