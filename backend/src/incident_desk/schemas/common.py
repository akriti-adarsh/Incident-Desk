"""Response envelopes shared by every endpoint.

Single objects arrive as ``{"data": ...}``; lists will additionally carry a
``next_cursor``. Errors always use the envelope defined in ``errors.py``.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Data(BaseModel, Generic[T]):
    data: T


class Page(BaseModel, Generic[T]):
    data: list[T]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque token; pass back as ?cursor= for the next page. Null on the last page.",
    )
