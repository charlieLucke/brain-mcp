"""Tests for list_stale — the tool that finds what nobody has checked lately.

The interesting cases are the absent values: a note with no 'geprueft' date has
never been verified, which is a stronger finding than one verified long ago.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from brain_mcp.mcp_server import _days_since, list_stale
from brain_mcp.schemas import NoteInfo, NotesResponse


def _note(
    name: str,
    domain: str = "betrieb",
    geprueft: str | None = None,
    quelle: str | None = "gemessen",
) -> NoteInfo:
    return NoteInfo(
        source_path=f"/mnt/f/vault/notes/{name}.md",
        domain=domain,
        chunk_count=3,
        content_hash="abc",
        updated="2026-08-29",
        geprueft=geprueft,
        quelle=quelle,
    )


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _run(notes: list[NoteInfo], **kwargs: object) -> str:
    response = NotesResponse(notes=notes, total=len(notes))
    with patch("brain_mcp.mcp_server._client") as client:
        client.list_notes.return_value = response
        return list_stale(**kwargs)  # type: ignore[arg-type]


# ─── _days_since ─────────────────────────────────────────────────────────────


def test_days_since_none_bei_fehlendem_datum() -> None:
    assert _days_since(None) is None
    assert _days_since("") is None


def test_days_since_none_bei_muell_statt_absturz() -> None:
    """Ein kaputtes Datum darf das Werkzeug nicht sprengen."""
    assert _days_since("gestern") is None
    assert _days_since("2026-13-45") is None


def test_days_since_rechnet_korrekt() -> None:
    assert _days_since(_days_ago(10)) == 10
    assert _days_since(date.today().isoformat()) == 0


# ─── list_stale ──────────────────────────────────────────────────────────────


def test_nie_geprueft_wird_gefunden() -> None:
    out = _run([_note("a", geprueft=None)])
    assert "never checked" in out
    assert "a.md" in out


def test_frisch_geprueftes_taucht_nicht_auf() -> None:
    out = _run([_note("a", geprueft=_days_ago(5))])
    assert "Nothing stale" in out


def test_alt_geprueftes_wird_gefunden() -> None:
    out = _run([_note("a", geprueft=_days_ago(200))], older_than_days=90)
    assert "200 days ago" in out


def test_schwelle_wird_beachtet() -> None:
    notes = [_note("a", geprueft=_days_ago(100))]
    assert "Nothing stale" in _run(notes, older_than_days=365)
    assert "100 days ago" in _run(notes, older_than_days=30)


def test_agent_entwurf_steht_ganz_oben() -> None:
    """Ein ungeprüfter Agenten-Entwurf ist der dringendste Fall, auch wenn er frisch ist."""
    notes = [
        _note("alt", geprueft=_days_ago(500)),
        _note("entwurf", geprueft=_days_ago(0), quelle="agent-entwurf"),
    ]
    out = _run(notes)
    assert out.index("entwurf.md") < out.index("alt.md")
    assert "drafted by an agent" in out


def test_aeltestes_zuerst() -> None:
    notes = [
        _note("juenger", geprueft=_days_ago(100)),
        _note("aelter", geprueft=_days_ago(400)),
    ]
    out = _run(notes, older_than_days=90)
    assert out.index("aelter.md") < out.index("juenger.md")


def test_domain_filter() -> None:
    notes = [_note("a", domain="betrieb"), _note("b", domain="lernen")]
    out = _run(notes, domain="lernen")
    assert "b.md" in out
    assert "a.md" not in out


def test_leerer_index() -> None:
    assert "No notes indexed yet" in _run([])


def test_unbekannte_domain() -> None:
    out = _run([_note("a", domain="betrieb")], domain="gibtesnicht")
    assert "No indexed notes in domain" in out
