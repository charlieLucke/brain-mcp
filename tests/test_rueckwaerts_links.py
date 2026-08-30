"""Tests fuer den Rueckwaerts-Link-Bericht nach einem Schreibvorgang.

Der Anlass: Am 30.08.2026 hat eine Connector-Sitzung Notizen geaendert und die
Notizen, die darauf verweisen, nicht mitgezogen. In einem Vault haengen
Aussagen aneinander — wer A aendert und B stehen laesst, hat zwei Wahrheiten.

Die Regel dafuer steht in CLAUDE.md. Eine Regel wirkt aber nur, wenn sie im
richtigen Moment vor Augen steht, und der richtige Moment ist die Antwort des
Schreibwerkzeugs.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from brain_mcp import mcp_server as srv
from brain_mcp.schemas import FindRelatedResponse, LinkedNote


def _antwort(*paare: tuple[str, str]) -> FindRelatedResponse:
    return FindRelatedResponse(
        source_path="/v/notes/a.md",
        related=[],
        linked=[LinkedNote(source_path=p, domain="betrieb", direction=d) for p, d in paare],
        latency_ms=1,
    )


class _Client:
    def __init__(self, antwort: object) -> None:
        self._antwort = antwort

    def find_related(self, path: Path, top_k: int = 5) -> object:
        if isinstance(self._antwort, Exception):
            raise self._antwort
        return self._antwort


def test_eingehende_links_werden_genannt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        srv, "_client", _Client(_antwort(("/v/notes/b.md", "incoming"), ("/v/notes/c.md", "both")))
    )
    text = srv._wer_zeigt_hierher(Path("/v/notes/a.md"))
    assert "2 note(s) link here" in text
    # Nur der Name, nicht der volle Pfad — achtzehn Pfade waeren eine Wand.
    assert "`b`" in text and "`c`" in text
    assert "/v/notes/" not in text


def test_ausgehende_links_zaehlen_nicht(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wen ICH verlinke, muss ich nicht pruefen — wer MICH verlinkt, schon."""
    monkeypatch.setattr(srv, "_client", _Client(_antwort(("/v/notes/b.md", "outgoing"))))
    text = srv._wer_zeigt_hierher(Path("/v/notes/a.md"))
    assert "No note links here yet" in text


def test_ohne_eingehende_links_kommt_die_verwaisungs_warnung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(srv, "_client", _Client(_antwort()))
    text = srv._wer_zeigt_hierher(Path("/v/notes/a.md"))
    assert "no orphans" in text
    assert "00-home" in text


def test_titan_stumm_bricht_den_schreibvorgang_nicht(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein fehlender Bericht ist ein Mangel, kein Grund, das Schreiben zu verlieren."""
    monkeypatch.setattr(srv, "_client", _Client(httpx.ConnectError("weg")))
    text = srv._wer_zeigt_hierher(Path("/v/notes/a.md"))
    assert "unknown" in text
