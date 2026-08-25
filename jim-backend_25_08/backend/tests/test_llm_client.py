"""Tests for LLMClient against a mocked OpenAI-compatible endpoint."""
import httpx
import pytest

from services.llm_client import LLMClient


@pytest.mark.asyncio
async def test_generate_parses_openai_compatible_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = request.read()
        assert b"hi" in body
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello there"}}]}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://fake")
    llm = LLMClient(base_url="http://fake", client=client)

    result = await llm.generate([{"role": "user", "content": "hi"}])

    assert result == "hello there"
    await client.aclose()


@pytest.mark.asyncio
async def test_generate_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://fake")
    llm = LLMClient(base_url="http://fake", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        await llm.generate([{"role": "user", "content": "hi"}])
    await client.aclose()
