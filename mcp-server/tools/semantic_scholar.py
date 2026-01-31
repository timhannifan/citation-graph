"""Semantic Scholar API client: citation/reference lookup with rate limiting."""

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429

# Rate limit: min seconds between Semantic Scholar calls (free tier ~100/5min → ~3s)
SEMANTIC_SCHOLAR_DELAY = float(os.getenv("SEMANTIC_SCHOLAR_DELAY_SECONDS", "3.0"))
_semantic_scholar_last_call: list[float] = [0.0]
_semantic_scholar_lock = asyncio.Lock()


async def _wait_semantic_scholar_rate_limit() -> None:
    """Enforce minimum delay between Semantic Scholar API calls."""
    async with _semantic_scholar_lock:
        now = time.monotonic()
        elapsed = now - _semantic_scholar_last_call[0]
        if elapsed < SEMANTIC_SCHOLAR_DELAY:
            wait = SEMANTIC_SCHOLAR_DELAY - elapsed
            logger.debug("Semantic Scholar rate limit: waiting %.1fs", wait)
            await asyncio.sleep(wait)
        _semantic_scholar_last_call[0] = time.monotonic()


async def fetch_citations_semantic_scholar(arxiv_id: str) -> dict[str, Any]:
    """Fetch citation data from Semantic Scholar (rate-limited)."""
    await _wait_semantic_scholar_rate_limit()

    paper_id = f"ARXIV:{arxiv_id}"
    url = f"{SEMANTIC_SCHOLAR_API}/paper/{paper_id}"
    params = {
        "fields": "references.externalIds,references.title,citations.externalIds,citations.title"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=30)
        if resp.status_code == HTTP_NOT_FOUND:
            return {"references": [], "citations": []}
        if resp.status_code == HTTP_TOO_MANY_REQUESTS:
            retry_after = resp.headers.get("Retry-After", "60")
            try:
                wait_secs = int(retry_after)
            except ValueError:
                wait_secs = 60
            logger.warning("Semantic Scholar rate limited (429); waiting %ss", wait_secs)
            await asyncio.sleep(wait_secs)
            return await fetch_citations_semantic_scholar(arxiv_id)  # Single retry
        resp.raise_for_status()

    data = resp.json()

    references = []
    for ref in data.get("references", []) or []:
        ext_ids = ref.get("externalIds", {}) or {}
        if ext_ids.get("ArXiv"):
            references.append({"arxiv_id": ext_ids["ArXiv"], "title": ref.get("title")})

    citations = []
    for cit in data.get("citations", []) or []:
        ext_ids = cit.get("externalIds", {}) or {}
        if ext_ids.get("ArXiv"):
            citations.append({"arxiv_id": ext_ids["ArXiv"], "title": cit.get("title")})

    return {"references": references[:20], "citations": citations[:20]}
