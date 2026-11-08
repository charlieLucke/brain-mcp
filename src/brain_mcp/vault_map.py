"""Landkarte des Vaults: je Notiz der Name und der erste Satz unter dem H1.

Die Hausform verlangt unter jedem H1 einen Absatz, der sagt, was die Notiz ist
(``vault_style``). Daraus entsteht die Karte, ohne dass jemand eine Zusammenfassung
pflegt: aendert sich eine Notiz, aendert sich ihre Zeile. Gemessen am 08.11.2026:
59 Notizen, rund 8 500 Zeichen fuer den ganzen Vault, 300 bis 1 900 je Domain.

Wofuer: Vor einer Planung sieht der Agent, was es zu einem Thema ueberhaupt gibt,
und stellt dann gezielte Suchen, statt mit einer oberflaechlichen Frage
anzufangen und nur das zu finden, wonach er schon gefragt hat.

Notizen mit ``indexed: false`` fehlen, wie in der Suche.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

MAX_SATZ = 220
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_SATZENDE = re.compile(r"(?<=[.!?])\s")
_KEIN_FLIESSTEXT = (">", "!", "|", "#", "```", "-", "*")


def _feld(frontmatter: str, name: str) -> str | None:
    found = re.search(rf"^{name}:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    return found.group(1) if found else None


def erster_satz(text: str) -> str:
    """Erster Satz der Einleitung zwischen H1 und erstem ``##``, gekuerzt; sonst leer."""
    heading = re.search(r"^# .+$", text, re.MULTILINE)
    rest = text[heading.end() :] if heading else text
    rest = re.split(r"^## ", rest, maxsplit=1, flags=re.MULTILINE)[0]  # nur die Einleitung
    absaetze = [a.strip() for a in re.split(r"\n\s*\n", rest) if a.strip()]
    text_ = next((a for a in absaetze if not a.startswith(_KEIN_FLIESSTEXT)), None)
    if text_ is None:  # Rueckfall: Einleitung als Zitatblock ("> STATUS: AUS ...")
        zitat = next((a for a in absaetze if a.startswith(">")), "")
        text_ = re.sub(r"^>\s?", "", zitat, flags=re.MULTILINE)
    satz = _SATZENDE.split(" ".join(text_.split()), maxsplit=1)[0]
    return satz if len(satz) <= MAX_SATZ else satz[: MAX_SATZ - 1].rstrip() + "…"


def karte(notes_root: Path, domain: str | None = None) -> dict[str, list[tuple[str, str]]]:
    """``domain -> [(notizname, erster satz), ...]``, Domains und Namen sortiert."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted(notes_root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        found = _FRONTMATTER.match(text)
        frontmatter = found.group(1) if found else ""
        if (_feld(frontmatter, "indexed") or "").lower() == "false":
            continue
        note_domain = _feld(frontmatter, "domain")
        if note_domain is None or (domain and note_domain != domain):
            continue
        body = text[found.end() :] if found else text
        out[note_domain].append((path.stem, erster_satz(body)))
    return dict(sorted(out.items()))
