"""Wrapper around the user's own OpenAI-compatible /v1/chat/completions server.

Jim never bundles a model — this just calls whatever endpoint the user pasted
into Settings (e.g. a local llama.cpp / Ollama / LM Studio server).
"""
from __future__ import annotations

import httpx


class LLMClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Injected in tests via httpx.MockTransport; created lazily otherwise.
        self._client = client

    async def generate(
        self,
        messages: list[dict],
        model: str = "local-model",
        temperature: float = 0.2,
    ) -> str:
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        finally:
            if owns_client:
                await client.aclose()


def build_llm_client(base_url: str) -> LLMClient:
    return LLMClient(base_url=base_url)
