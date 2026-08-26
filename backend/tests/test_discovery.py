"""Tests for the arXiv discovery client.

Feed parsing is tested against a real (trimmed) arXiv Atom response so it
doesn't depend on the network. search() and download_pdf() are tested via
httpx.MockTransport for the same reason.
"""
from pathlib import Path

import httpx
import pytest

from services.discovery import ArxivClient, download_pdf, parse_arxiv_feed

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models are based on complex
recurrent or convolutional neural networks.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link href="http://arxiv.org/abs/1706.03762v5" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v5" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2005.14165v4</id>
    <published>2020-05-28T17:29:03Z</published>
    <title>Language Models are Few-Shot Learners</title>
    <summary>Recent work has demonstrated substantial gains on many NLP tasks.</summary>
    <author><name>Tom B. Brown</name></author>
    <link href="http://arxiv.org/abs/2005.14165v4" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2005.14165v4" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def test_parse_arxiv_feed_extracts_all_entries():
    results = parse_arxiv_feed(SAMPLE_FEED)
    assert len(results) == 2


def test_parse_arxiv_feed_strips_version_suffix_from_id():
    results = parse_arxiv_feed(SAMPLE_FEED)
    assert results[0].arxiv_id == "1706.03762"


def test_parse_arxiv_feed_extracts_title_authors_year():
    results = parse_arxiv_feed(SAMPLE_FEED)
    paper = results[0]
    assert paper.title == "Attention Is All You Need"
    assert paper.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper.year == 2017


def test_parse_arxiv_feed_extracts_pdf_url():
    results = parse_arxiv_feed(SAMPLE_FEED)
    assert results[0].pdf_url == "http://arxiv.org/pdf/1706.03762v5"


def test_parse_arxiv_feed_handles_empty_feed():
    assert parse_arxiv_feed(EMPTY_FEED) == []


@pytest.mark.asyncio
async def test_search_hits_correct_endpoint_and_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/query"
        assert request.url.params.get("search_query") == "all:llm architecture"
        return httpx.Response(200, text=SAMPLE_FEED)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    client = ArxivClient(client=async_client)

    results = await client.search("llm architecture", max_results=5)

    assert len(results) == 2
    await async_client.aclose()


@pytest.mark.asyncio
async def test_download_pdf_writes_file(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 fake pdf bytes")

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    dest = tmp_path / "paper.pdf"

    result_path = await download_pdf("http://arxiv.org/pdf/fake", dest, client=async_client)

    assert result_path == dest
    assert dest.read_bytes() == b"%PDF-1.4 fake pdf bytes"
    await async_client.aclose()


@pytest.mark.asyncio
async def test_download_pdf_raises_on_http_error(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    dest = tmp_path / "paper.pdf"

    with pytest.raises(httpx.HTTPStatusError):
        await download_pdf("http://arxiv.org/pdf/missing", dest, client=async_client)
    await async_client.aclose()
