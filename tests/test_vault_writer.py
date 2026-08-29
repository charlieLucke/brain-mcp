"""Tests fuer den Schreibzugriff auf den Vault.

Der Schwerpunkt liegt auf dem, was **abgelehnt** werden muss. Ein Schreibwerkzeug
wird an seinen Grenzen gemessen, nicht daran, dass es im Normalfall schreibt.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brain_mcp import vault_writer as vw
from brain_mcp.vault_writer import (
    QUELLE_AGENT,
    StaleWriteError,
    VaultWriteError,
    markiere_als_agentenarbeit,
    pruefe_domain,
    read_note,
    rendere,
    resolve_note_path,
)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vault"
    (root / "notes").mkdir(parents=True)
    monkeypatch.setattr(vw.settings, "vault_root", root)
    return root


def _notiz(vault: Path, name: str, text: str = "# Titel\n\nInhalt.\n", **meta: str) -> Path:
    felder = {"domain": "betrieb", "updated": "2026-08-01", "quelle": "gemessen", **meta}
    kopf = "\n".join(f"{k}: {v}" for k, v in felder.items())
    p = vault / "notes" / f"{name}.md"
    p.write_text(f"---\n{kopf}\n---\n\n{text}", encoding="utf-8")
    return p


# ─── Pfad-Sandbox ────────────────────────────────────────────────────────────


def test_relativer_name_landet_in_notes(vault: Path) -> None:
    assert resolve_note_path("neu.md", must_exist=False) == vault / "notes" / "neu.md"


def test_pfad_ausserhalb_wird_abgelehnt(vault: Path) -> None:
    with pytest.raises(VaultWriteError, match="ausserhalb"):
        resolve_note_path("/etc/passwd.md", must_exist=False)


def test_traversal_wird_abgelehnt(vault: Path) -> None:
    with pytest.raises(VaultWriteError, match="ausserhalb"):
        resolve_note_path("../../../tmp/boese.md", must_exist=False)


def test_symlink_aus_dem_vault_heraus_wird_abgelehnt(vault: Path, tmp_path: Path) -> None:
    """resolve() vor dem Vergleich - sonst zeigt ein Symlink nach draussen."""
    ziel = tmp_path / "draussen.md"
    ziel.write_text("x", encoding="utf-8")
    link = vault / "notes" / "link.md"
    try:
        link.symlink_to(ziel)
    except (OSError, NotImplementedError):
        pytest.skip("keine Symlinks in dieser Umgebung")
    with pytest.raises(VaultWriteError, match="ausserhalb"):
        resolve_note_path(str(link), must_exist=True)


def test_nur_markdown(vault: Path) -> None:
    with pytest.raises(VaultWriteError, match=r"\.md"):
        resolve_note_path("skript.sh", must_exist=False)


def test_neu_aber_existiert_schon(vault: Path) -> None:
    _notiz(vault, "da")
    with pytest.raises(VaultWriteError, match="existiert bereits"):
        resolve_note_path("da.md", must_exist=False)


def test_bearbeiten_aber_gibt_es_nicht(vault: Path) -> None:
    with pytest.raises(VaultWriteError, match="existiert nicht"):
        resolve_note_path("weg.md", must_exist=True)


# ─── Domains ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("d", ["betrieb", "arbeitsplatz", "rag-system", "vault", "lernen"])
def test_bekannte_domains(d: str) -> None:
    assert pruefe_domain(d) == d


def test_unbekannte_domain_wird_abgelehnt() -> None:
    """titan legt sie wortlos an - deshalb muss das Werkzeug es fangen."""
    with pytest.raises(VaultWriteError, match="Unbekannte Domain"):
        pruefe_domain("technik")


def test_fehlermeldung_nennt_die_erlaubten() -> None:
    with pytest.raises(VaultWriteError, match="arbeitsplatz"):
        pruefe_domain("")


# ─── Herkunft ────────────────────────────────────────────────────────────────


def test_agentenschreiben_entfernt_geprueft() -> None:
    """Der Kern gegen die Rueckkopplung.

    Eine Notiz, an der ein Agent gearbeitet hat, ist als Ganzes nicht mehr
    geprueft - auch wenn der Mensch die alten Teile geprueft hatte. Bliebe
    geprueft stehen, wuerde der Agent seine eigenen Ausgaben spaeter als
    verifiziert zurueckbekommen.
    """
    meta = markiere_als_agentenarbeit(
        {"domain": "betrieb", "geprueft": "2026-08-29", "quelle": "gemessen"}
    )
    assert "geprueft" not in meta
    assert meta["quelle"] == QUELLE_AGENT
    assert meta["updated"] == date.today().isoformat()


def test_andere_felder_bleiben_erhalten() -> None:
    meta = markiere_als_agentenarbeit({"domain": "vault", "created": "2026-01-01", "tags": "[a]"})
    assert meta["domain"] == "vault"
    assert meta["created"] == "2026-01-01"
    assert meta["tags"] == "[a]"


def test_original_wird_nicht_veraendert() -> None:
    original = {"domain": "betrieb", "geprueft": "2026-08-29"}
    markiere_als_agentenarbeit(original)
    assert original["geprueft"] == "2026-08-29"


# ─── Rendern und Lesen ───────────────────────────────────────────────────────


def test_feldreihenfolge_ist_stabil() -> None:
    text = rendere({"quelle": "gemessen", "domain": "betrieb", "updated": "2026-08-29"}, "# T\n")
    kopf = text.split("---")[1]
    assert kopf.index("domain") < kopf.index("updated") < kopf.index("quelle")


def test_unbekannte_felder_bleiben_erhalten() -> None:
    text = rendere({"domain": "vault", "eigenes": "wert"}, "# T\n")
    assert "eigenes: wert" in text


def test_rendern_und_lesen_ist_verlustfrei(vault: Path) -> None:
    p = vault / "notes" / "rt.md"
    p.write_text(rendere({"domain": "lernen", "updated": "2026-08-29"}, "# T\n\nText.\n"), "utf-8")
    state = read_note(p)
    assert state.meta["domain"] == "lernen"
    assert "Text." in state.body


def test_hash_aendert_sich_mit_dem_inhalt(vault: Path) -> None:
    p = _notiz(vault, "h")
    vorher = read_note(p).content_hash
    p.write_text(p.read_text(encoding="utf-8") + "\nmehr\n", encoding="utf-8")
    assert read_note(p).content_hash != vorher


# ─── Stale-Check (die Logik, die edit_note benutzt) ──────────────────────────


def test_stale_ist_ein_vaultwriteerror() -> None:
    """Damit ein Aufrufer beide mit einem except faengt, aber unterscheiden kann."""
    assert issubclass(StaleWriteError, VaultWriteError)


# ─── Domain-Unterordner (seit 29.08.2026) ────────────────────────────────────
#
# Die Notizen liegen seither in notes/<domain>/. Ein Agent kennt aber Namen,
# keine Pfade — Wikilinks nennen den Stamm. Ohne die Namenssuche waere jeder
# edit_note("coolify-prod.md", ...) seit der Umsortierung gebrochen, und neue
# Notizen waeren im falschen Ordner gelandet.


def test_neue_notiz_landet_im_domain_ordner(vault: Path) -> None:
    p = resolve_note_path("neu.md", must_exist=False, domain="betrieb")
    assert p == (vault / "notes" / "betrieb" / "neu.md").resolve()


def test_neue_notiz_ohne_domain_bleibt_oben(vault: Path) -> None:
    p = resolve_note_path("neu.md", must_exist=False)
    assert p == (vault / "notes" / "neu.md").resolve()


def test_blosser_name_wird_im_unterordner_gefunden(vault: Path) -> None:
    (vault / "notes" / "betrieb").mkdir(parents=True)
    ziel = vault / "notes" / "betrieb" / "coolify-prod.md"
    ziel.write_text("---\ndomain: betrieb\n---\n\n# X\n", encoding="utf-8")
    assert resolve_note_path("coolify-prod.md", must_exist=True) == ziel.resolve()


def test_mehrdeutiger_name_wird_nicht_geraten(vault: Path) -> None:
    for d in ("betrieb", "projekte"):
        (vault / "notes" / d).mkdir(parents=True)
        (vault / "notes" / d / "doppelt.md").write_text("# X\n", encoding="utf-8")
    with pytest.raises(VaultWriteError, match="mehrfach"):
        resolve_note_path("doppelt.md", must_exist=True)


def test_pfad_ab_vault_wurzel(vault: Path) -> None:
    (vault / "notes" / "lernen").mkdir(parents=True)
    ziel = vault / "notes" / "lernen" / "x.md"
    ziel.write_text("# X\n", encoding="utf-8")
    assert resolve_note_path("notes/lernen/x.md", must_exist=True) == ziel.resolve()


def test_pfad_ab_notes(vault: Path) -> None:
    (vault / "notes" / "lernen").mkdir(parents=True)
    ziel = vault / "notes" / "lernen" / "y.md"
    ziel.write_text("# Y\n", encoding="utf-8")
    assert resolve_note_path("lernen/y.md", must_exist=True) == ziel.resolve()


def test_sandbox_haelt_auch_mit_unterordnern(vault: Path) -> None:
    with pytest.raises(VaultWriteError, match="ausserhalb"):
        resolve_note_path("../../etc/passwd.md", must_exist=False, domain="betrieb")
