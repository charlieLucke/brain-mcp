"""Die Hausform des Vaults fuer Sitzungen, die sie nicht von selbst sehen.

Claude Code laedt ``CLAUDE.md`` in jeder Sitzung und findet den Skill unter
``.claude/skills/``. Eine Sitzung ueber den Connector — claude.ai, Desktop,
Handy — sieht **beides nicht**: Skills sind ein Mechanismus der Claude-Apps und
reisen nicht ueber MCP mit, und ``CLAUDE.md`` traegt ``indexed: false``.

Der Ausweg waere gewesen, die Form in die Werkzeugbeschreibungen zu schreiben.
Gemessen am 29.08.2026 kosten die elf Docstrings zusammen rund 1 500 Tokens, in
**jeder** Sitzung mit dem Connector. Der Skill allein waere noch einmal so viel,
und er wird bei den meisten Anfragen gar nicht gebraucht. Also ein Werkzeug, das
ihn auf Zuruf liefert: rund 75 Tokens fix, der Rest nur bei Bedarf.

Und bewusst **gelesen statt kopiert**. Die Alternative — die Form hier im Code
zu wiederholen — waere eine zweite Wahrheit, die still veraltet. Dieselbe
Ueberlegung wie bei der Junction, die den Skill lokal ueberall verfuegbar macht,
ohne ihn zu vervielfaeltigen.
"""

from __future__ import annotations

import re
from pathlib import Path

from brain_mcp.config import settings

SKILL_REL = Path(".claude/skills/vault-notiz/SKILL.md")
CLAUDE_REL = Path("CLAUDE.md")
HARTE_REGELN = "Harte Regeln"

_H2 = re.compile(r"^## (.+?)\s*$")


def abschnitt(text: str, ueberschrift: str) -> str | None:
    """Gibt einen ``##``-Abschnitt samt Ueberschrift zurueck, oder None."""
    zeilen = text.splitlines()
    start: int | None = None
    for i, zeile in enumerate(zeilen):
        treffer = _H2.match(zeile)
        if treffer is None:
            continue
        if start is None and treffer.group(1) == ueberschrift:
            start = i
        elif start is not None:
            return "\n".join(zeilen[start:i]).rstrip()
    return "\n".join(zeilen[start:]).rstrip() if start is not None else None


def _lies(pfad: Path) -> str | None:
    try:
        return pfad.read_text(encoding="utf-8")
    except OSError:
        return None


def lade_stil() -> str:
    """Skill plus die harten Regeln, die kein Werkzeug erzwingen kann.

    Was der Code selbst durchsetzt (Sandbox, Domain-Liste, Herkunft), steht
    absichtlich **nicht** hier — dafuer braucht niemand eine Anweisung.
    Fehlt eine Quelle, sagt die Antwort das. Stillschweigend die Haelfte zu
    liefern waere schlimmer als eine Luecke, die man sieht.
    """
    wurzel = settings.vault_root.resolve()
    teile: list[str] = []

    skill = _lies(wurzel / SKILL_REL)
    if skill is None:
        teile.append(f"⚠️ Skill nicht gefunden unter {SKILL_REL} — Form unbekannt.")
    else:
        # Das Frontmatter ist fuer die Claude-Apps, nicht fuer den Leser.
        ohne_fm = re.sub(r"\A---\n.*?\n---\n", "", skill, count=1, flags=re.DOTALL)
        teile.append(ohne_fm.strip())

    claude = _lies(wurzel / CLAUDE_REL)
    regeln = abschnitt(claude, HARTE_REGELN) if claude else None
    if regeln is None:
        teile.append(
            f"⚠️ Abschnitt '{HARTE_REGELN}' in {CLAUDE_REL} nicht gefunden — "
            "die harten Regeln bitte dort nachlesen."
        )
    else:
        teile.append(
            "---\n\n# Aus CLAUDE.md — gilt auch hier\n\n"
            "Diese Sitzung laedt CLAUDE.md nicht. Der folgende Abschnitt steht "
            "unveraendert dort und ist die Quelle; hier ist nur eine Kopie fuer "
            "die Dauer dieser Antwort.\n\n" + regeln
        )

    return "\n\n".join(teile)
