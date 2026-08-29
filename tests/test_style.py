"""Tests fuer vault_style — die Form fuer Sitzungen, die sie nicht selbst sehen.

Der Schwerpunkt liegt auf dem, was passiert, wenn eine Quelle **fehlt**. Ein
Werkzeug, das stillschweigend die Haelfte liefert, waere schlimmer als eines,
das eine Luecke benennt: Der Agent schreibt dann eine Notiz nach halber Form
und niemand sieht, warum.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_mcp import style as st
from brain_mcp.style import abschnitt, lade_stil

SKILL = """---
name: vault-notiz
description: irgendwas
---

# Die Hausform

Ein Absatz.

## Frontmatter

Vier Felder.
"""

CLAUDE = """---
indexed: false
---

# Agent Instructions

Vorspann.

## Zuerst lesen

Eins, zwei.

## Harte Regeln

- Keine Zugangsdaten in Notizen.
- Nichts loeschen ohne Rueckfrage.

## Arbeitsweise

Messen statt behaupten.
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vault"
    (root / ".claude/skills/vault-notiz").mkdir(parents=True)
    (root / SKILL_NAME).write_text(SKILL, encoding="utf-8")
    (root / "CLAUDE.md").write_text(CLAUDE, encoding="utf-8")
    monkeypatch.setattr(st.settings, "vault_root", root)
    return root


SKILL_NAME = ".claude/skills/vault-notiz/SKILL.md"


# ─── abschnitt ───────────────────────────────────────────────────────────────


def test_schneidet_bis_zur_naechsten_ueberschrift() -> None:
    a = abschnitt(CLAUDE, "Harte Regeln")
    assert a is not None
    assert a.startswith("## Harte Regeln")
    assert "Keine Zugangsdaten" in a
    assert "Messen statt behaupten" not in a


def test_letzter_abschnitt_geht_bis_zum_ende() -> None:
    a = abschnitt(CLAUDE, "Arbeitsweise")
    assert a is not None
    assert a.rstrip().endswith("Messen statt behaupten.")


def test_unbekannte_ueberschrift_gibt_none() -> None:
    assert abschnitt(CLAUDE, "Gibt es nicht") is None


# ─── lade_stil ───────────────────────────────────────────────────────────────


def test_liefert_skill_und_harte_regeln(vault: Path) -> None:
    text = lade_stil()
    assert "Die Hausform" in text
    assert "Keine Zugangsdaten" in text
    # Das Frontmatter des Skills gehoert den Claude-Apps, nicht dem Leser.
    assert "name: vault-notiz" not in text
    # Und nicht der ganze Rest von CLAUDE.md.
    assert "Messen statt behaupten" not in text


def test_fehlender_skill_wird_benannt(vault: Path) -> None:
    (vault / SKILL_NAME).unlink()
    text = lade_stil()
    assert "nicht gefunden" in text
    # Die harten Regeln kommen trotzdem — halbe Form ist besser als keine.
    assert "Keine Zugangsdaten" in text


def test_fehlende_claude_md_wird_benannt(vault: Path) -> None:
    (vault / "CLAUDE.md").unlink()
    text = lade_stil()
    assert "nicht gefunden" in text
    assert "Die Hausform" in text


def test_umbenannter_abschnitt_faellt_auf(vault: Path) -> None:
    """Wird 'Harte Regeln' in CLAUDE.md umbenannt, schweigt das Werkzeug nicht."""
    (vault / "CLAUDE.md").write_text(
        CLAUDE.replace("## Harte Regeln", "## Regeln"), encoding="utf-8"
    )
    text = lade_stil()
    assert "Harte Regeln" in text and "nicht gefunden" in text
