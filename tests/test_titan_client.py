"""Unit tests for TitanClient using httpx mock transport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from brain_mcp.titan_client import TitanClient


def _mock_transport(responses: dict[tuple[str, str], tuple[int, object]]) -> httpx.MockTransport:
    """Build a simple httpx.MockTransport from a {(method, path): (status, body)} dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in responses:
            return httpx.Response(404, json={"detail": "not found in mock"})
        status, body = responses[key]
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


_HEALTH_OK = {
    "status": "ok",
    "bge_loaded": True,
    "qdrant_reachable": True,
    "vram_used_mb": 4096,
    "collection_name": "mein_wissen",
    "colbert_dim": 1024,
}

_SEARCH_RESPONSE = {
    "query": "test",
    "chunks": [
        {
            "text": "Hello world",
            "source_path": "/mnt/f/vault/note.md",
            "domain": "lernen",
            "chunk_offset": 0,
            "score": 0.87,
            "metadata": {},
        }
    ],
    "sub_queries": [],
    "cache_hit": False,
    "latency_ms": 42,
}

_INGEST_RESPONSE = {
    "file_path": "/mnt/f/vault/note.md",
    "domain": "lernen",
    "chunks_deleted": 0,
    "chunks_created": 3,
    "skipped_reason": None,
    "latency_ms": 200,
}

_DOMAINS_RESPONSE = {
    "domains": ["lernen", "titan"],
    "counts": {"lernen": 10, "titan": 5},
}

_FIND_RELATED_RESPONSE = {
    "source_path": "/mnt/f/vault/note.md",
    "related": [],
    "latency_ms": 30,
}


@pytest.fixture()
def client() -> TitanClient:
    transport = _mock_transport(
        {
            ("GET", "/health"): (200, _HEALTH_OK),
            ("POST", "/search"): (200, _SEARCH_RESPONSE),
            ("POST", "/ingest/file"): (200, _INGEST_RESPONSE),
            ("DELETE", "/chunks"): (200, {"chunks_deleted": 2}),
            ("GET", "/domains"): (200, _DOMAINS_RESPONSE),
            ("POST", "/find_related"): (200, _FIND_RELATED_RESPONSE),
        }
    )
    raw = httpx.Client(base_url="http://127.0.0.1:8765", transport=transport)
    c = TitanClient.__new__(TitanClient)
    c._client = raw
    return c


def test_health(client: TitanClient) -> None:
    result = client.health()
    assert result.status == "ok"
    assert result.bge_loaded is True


def test_search(client: TitanClient) -> None:
    result = client.search("test", domain="lernen", top_k=5)
    assert result.query == "test"
    assert len(result.chunks) == 1
    assert result.chunks[0].score == pytest.approx(0.87)


def test_ingest_file(client: TitanClient) -> None:
    result = client.ingest_file(Path("/mnt/f/vault/note.md"))
    assert result.chunks_created == 3
    assert result.domain == "lernen"


def test_delete_chunks(client: TitanClient) -> None:
    n = client.delete_chunks(Path("/mnt/f/vault/note.md"))
    assert n == 2


def test_list_domains(client: TitanClient) -> None:
    result = client.list_domains()
    assert "lernen" in result.domains
    assert result.counts["titan"] == 5


def test_find_related(client: TitanClient) -> None:
    result = client.find_related(Path("/mnt/f/vault/note.md"))
    assert result.source_path == "/mnt/f/vault/note.md"


def test_health_404_raises(client: TitanClient) -> None:
    transport = _mock_transport({("GET", "/health"): (503, {"detail": "down"})})
    raw = httpx.Client(base_url="http://127.0.0.1:8765", transport=transport)
    c = TitanClient.__new__(TitanClient)
    c._client = raw
    with pytest.raises(httpx.HTTPStatusError):
        c.health()


def test_health_degraded_colbert_dim_none(client: TitanClient) -> None:
    """B-CRIT-1 regression: colbert_dim=null must not raise a ValidationError."""
    degraded = {
        "status": "degraded",
        "bge_loaded": False,
        "qdrant_reachable": True,
        "vram_used_mb": None,
        "collection_name": "mein_wissen",
        "colbert_dim": None,
    }
    transport = _mock_transport({("GET", "/health"): (200, degraded)})
    raw = httpx.Client(base_url="http://127.0.0.1:8765", transport=transport)
    c = TitanClient.__new__(TitanClient)
    c._client = raw
    result = c.health()  # must not raise
    assert result.status == "degraded"
    assert result.colbert_dim is None
