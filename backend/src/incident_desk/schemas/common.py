"""Response envelopes shared by every endpoint.

Single objects arrive as ``{"data": ...}``; lists will additionally carry a
``next_cursor``. Errors always use the envelope defined in ``errors.py``.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Data(BaseModel, Generic[T]):
    data: T
