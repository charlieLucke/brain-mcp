"""Pydantic schemas matching the Titan service HTTP API.

These are intentionally kept as a local copy (not imported from titan) so that
brain-mcp stays decoupled from the titan package. If the API evolves, update
both sides and bump the version field.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    text: str
    source_path: str
    domain: str
    chunk_offset: int
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    bge_loaded: bool
    qdrant_reachable: bool
    vram_used_mb: int | None
    collection_name: str
    colbert_dim: int | None  # None when BGE-M3 is not loaded (degraded state)


class SearchResponse(BaseModel):
    query: str
    chunks: list[Chunk]
    sub_queries: list[str]
    cache_hit: bool
    latency_ms: int


class IngestResponse(BaseModel):
    file_path: str
    domain: str | None
    chunks_deleted: int
    chunks_created: int
    skipped_reason: str | None
    latency_ms: int


class DomainsResponse(BaseModel):
    domains: list[str]
    counts: dict[str, int]


class FindRelatedResponse(BaseModel):
    source_path: str
    related: list[Chunk]
    latency_ms: int


class NoteInfo(BaseModel):
    source_path: str
    domain: str
    chunk_count: int
    content_hash: str | None = None  # sha256 of note raw bytes; null for legacy/PDF chunks


class NotesResponse(BaseModel):
    notes: list[NoteInfo]
    total: int
