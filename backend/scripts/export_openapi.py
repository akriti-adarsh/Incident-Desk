"""Write the app's OpenAPI schema to backend/openapi.json.

The committed file is the contract the frontend types are checked against and
that the CI drift check compares to. Regenerate with this script after any API
change: ``uv run python -m scripts.export_openapi``.
"""

import json
from pathlib import Path

from incident_desk.main import create_app

TARGET = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    schema = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    TARGET.write_text(render(), encoding="utf-8")
    print(f"Wrote {TARGET}")


if __name__ == "__main__":
    main()
