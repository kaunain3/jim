"""Text embedding service.

Wraps a local sentence-transformers model so the rest of the app never talks
to the ML library directly. Swappable via the `model_name` / `model` args —
tests inject a fake model so they don't need network access or GPU/CPU time.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

# Small, fast, CPU-friendly, 384-dim. Good default for a local-first app —
# swap to a bigger model later (e.g. bge-small-en-v1.5) if quality matters
# more than ingest speed.
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingService:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, model: Any = None):
        self.model_name = model_name
        # `model` is injected in tests to avoid downloading real weights.
        self._model = model

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of strings. Returns one unit-normalized vector per text."""
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in vector] for vector in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @staticmethod
    def serialize(vector: Sequence[float]) -> str:
        return json.dumps(list(vector))

    @staticmethod
    def deserialize(payload: str) -> list[float]:
        return json.loads(payload)


# Shared default instance — lazy-loads the real model on first use.
embedding_service = EmbeddingService()
