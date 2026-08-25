"""Topic -> candidate papers, via the arXiv API.

Uses the public export.arxiv.org Atom feed rather than scraping — it's
structured, free, and meant to be queried programmatically, so results are
clean and there's no ToS gray area. `search()` returns candidates only; it's
the caller's job (the API layer) to show them to the user and decide what
gets ingested via `download_pdf` + `ingest_paper`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

ATOM_NS = "{http://www.w3.org/2005/Atom}"
_VERSION_SUFFIX = re.compile(r"v\d+$")


@dataclass
class ArxivResult:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None
    pdf_url: str
    entry_url: str


class ArxivClient:
    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 15.0):
        # Injected in tests via httpx.MockTransport; created lazily otherwise.
        self._client = client
        self.timeout = timeout

    async def search(self, topic: str, max_results: int = 10) -> list[ArxivResult]:
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        owns_client = self._client is None
        try:
            response = await client.get(
                self.BASE_URL,
                params={
                    "search_query": f"all:{topic}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
            response.raise_for_status()
            return parse_arxiv_feed(response.text)
        finally:
            if owns_client:
                await client.aclose()


def parse_arxiv_feed(xml_text: str) -> list[ArxivResult]:
    root = ET.fromstring(xml_text)
    results: list[ArxivResult] = []

    for entry in root.findall(f"{ATOM_NS}entry"):
        raw_id = (entry.findtext(f"{ATOM_NS}id") or "").strip()
        arxiv_id = _VERSION_SUFFIX.sub("", raw_id.rsplit("/", 1)[-1])

        title = " ".join((entry.findtext(f"{ATOM_NS}title") or "").split())
        abstract = " ".join((entry.findtext(f"{ATOM_NS}summary") or "").split())
        authors = [
            (author.findtext(f"{ATOM_NS}name") or "").strip()
            for author in entry.findall(f"{ATOM_NS}author")
        ]

        published = entry.findtext(f"{ATOM_NS}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None

        pdf_url = ""
        for link in entry.findall(f"{ATOM_NS}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

        if not arxiv_id or not title:
            continue  # malformed entry, skip rather than surface junk

        results.append(
            ArxivResult(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                pdf_url=pdf_url,
                entry_url=raw_id,
            )
        )

    return results


async def download_pdf(
    pdf_url: str,
    dest_path: str | Path,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """Download a PDF to dest_path. Raises httpx.HTTPStatusError on failure."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    active_client = client or httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    owns_client = client is None
    try:
        response = await active_client.get(pdf_url)
        response.raise_for_status()
        dest_path.write_bytes(response.content)
        return dest_path
    finally:
        if owns_client:
            await active_client.aclose()
