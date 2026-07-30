"""Helpers for asserting delivered email through the Mailpit capture API."""

import os
import re

import httpx

BASE_URL = os.environ.get("MAILPIT_API_URL", "http://localhost:58026")


async def messages_to(address: str) -> list[dict[str, object]]:
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        search = await client.get("/api/v1/search", params={"query": f'to:"{address}"'})
        search.raise_for_status()
        result: list[dict[str, object]] = search.json()["messages"]
        return result


async def latest_message_text_to(address: str) -> str:
    """Return the text body of the newest captured message to ``address``."""
    messages = await messages_to(address)
    assert messages, f"no captured email for {address}"
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        detail = await client.get(f"/api/v1/message/{messages[0]['ID']}")
        detail.raise_for_status()
        return str(detail.json()["Text"])


def extract_token(body: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, f"no token link in email body: {body!r}"
    return match.group(1)
