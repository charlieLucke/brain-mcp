"""Schreibzugriff auf den Vault — mit Netz.

Bis 29.08.2026 war der Vault fuer Claude nur lesbar. Alles, was in einer Sitzung
erarbeitet wurde, war danach weg: Die Pruefung vom selben Tag fand zwanzig
Fehler und konnte sie nur festhalten, weil Claude Code direkten Dateizugriff
hatte. Ueber den Connector waere nichts davon im Vault gelandet.

Vier Regeln, alle **hier** durchgesetzt und nicht in einem Prompt erbeten. Ein
Werkzeug, das das Falsche nicht kann, schlaegt eine Anweisung, es nicht zu tun:

1. **Pfad-Sandbox.** Nur `.md` unterhalb von ``vault_root``. Symlinks werden
   aufgeloest, bevor geprueft wird.
2. **Stale-Check.** Wer aendert, muss den Hash mitschicken, den er beim Lesen
   bekommen hat. Passt er nicht mehr, wird abgelehnt statt still ueberschrieben.
3. **Herkunft.** Jeder Schreibvorgang eines Agenten setzt ``quelle:
   agent-entwurf`` und **entfernt** ``geprueft``. Das ist das Gegenmittel gegen
   die Rueckkopplung, in der ein Agent seine eigenen Ausgaben spaeter als
   Wahrheit zurueckliest: Was er anfasst, gilt als ungeprueft, taucht in
   ``list_stale`` auf und wird erst durch ``mark_verified`` wieder sauber.
4. **Ein Commit je Schreibvorgang**, mit eigenem Autor. Sonst ist "Git ist das
   Netz" eine Behauptung und kein Rueckweg.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import frontmatter

from brain_mcp.config import settings

# Geschlossene Liste, gespiegelt aus F:\vault\CLAUDE.md. titan legt eine
# unbekannte Domain wortlos an — es gibt dort keine Fehlermeldung, die einen
# Tippfehler auffaengt. Deshalb faengt ihn dieses Werkzeug.
VAULT_DOMAINS: frozenset[str] = frozenset(
    {"arbeitsplatz", "betrieb", "rag-system", "projekte", "vault", "lernen", "business"}
)

QUELLE_AGENT = "agent-entwurf"
QUELLEN: frozenset[str] = frozenset({"gemessen", "recherchiert", "ueberlegt", QUELLE_AGENT})

# Reihenfolge im Frontmatter, damit Diffs lesbar bleiben.
FELD_REIHENFOLGE = ("domain", "created", "updated", "geprueft", "quelle", "tags", "source")

GIT_AUTHOR = "Claude (brain-mcp) <noreply@anthropic.com>"


class VaultWriteError(ValueError):
    """Ein Schreibversuch wurde abgelehnt. Die Nachricht sagt warum."""


class StaleWriteError(VaultWriteError):
    """Die Datei hat sich seit dem Lesen geaendert."""


@dataclass(frozen=True)
class NoteState:
    path: Path
    meta: dict[str, Any]
    body: str
    content_hash: str


# ─── Pfad und Lesen ──────────────────────────────────────────────────────────


def resolve_note_path(file_path: str, *, must_exist: bool) -> Path:
    """Prueft einen Pfad gegen die Sandbox und gibt ihn aufgeloest zurueck.

    Raises:
        VaultWriteError: ausserhalb des Vaults, keine .md, oder Existenz passt
            nicht zur Erwartung.
    """
    root = settings.vault_root.resolve()
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = root / "notes" / candidate
    # resolve() loest Symlinks auf, bevor verglichen wird — sonst liesse sich
    # per Symlink aus dem Vault herauszeigen.
    resolved = candidate.resolve()

    if not resolved.is_relative_to(root):
        raise VaultWriteError(f"Pfad liegt ausserhalb des Vaults ({root}): {file_path}")
    if resolved.suffix.lower() != ".md":
        raise VaultWriteError(f"Nur .md-Dateien, nicht: {resolved.name}")
    if must_exist and not resolved.is_file():
        raise VaultWriteError(f"Notiz existiert nicht: {resolved}")
    if not must_exist and resolved.exists():
        raise VaultWriteError(
            f"Notiz existiert bereits: {resolved}. "
            "Zum Aendern edit_note oder append_section nehmen."
        )
    return resolved


def read_note(path: Path) -> NoteState:
    """Liest eine Notiz samt Hash — der Hash ist der Schluessel fuer den Stale-Check."""
    raw = path.read_bytes()
    post = frontmatter.loads(raw.decode("utf-8"))
    return NoteState(
        path=path,
        meta=dict(post.metadata),
        body=post.content,
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


# ─── Frontmatter ─────────────────────────────────────────────────────────────


def pruefe_domain(domain: str) -> str:
    d = (domain or "").strip()
    if d not in VAULT_DOMAINS:
        raise VaultWriteError(
            f"Unbekannte Domain {d!r}. Erlaubt sind: {', '.join(sorted(VAULT_DOMAINS))}. "
            "Eine neue Domain ist eine Entscheidung ueber die Vault-Struktur — "
            "die trifft der Mensch, nicht das Werkzeug."
        )
    return d


def markiere_als_agentenarbeit(meta: dict[str, Any]) -> dict[str, Any]:
    """Setzt Herkunft und Datum nach einem Agenten-Schreibvorgang.

    ``geprueft`` wird **entfernt**, nicht beibehalten. Eine Notiz, an der ein
    Agent gearbeitet hat, ist als Ganzes nicht mehr geprueft — auch wenn der
    Mensch die alten Teile mal geprueft hatte. Genau so landet sie in
    ``list_stale`` und wird wieder angesehen.
    """
    neu = dict(meta)
    neu["updated"] = date.today().isoformat()
    neu["quelle"] = QUELLE_AGENT
    neu.pop("geprueft", None)
    return neu


def rendere(meta: dict[str, Any], body: str) -> str:
    zeilen = [f"{k}: {meta[k]}" for k in FELD_REIHENFOLGE if k in meta and meta[k] is not None]
    zeilen += [f"{k}: {v}" for k, v in meta.items() if k not in FELD_REIHENFOLGE and v is not None]
    return "---\n" + "\n".join(zeilen) + "\n---\n\n" + body.lstrip("\n")


# ─── Git ─────────────────────────────────────────────────────────────────────


def git_commit(paths: list[Path], subject: str, body: str = "") -> str:
    """Committet die Aenderung als Agent. Gibt den kurzen Hash zurueck.

    Ohne diesen Schritt waere "Git ist das Netz" eine Behauptung. Der eigene
    Autor macht `git log --author="Claude (brain-mcp)"` zur Antwort auf die
    Frage, was der Agent angefasst hat.
    """
    root = settings.vault_root.resolve()
    nachricht = f"{subject}\n\n{body}".strip() if body else subject

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60
        )

    add = git("add", "--", *[str(p) for p in paths])
    if add.returncode != 0:
        raise VaultWriteError(f"git add fehlgeschlagen: {add.stderr.strip()}")

    commit = git("commit", f"--author={GIT_AUTHOR}", "-m", nachricht)
    if commit.returncode != 0:
        if "nothing to commit" in (commit.stdout + commit.stderr).lower():
            return "(nichts zu committen)"
        raise VaultWriteError(f"git commit fehlgeschlagen: {commit.stderr.strip()}")

    kurz = git("rev-parse", "--short", "HEAD")
    return kurz.stdout.strip() or "?"
