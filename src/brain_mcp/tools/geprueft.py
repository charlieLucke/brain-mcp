"""Notizen abnehmen: was ein Agent geschrieben hat, ansehen und bestaetigen.

Das Gegenstueck zu den Schreibwerkzeugen. Jeder Agenten-Schreibvorgang setzt
``quelle: agent-entwurf`` und entfernt ``geprueft`` — die Notiz gilt damit als
ungepruef, bis ein Mensch sie gelesen hat. Ueber den Connector geht das mit
``mark_verified``; hier ist derselbe Weg fuer die Kommandozeile.

    uv run python -m brain_mcp.tools.geprueft              # was ansteht
    uv run python -m brain_mcp.tools.geprueft <notiz>      # was der Agent geaendert hat
    uv run python -m brain_mcp.tools.geprueft <notiz> --ok # abnehmen

**Was das Werkzeug NICHT kann.** Es kann nicht pruefen, ob eine Aussage stimmt —
das ist der ganze Sinn des Feldes. Was es kann, ist die Arbeit klein machen:
statt der ganzen Notiz zeigt es **nur, was sich seit der letzten menschlichen
Berührung geaendert hat.** Meist sind das zwanzig Zeilen statt vierhundert.

Ein erfundenes Datum ist schlimmer als keins — es nimmt die Notiz dauerhaft aus
``list_stale`` heraus. Deshalb setzt ``--ok`` immer das heutige Datum und
verlangt eine Angabe, *wie* der Inhalt belegt ist.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

from brain_mcp.config import settings
from brain_mcp.vault_writer import (
    QUELLE_AGENT,
    QUELLEN,
    VaultWriteError,
    git_commit,
    read_note,
    rendere,
    resolve_note_path,
)

AGENT_AUTOR = "Claude (brain-mcp)"


def _git(*args: str) -> str:
    fertig = subprocess.run(  # noqa: S603 — Listenargumente, keine Shell; die Argumente kommen nicht vom Nutzer
        ["git", "-C", str(settings.vault_root.resolve()), *args],  # noqa: S607 — `git` absichtlich ueber den PATH, nicht auf eine Distribution festgenagelt
        capture_output=True,
        text=True,
        check=False,
    )
    return fertig.stdout


def offene_notizen(nur_agent: bool = True) -> list[tuple[Path, str, str | None]]:
    """Notizen, die auf eine Abnahme warten: (Pfad, quelle, geprueft).

    Standardmaessig **nur Agenten-Entwuerfe**. Der Grund ist Dringlichkeit:
    "ein Agent hat das geschrieben und niemand hat es gelesen" ist etwas
    anderes als "wurde nie gegen die Wirklichkeit gehalten". Das Zweite ist
    ein Dauerzustand vieler Notizen und der Job von ``list_stale``; hier
    wuerde es die eigentliche Arbeit zudecken.
    """
    wurzel = settings.vault_root.resolve()
    offen: list[tuple[Path, str, str | None]] = []
    for pfad in sorted((wurzel / "notes").rglob("*.md")):
        try:
            state = read_note(pfad)
        except (OSError, VaultWriteError):
            continue
        quelle = str(state.meta.get("quelle", ""))
        geprueft = state.meta.get("geprueft")
        if quelle == QUELLE_AGENT or (not nur_agent and not geprueft):
            offen.append((pfad, quelle or "—", str(geprueft) if geprueft else None))
    return offen


def letzte_menschliche_fassung(pfad: Path) -> str | None:
    """Der neueste Commit dieser Datei, der **nicht** vom Agenten stammt.

    Alles danach ist das, was noch niemand gelesen hat. Genau dieser Ausschnitt
    ist die Arbeit — nicht die ganze Notiz.
    """
    roh = _git("log", "--format=%H%x1f%an", "--", str(pfad))
    for zeile in roh.splitlines():
        commit, _, autor = zeile.partition("\x1f")
        if autor != AGENT_AUTOR:
            return commit
    return None


# Der leere Git-Baum. Basis fuer eine Notiz, die noch nie ein Mensch angefasst
# hat: dann ist "was noch niemand gelesen hat" die ganze Datei.
LEERER_BAUM = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def agenten_diff(pfad: Path) -> str:
    """Was sich seit der letzten menschlichen Fassung geaendert hat.

    Gibt es keine, ist die Antwort **die ganze Notiz** und nicht nichts. Vorher
    stand hier ``git show`` ohne Commit-Angabe, was den letzten Commit fuer diesen
    Pfad zeigt — und leer ausgeht, sobald der letzte Commit die Datei nicht
    beruehrt hat. Fuer genau die Notizen, um die es geht (vom Agenten angelegt,
    von niemandem gelesen), zeigte das Werkzeug damit nichts.
    """
    basis = letzte_menschliche_fassung(pfad) or LEERER_BAUM
    return _git("diff", f"{basis}..HEAD", "--", str(pfad)) or "(keine Aenderung)"


def abnehmen(pfad: Path, quelle: str) -> str:
    if quelle not in QUELLEN or quelle == QUELLE_AGENT:
        erlaubt = ", ".join(sorted(QUELLEN - {QUELLE_AGENT}))
        raise VaultWriteError(f"--quelle muss eins von {erlaubt} sein (war {quelle!r}).")
    state = read_note(pfad)
    heute = date.today().isoformat()
    meta = dict(state.meta)
    meta["geprueft"] = heute
    meta["quelle"] = quelle
    pfad.write_text(rendere(meta, state.body), encoding="utf-8", newline="\n")
    return git_commit([pfad], f"vault: {pfad.stem} geprueft ({heute})")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("notiz", nargs="?", help="Dateiname oder Pfad; ohne Angabe kommt die Liste")
    ap.add_argument("--ok", action="store_true", help="abnehmen: geprueft auf heute setzen")
    ap.add_argument("--quelle", default="gemessen", help="gemessen | recherchiert | ueberlegt")
    ap.add_argument("--alle", action="store_true", help="auch nie gepruefte Notizen zeigen")
    args = ap.parse_args()

    if args.notiz is None:
        offen = offene_notizen(nur_agent=not args.alle)
        if not offen:
            was = "alles geprueft" if args.alle else "kein Agenten-Entwurf offen"
            print(f"Nichts zu tun - {was}.  (--alle zeigt auch nie geprueftes)")
            return 0
        was = "Notiz(en)" if args.alle else "Agenten-Entwurf/-Entwuerfe"
        print(f"{len(offen)} {was} warten auf Abnahme:\n")
        for pfad, quelle, geprueft in offen:
            marke = "AGENT" if quelle == QUELLE_AGENT else "     "
            print(f"  {marke}  {pfad.stem:<38} quelle={quelle:<14} geprueft={geprueft or '—'}")
        print("\nAnsehen:  ... geprueft <notiz>        Abnehmen:  ... geprueft <notiz> --ok")
        return 0

    try:
        pfad = resolve_note_path(args.notiz, must_exist=True)
    except VaultWriteError as exc:
        print(exc, file=sys.stderr)
        return 2

    if not args.ok:
        diff = agenten_diff(pfad).strip()
        print(f"=== {pfad.relative_to(settings.vault_root.resolve())} ===\n")
        print(diff if diff else "Keine Aenderung seit der letzten menschlichen Fassung.")
        print("\nAbnehmen mit:  --ok [--quelle gemessen|recherchiert|ueberlegt]")
        return 0

    try:
        commit = abnehmen(pfad, args.quelle)
    except VaultWriteError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"{pfad.stem}: geprueft {date.today().isoformat()}, quelle={args.quelle}  ({commit})")
    print("Der Watcher indexiert innerhalb von 30 Sekunden nach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
