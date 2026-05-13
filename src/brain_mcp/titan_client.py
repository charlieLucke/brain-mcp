"""HTTP client for the Titan RAG service."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from brain_mcp.schemas import (
    DomainsResponse,
    FindRelatedResponse,
    HealthResponse,
    IngestResponse,
    SearchResponse,
)

log = logging.getLogger(__name__)

# Retry only on transient connection errors, not on HTTP-level errors (4xx/5xx).
_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=4),
    reraise=True,
)


class TitanClient:
    """Thin HTTP wrapper around the Titan service API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: int = 30) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def health(self) -> HealthResponse:
        """GET /health — raises httpx.HTTPError on failure."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return HealthResponse.model_validate(resp.json())

    @_RETRY
    def search(
        self,
        query: str,
        domain: str | None = None,
        top_k: int = 10,
        use_decompose: bool = False,
        use_cache: bool = True,
    ) -> SearchResponse:
        """POST /search — retries on ConnectError."""
        payload: dict[str, object] = {
            "query": query,
            "top_k": top_k,
            "use_decompose": use_decompose,
            "use_cache": use_cache,
        }
        if domain is not None:
            payload["domain"] = domain
        resp = self._client.post("/search", json=payload)
        resp.raise_for_status()
        return SearchResponse.model_validate(resp.json())

    @_RETRY
    def ingest_file(self, file_path: Path, force: bool = False) -> IngestResponse:
        """POST /ingest/file — retries on ConnectError."""
        resp = self._client.post(
            "/ingest/file",
            json={"file_path": str(file_path), "force": force},
        )
        resp.raise_for_status()
        return IngestResponse.model_validate(resp.json())

    def delete_chunks(self, file_path: Path) -> int:
        """DELETE /chunks?source_path=… — returns number of deleted chunks."""
        resp = self._client.delete("/chunks", params={"source_path": str(file_path)})
        resp.raise_for_status()
        data: dict[str, int] = resp.json()
        return data.get("chunks_deleted", 0)

    def list_domains(self) -> DomainsResponse:
        """GET /domains."""
        resp = self._client.get("/domains")
        resp.raise_for_status()
        return DomainsResponse.model_validate(resp.json())

    @_RETRY
    def find_related(self, file_path: Path, top_k: int = 5) -> FindRelatedResponse:
        """POST /find_related — retries on ConnectError."""
        resp = self._client.post(
            "/find_related",
            json={"file_path": str(file_path), "top_k": top_k},
        )
        resp.raise_for_status()
        return FindRelatedResponse.model_validate(resp.json())

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> TitanClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
