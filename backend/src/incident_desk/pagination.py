"""Cursor (keyset) pagination.

Why cursors and not OFFSET: an offset scan re-reads and discards every
skipped row on each page (O(n) per page, O(n^2) to walk a table), and
concurrent inserts or deletes shift the window between requests so rows get
skipped or duplicated. A cursor pins the position to the last row seen.

Every ORDER BY includes the unique row id as a tiebreaker; without it,
pagination silently skips and duplicates rows whenever sort values collide,
which is exactly what happens with timestamps written in the same
transaction. The cursor itself is an opaque urlsafe-base64 JSON pair
``[sort_value, id]``; clients must treat it as a token, not parse it.
"""

import base64
import binascii
import json
from uuid import UUID

from incident_desk.errors import AppError


class InvalidCursorError(AppError):
    status_code = 400
    code = "invalid_cursor"


def encode_cursor(sort_value: str, row_id: UUID | int) -> str:
    payload = json.dumps([sort_value, str(row_id)]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        sort_value, row_id = decoded
        return str(sort_value), str(row_id)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise InvalidCursorError("The cursor is not valid; request the first page again") from exc


def decode_uuid_cursor(cursor: str) -> tuple[str, UUID]:
    sort_value, row_id = decode_cursor(cursor)
    try:
        return sort_value, UUID(row_id)
    except ValueError as exc:
        raise InvalidCursorError("The cursor is not valid; request the first page again") from exc
