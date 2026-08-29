"""LLM prompts as Python modules, one constant per prompt.

Prompts belong in version control next to the code that sends them, not in a
YAML blob or a database row: a prompt change is a behaviour change, and it should
show up in a diff and in the git SHA that the MLflow run is tagged with.

One module per prompt, named for its role:

    # scorer_system.py
    SCORER_SYSTEM = \"\"\"You are ...\"\"\"

then re-export it here so callers write
`from core.config.prompts import SCORER_SYSTEM`.
"""

__all__: list[str] = []
