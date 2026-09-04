"""Tests fuer das Abnahme-CLI und die sichtbare Herkunft.

Beides beantwortet dieselbe Frage aus verschiedenen Richtungen: Woran erkennt
man, dass eine Notiz noch niemand gelesen hat? Bis zum 30.08.2026 gar nicht —
der Marker stand in der Payload und kam im Suchergebnis nie an.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_mcp import mcp_server as srv
from brain_mcp.schemas import Chunk
from brain_mcp.tools import geprueft as g
from brain_mcp.vault_writer import VaultWriteError


def _chunk(**meta: object) -> Chunk:
    return Chunk(
        text="Text",
        source_path="/v/notes/a.md",
        domain="betrieb",
        chunk_offset=0,
        score=0.9,
        metadata=meta,
    )


# ─── Herkunft im Treffer ─────────────────────────────────────────────────────


def test_agenten_entwurf_wird_gewarnt() -> None:
    assert "noch nicht geprueft" in srv._herkunft(_chunk(quelle="agent-entwurf"))


def test_gemessen_und_geprueft_bleibt_still() -> None:
    assert srv._herkunft(_chunk(quelle="gemessen", geprueft="2026-08-30")) == ""


def test_nie_geprueft_wird_leise_vermerkt() -> None:
    text = srv._herkunft(_chunk(quelle="recherchiert"))
    assert "nie geprueft" in text and "⚠️" not in text


def test_ohne_herkunft_kein_zusatz() -> None:
    assert srv._herkunft(_chunk()) == ""


def test_warnung_steht_in_der_trefferzeile() -> None:
    text = srv._format_chunks([_chunk(quelle="agent-entwurf")], cache_hit=False, latency_ms=1)
    assert "Result 1" in text and "noch nicht geprueft" in text


# ─── Das CLI ─────────────────────────────────────────────────────────────────


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vault"
    (root / "notes" / "betrieb").mkdir(parents=True)
    monkeypatch.setattr(g.settings, "vault_root", root)
    return root


def _schreibe(vault: Path, name: str, **meta: str) -> Path:
    felder = {"domain": "betrieb", "updated": "2026-08-30", **meta}
    kopf = "\n".join(f"{k}: {v}" for k, v in felder.items())
    p = vault / "notes" / "betrieb" / f"{name}.md"
    p.write_text(f"---\n{kopf}\n---\n\n# {name}\n\nInhalt.\n", encoding="utf-8")
    return p


def test_liste_zeigt_agenten_entwuerfe(vault: Path) -> None:
    _schreibe(vault, "entwurf", quelle="agent-entwurf")
    _schreibe(vault, "sauber", quelle="gemessen", geprueft="2026-08-30")
    namen = [p.stem for p, _, _ in g.offene_notizen()]
    assert namen == ["entwurf"]


def test_nie_geprueftes_erst_mit_alle(vault: Path) -> None:
    """Standard ist die dringende Frage, nicht der Dauerzustand."""
    _schreibe(vault, "ohne-datum", quelle="gemessen")
    assert g.offene_notizen() == []
    assert [p.stem for p, _, _ in g.offene_notizen(nur_agent=False)] == ["ohne-datum"]


def test_abnehmen_setzt_datum_und_quelle(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "git_commit", lambda *a, **k: "abc1234")
    p = _schreibe(vault, "entwurf", quelle="agent-entwurf")
    g.abnehmen(p, "gemessen")
    text = p.read_text(encoding="utf-8")
    assert "quelle: gemessen" in text
    assert "agent-entwurf" not in text
    assert "geprueft:" in text


def test_agent_darf_sich_nicht_selbst_abnehmen(vault: Path) -> None:
    """Der ganze Sinn des Feldes waere sonst weg."""
    p = _schreibe(vault, "entwurf", quelle="agent-entwurf")
    with pytest.raises(VaultWriteError, match="quelle"):
        g.abnehmen(p, "agent-entwurf")


def test_unbekannte_quelle_wird_abgelehnt(vault: Path) -> None:
    p = _schreibe(vault, "entwurf", quelle="agent-entwurf")
    with pytest.raises(VaultWriteError):
        g.abnehmen(p, "geraten")


def test_diff_einer_reinen_agentennotiz_zeigt_die_ganze_notiz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ohne menschliche Fassung ist "was niemand gelesen hat" die ganze Datei.

    Vorher lief das ueber ``git show`` ohne Commit-Angabe und ging leer aus, sobald
    der letzte Commit die Datei nicht beruehrt hatte — also fuer genau die Notizen,
    um die es geht.
    """
    aufrufe: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        aufrufe.append(args)
        return "diff --git ...\n+++ alles neu\n"

    monkeypatch.setattr(g, "_git", fake_git)
    monkeypatch.setattr(g, "letzte_menschliche_fassung", lambda p: None)

    ergebnis = g.agenten_diff(Path("/vault/notes/x.md"))

    assert "alles neu" in ergebnis
    assert aufrufe[0][0] == "diff"
    assert aufrufe[0][1].startswith(g.LEERER_BAUM)
