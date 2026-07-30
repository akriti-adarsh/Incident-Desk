"""OpenAPI drift guard: the committed openapi.json must match the live app.

A field rename or a new route that is not reflected in openapi.json fails
here, so the committed contract (which the frontend types track) never rots.
Regenerate with ``uv run python -m scripts.export_openapi``.
"""

from pathlib import Path

from scripts.export_openapi import render

COMMITTED = Path(__file__).resolve().parent.parent / "openapi.json"


def test_committed_openapi_matches_the_app() -> None:
    current = render()
    assert COMMITTED.exists(), "openapi.json is missing; run scripts.export_openapi"
    committed = COMMITTED.read_text(encoding="utf-8")
    assert committed == current, (
        "openapi.json is out of date with the app. "
        "Run `uv run python -m scripts.export_openapi` and commit the result."
    )
