"""Landkarte des Vaults (brain_mcp.vault_map)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from brain_mcp.vault_map import erster_satz, karte


def _note(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_map_shows_the_first_sentence_by_domain_and_hides_unindexed(tmp_path: Path) -> None:
    _note(tmp_path, "arbeitsplatz/hub.md",
          "---\ndomain: arbeitsplatz\n---\n\n# Hub\n\n> Stand: alt.\n\n"
          "Der Mini-PC im Flur. Er laeuft immer.\n")  # fmt: skip
    _note(
        tmp_path, "business/leads.md", "---\ndomain: business\nindexed: false\n---\n# Leads\n\nX."
    )
    _note(tmp_path, "00-home.md", "---\ndomain: vault\n---\n# Home\n\nDie Landkarte.\n")
    assert karte(tmp_path) == {
        "arbeitsplatz": [("hub", "Der Mini-PC im Flur.")],
        "vault": [("00-home", "Die Landkarte.")],
    }
    assert list(karte(tmp_path, "vault")) == ["vault"]


def test_first_sentence_is_shortened() -> None:
    assert erster_satz("# T\n\n" + "Wort " * 100).endswith("…")
    assert erster_satz("# T\n\n| Tabelle |\n") == ""
    assert erster_satz("# T\n\n## Abschnitt\n\nSpaeter.") == ""  # keine Einleitung
    assert erster_satz("# T\n\n> **AUS** seit Mai.\n> Mehr.") == "**AUS** seit Mai."


def test_tool_renders_links(tmp_path: Path) -> None:
    from brain_mcp import mcp_server

    _note(
        tmp_path, "notes/privat/ueber-mich.md", "---\ndomain: privat\n---\n# Ich\n\nKurzprofil.\n"
    )
    with patch.object(mcp_server.settings, "vault_root", tmp_path):
        assert mcp_server.vault_map() == "## privat (1)\n- [[ueber-mich]] Kurzprofil."
        assert "No notes" in mcp_server.vault_map("lernen")
