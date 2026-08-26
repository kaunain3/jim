"""Tests for the embedding service. Uses a fake model so tests don't need to
download real weights or hit the network."""
import json

import pytest

from services.embedding import EmbeddingService


class _FakeModel:
    """Deterministic stand-in for SentenceTransformer."""

    def encode(self, texts, normalize_embeddings=True):
        vectors = []
        for text in texts:
            base = [float(len(text) % 5 + 1), float(text.count("a") + 1), 1.0]
            if normalize_embeddings:
                norm = sum(x * x for x in base) ** 0.5
                base = [x / norm for x in base]
            vectors.append(base)
        return vectors


@pytest.fixture
def service():
    return EmbeddingService(model_name="fake-model", model=_FakeModel())


def test_embed_returns_one_vector_per_text(service):
    vectors = service.embed(["alpha", "beta particle"])
    assert len(vectors) == 2
    assert all(len(vector) == 3 for vector in vectors)


def test_embed_one_returns_single_vector(service):
    vector = service.embed_one("hello world")
    assert isinstance(vector, list)
    assert all(isinstance(x, float) for x in vector)


def test_embed_empty_input_returns_empty_list(service):
    assert service.embed([]) == []


def test_embed_is_deterministic_for_same_text(service):
    assert service.embed_one("consistent text") == service.embed_one("consistent text")


def test_serialize_deserialize_round_trip(service):
    vector = service.embed_one("round trip")
    payload = service.serialize(vector)
    assert json.loads(payload) == vector
    assert EmbeddingService.deserialize(payload) == vector
