"""FastMCP server — exposes knowledge vault as MCP tools for Claude."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from functools import wraps
from pathlib import Path

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import OAuthProxy

from brain_mcp import read_api
from brain_mcp.auth import build_github_auth
from brain_mcp.config import settings
from brain_mcp.schemas import Chunk, NoteInfo
from brain_mcp.style import lade_stil
from brain_mcp.titan_client import TitanClient
from brain_mcp.vault_writer import (
    QUELLE_AGENT,
    QUELLEN,
    StaleWriteError,
    VaultWriteError,
    git_commit,
    markiere_als_agentenarbeit,
    pruefe_domain,
    read_note,
    rendere,
    resolve_note_path,
)

log = logging.getLogger(__name__)


def _build_auth() -> OAuthProxy | None:
    """Build the OAuth provider when HTTP auth is enabled, else None.

    Auth applies only to the HTTP transport; stdio is local and unauthenticated.
    Raises if BRAIN_MCP_AUTH=github but required settings are missing.
    """
    if settings.mcp_transport != "http" or settings.mcp_auth != "github":
        return None
    allowed_logins = {
        login.strip().lower()
        for login in settings.github_allowed_logins.split(",")
        if login.strip()
    }
    missing = [
        name
        for name, value in (
            ("BRAIN_MCP_BASE_URL", settings.mcp_base_url),
            ("BRAIN_GITHUB_CLIENT_ID", settings.github_client_id),
            ("BRAIN_GITHUB_CLIENT_SECRET", settings.github_client_secret),
            ("BRAIN_GITHUB_ALLOWED_LOGINS", settings.github_allowed_logins),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("BRAIN_MCP_AUTH=github requires these settings: " + ", ".join(missing))
    log.info("OAuth enabled (GitHub), allowlist: %s", sorted(allowed_logins))
    return build_github_auth(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=settings.mcp_base_url,
        allowed_logins=allowed_logins,
    )


mcp: FastMCP = FastMCP("brain", auth=_build_auth())
_client = TitanClient(base_url=settings.titan_url)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TITAN_UNREACHABLE = (
    "Error: Titan service is not reachable. Check `systemctl --user status titan-service`."
)


def _titan_errors[**P](func: Callable[P, str]) -> Callable[P, str]:
    """Übersetzt Transport-Fehler des Titan-Clients in Klartext für Claude.

    Jedes Tool gibt Text zurück — ein Traceback hilft dort niemandem. Vorher
    wiederholte jeder Tool-Handler denselben try/except-Block sechsfach.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return func(*args, **kwargs)
        except httpx.ConnectError:
            return _TITAN_UNREACHABLE
        except httpx.HTTPStatusError as e:
            return f"Error: Titan service returned {e.response.status_code}: {e.response.text}"

    return wrapper


def _herkunft(chunk: Chunk) -> str:
    """Ein Warnhinweis, wenn der Treffer noch niemand geprueft hat.

    Ohne das sieht ein Agenten-Entwurf aus wie eine gemessene Notiz, und der
    Agent liest seine eigene ungepruefte Behauptung als Wahrheit zurueck — die
    Kontaminationsschleife aus plan-second-brain 3.3. Das Feld `quelle` gab es
    seit dem 29.08.2026, aber es kam nie beim Leser an; titan traegt es seit
    dem 30.08. im Suchergebnis mit.
    """
    quelle = chunk.metadata.get("quelle")
    if quelle == "agent-entwurf":
        return "  ⚠️ **von einem Agenten geschrieben, noch nicht geprueft**"
    if quelle and not chunk.metadata.get("geprueft"):
        return f"  _(quelle: {quelle}, nie geprueft)_"
    return ""


def _format_chunks(chunks: list[Chunk], cache_hit: bool, latency_ms: int) -> str:
    """Format a list of Chunk objects as a Markdown string for Claude."""
    if not chunks:
        return "_No relevant chunks found._"
    lines: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        lines.append(
            f"## Result {i} (score: {chunk.score:.2f}, source: {chunk.source_path})"
            f"{_herkunft(chunk)}"
        )
        lines.append(chunk.text.strip())
        lines.append("")
    lines.append(f"*Cache hit: {str(cache_hit).lower()}, latency: {latency_ms}ms*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# B3 — query_knowledge
# ---------------------------------------------------------------------------


@mcp.tool()
@_titan_errors
def query_knowledge(
    query: str,
    domain: str | None = None,
    top_k: int = 10,
) -> str:
    """Search my personal knowledge vault.

    Args:
        query: Natural-language question or keywords to search for.
        domain: Optional domain filter. Use list_domains() first to see available
            domains (e.g. "lernen", "titan", "trading"). Leave empty to search all.
        top_k: Number of chunks to return (1-30). Default 10.

    Returns:
        Markdown-formatted list of relevant chunks with source paths and scores.
        Returns an error message if the Titan service is unreachable.
    """
    top_k = min(max(1, top_k), 30)
    result = _client.search(query, domain=domain, top_k=top_k)
    return _format_chunks(result.chunks, result.cache_hit, result.latency_ms)


# ---------------------------------------------------------------------------
# B4 — ingest_note
# ---------------------------------------------------------------------------


@mcp.tool()
@_titan_errors
def ingest_note(file_path: str, force: bool = False) -> str:
    """Trigger immediate re-indexing of a note (bypasses the watcher's 30-second delay).

    Re-ingesting always *replaces* the note's previous chunks — the old and new
    versions never coexist in the index. To remove a note entirely, use delete_note().

    Use when:
    - You just edited a note and want it searchable immediately.
    - You suspect the index is stale for a specific note.

    Args:
        file_path: Absolute path to the Markdown note inside the vault.
        force: Titan skips re-embedding when the file bytes are unchanged
            (content-hash match). Set True to bypass that skip and re-embed
            anyway. Default False.

    Returns:
        A short status message describing what happened (chunks created/replaced,
        or why the note was skipped).
    """
    path = Path(file_path).resolve()
    if not path.is_relative_to(settings.vault_root):
        return f"Error: {file_path!r} is outside the vault root ({settings.vault_root})."

    result = _client.ingest_file(path, force=force)

    if result.skipped_reason == "unchanged":
        return (
            "Unchanged — the note's content hash matches the indexed version. "
            "Use force=True to re-embed anyway."
        )
    if result.skipped_reason:
        return f"Skipped ({result.skipped_reason}). {result.chunks_deleted} old chunk(s) removed."
    return (
        f"Indexed: {result.chunks_created} chunk(s) created, "
        f"{result.chunks_deleted} replaced. "
        f"Domain: {result.domain}."
    )


# ---------------------------------------------------------------------------
# B5 — list_domains
# ---------------------------------------------------------------------------


@mcp.tool()
@_titan_errors
def list_domains() -> str:
    """List all domains in the knowledge vault with chunk counts.

    Use this before calling query_knowledge() with a domain filter to see
    which domains are available.

    Returns:
        Markdown-formatted list of domains and their chunk counts.
    """
    result = _client.list_domains()

    if not result.domains:
        return "_No domains indexed yet._"
    lines = [f"- **{d}**: {result.counts.get(d, 0)} chunk(s)" for d in result.domains]
    return "Available domains:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# B5 — find_related
# ---------------------------------------------------------------------------


@mcp.tool()
@_titan_errors
def find_related(file_path: str, top_k: int = 5) -> str:
    """Find notes semantically related to a given note.

    Uses the embedding of the note's first chunk to search for similar content
    in the vault, excluding the note itself.

    Args:
        file_path: Absolute path to the source Markdown note inside the vault.
        top_k: Number of related notes to return (1-20). Default 5.

    Returns:
        Markdown-formatted list of related chunks with source paths and scores.
    """
    path = Path(file_path).resolve()
    if not path.is_relative_to(settings.vault_root):
        return f"Error: {file_path!r} is outside the vault root ({settings.vault_root})."

    result = _client.find_related(path, top_k=top_k)
    return _format_chunks(result.related, cache_hit=False, latency_ms=result.latency_ms)


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------


def _hash_suffix(note: NoteInfo) -> str:
    """Render the `content_hash` that `edit_note` compares against.

    Never shortened. `edit_note` compares the whole string, so a display-friendly
    prefix would be a value the caller cannot pass back.
    """
    if note.content_hash:
        return f", hash: `{note.content_hash}`"
    return ", hash: _not indexed_ (legacy or PDF chunk)"


@mcp.tool()
@_titan_errors
def list_notes(domain: str | None = None, with_hash: bool = False) -> str:
    """List every note currently in the search index.

    Use this to see what is indexed — to spot stale entries, confirm a file made
    it into the index, or pick a path for delete_note() or find_related().

    Args:
        domain: Optional domain filter (e.g. "projekte"). Leave empty to list all.
        with_hash: Also print each note's `content_hash` — the value `edit_note`
            demands before it will touch an existing note. Off by default: it is
            64 hex characters per note, and a listing that answers "what is
            indexed" should not make every caller pay for them.

    Returns:
        Markdown list of indexed notes with their domain and chunk count.
    """
    result = _client.list_notes()

    notes = [n for n in result.notes if n.domain == domain] if domain else result.notes
    if not notes:
        return f"_No indexed notes in domain {domain!r}._" if domain else "_No notes indexed yet._"
    lines = [
        f"- `{n.source_path}` — domain: **{n.domain}**, {n.chunk_count} chunk(s)"
        + (_hash_suffix(n) if with_hash else "")
        for n in notes
    ]
    return f"{len(notes)} indexed note(s):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# list_stale
# ---------------------------------------------------------------------------


def _days_since(iso_date: str | None) -> int | None:
    """Whole days between an ISO date and today, or None if unparseable/absent."""
    if not iso_date:
        return None
    try:
        then = date.fromisoformat(iso_date[:10])
    except ValueError:
        return None
    return (date.today() - then).days


@mcp.tool()
@_titan_errors
def list_stale(older_than_days: int = 90, domain: str | None = None) -> str:
    """Find notes whose claims may no longer be true.

    Answers the question a knowledge base cannot otherwise answer: what does it
    still assert that nobody has checked in a long time? Ranked worst first.

    Two kinds of finding, and the first one matters more:
      - never checked: the note has no 'geprueft' date at all
      - checked long ago: older than the given threshold

    Notes written as 'agent-entwurf' (drafted by an AI, never reviewed) are
    listed first regardless of age.

    Args:
        older_than_days: Age threshold for "checked long ago". Default 90.
        domain: Optional domain filter (e.g. "betrieb"). Leave empty for all.

    Returns:
        Markdown list, worst first, with the age and source of each note.
    """
    result = _client.list_notes()
    notes = [n for n in result.notes if n.domain == domain] if domain else result.notes
    if not notes:
        return f"_No indexed notes in domain {domain!r}._" if domain else "_No notes indexed yet._"

    entwuerfe: list[str] = []
    nie: list[str] = []
    alt: list[tuple[int, str]] = []

    for n in notes:
        age = _days_since(n.geprueft)
        label = f"`{n.source_path}` — **{n.domain}**"
        if n.quelle == "agent-entwurf":
            entwuerfe.append(f"- {label} — drafted by an agent, never reviewed")
        elif age is None:
            src = f", source: {n.quelle}" if n.quelle else ""
            nie.append(f"- {label} — **never checked**{src}")
        elif age >= older_than_days:
            alt.append((age, f"- {label} — last checked {age} days ago ({n.geprueft})"))

    if not (entwuerfe or nie or alt):
        return (
            f"_Nothing stale: every note has been checked within {older_than_days} days._\n"
            f"({len(notes)} note(s) examined.)"
        )

    out: list[str] = []
    if entwuerfe:
        out.append(f"**Agent drafts, unreviewed ({len(entwuerfe)}):**")
        out.extend(entwuerfe)
    if nie:
        out.append(f"\n**Never checked ({len(nie)}):**")
        out.extend(nie)
    if alt:
        out.append(f"\n**Checked more than {older_than_days} days ago ({len(alt)}):**")
        out.extend(line for _, line in sorted(alt, reverse=True))

    total = len(entwuerfe) + len(nie) + len(alt)
    out.append(f"\n_{total} of {len(notes)} note(s) worth a look._")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Writing tools
#
# Every write goes through vault_writer, which enforces the path sandbox, the
# stale check, the frontmatter rules and one git commit per write. None of that
# is asked for in a prompt — a tool that cannot do the wrong thing beats an
# instruction not to do it.
# ---------------------------------------------------------------------------


def _write_errors[**P](func: Callable[P, str]) -> Callable[P, str]:
    """Turn a rejected write into a sentence, not a stack trace."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return func(*args, **kwargs)
        except StaleWriteError as exc:
            return f"Rejected — the note changed since you read it.\n\n{exc}"
        except VaultWriteError as exc:
            return f"Rejected: {exc}"
        except OSError as exc:
            return f"Could not write: {exc}"

    return wrapper


def _wer_zeigt_hierher(path: Path) -> str:
    """Die Notizen, die per Wikilink auf diese zeigen.

    **Warum das nach jedem Schreibvorgang mitkommt.** In einem Vault haengen
    Aussagen aneinander: Notiz A sagt etwas, Notiz B verweist darauf. Wer A
    aendert und B stehen laesst, hat zwei Wahrheiten erzeugt. Die Regel dazu
    steht in CLAUDE.md ("Einem Verweis sofort folgen"), aber eine Regel wirkt
    nur, wenn sie im richtigen Moment vor Augen steht - am 30.08.2026 hat eine
    Connector-Sitzung genau das uebersehen.

    Deshalb steht es hier und nicht in einer Werkzeugbeschreibung: Es kostet
    keinen Fixkontext und kommt genau dann, wenn es zaehlt.
    """
    try:
        antwort = _client.find_related(path, top_k=1)
    except httpx.HTTPError:
        return "- inbound links: unknown (titan did not answer)"

    # Nur der Name: ihn nimmt resolve_note_path seit dem 30.08.2026 direkt an,
    # und achtzehn volle Pfade sind eine Wand statt einer Liste.
    rein = [Path(n.source_path).stem for n in antwort.linked if n.direction in ("incoming", "both")]
    if not rein:
        return (
            "- **No note links here yet.** This vault has no orphans - link it from at "
            "least one existing note, usually `notes/00-home.md`."
        )
    liste = ", ".join(f"`{p}`" for p in sorted(rein))
    return (
        f"- **{len(rein)} note(s) link here - check whether they still agree:** {liste}. "
        "A claim you changed here may be repeated or referenced there; two notes "
        "disagreeing is worse than one being incomplete."
    )


def _nach_dem_schreiben(path: Path, commit: str, hinweis: str) -> str:
    """Re-index immediately and report. The watcher would take 30s otherwise."""
    try:
        result = _client.ingest_file(path, force=True)
        indexed = f"{result.chunks_created} chunk(s) indexed"
    except httpx.HTTPError as exc:
        indexed = f"not indexed yet ({exc}) — the watcher will retry"
    return (
        f"{hinweis}\n\n"
        f"- file: `{path}`\n"
        f"- commit: `{commit}`\n"
        f"- index: {indexed}\n"
        f"- **`quelle: agent-entwurf`, `geprueft` cleared** — this note now shows up in "
        f"`list_stale` until a human confirms it with `mark_verified`.\n"
        f"{_wer_zeigt_hierher(path)}"
    )


@mcp.tool()
def vault_style() -> str:
    """The house form for notes in this vault. Call this BEFORE writing or editing one.

    A session reached through this connector sees neither `CLAUDE.md` (it is
    marked `indexed: false`) nor the skill file — skills do not travel over MCP.
    This tool hands both over on request instead of carrying them in every tool
    description, where they would cost tokens in every session including the
    ones that only search.

    Returns:
        Markdown: structure, frontmatter, the sections for open points and
        ideas, linking, how to mark superseded claims, plus the hard rules.
        Around 2000 tokens — call it once per session, not once per note.
    """
    return lade_stil()


@mcp.tool()
@_write_errors
def write_note(file_path: str, domain: str, content: str) -> str:
    """Create a NEW note in the vault. Fails if the file already exists.

    **Call `vault_style` first** unless you already did in this session. The
    house form — structure, frontmatter, section conventions, how long a section
    should be — is not part of these descriptions.

    Frontmatter is written for you — do not include a `---` block in `content`.
    The note is marked `quelle: agent-entwurf`, which means "written by an AI,
    not yet checked by a human". That is not a formality: it keeps the note out
    of the pool of things the vault treats as verified, and `list_stale` will
    keep offering it until someone confirms it.

    Args:
        file_path: Filename (e.g. "neue-notiz.md") or a path inside the vault.
            A bare filename lands in notes/<domain>/ — notes are filed by
            domain since 2026-08-29. Pass a full path only to override that.
        domain: One of arbeitsplatz, betrieb, rag-system, projekte, vault,
            lernen, business. Unknown values are refused — a new domain is a
            decision about the vault's structure and belongs to the operator.
        content: The Markdown body, starting with a `# Heading`.

    Returns:
        Path, commit hash and index status.
    """
    geprueft = pruefe_domain(domain)
    path = resolve_note_path(file_path, must_exist=False, domain=geprueft)
    meta = markiere_als_agentenarbeit({"domain": geprueft})
    meta["created"] = date.today().isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendere(meta, content), encoding="utf-8", newline="\n")

    commit = git_commit(
        [path],
        f"vault(agent): Notiz {path.stem} angelegt",
        "Von Claude ueber brain-mcp geschrieben, noch nicht geprueft.",
    )
    return _nach_dem_schreiben(
        path, commit, f"Created **{path.name}** in domain `{meta['domain']}`."
    )


@mcp.tool()
@_write_errors
def edit_note(file_path: str, old_text: str, new_text: str, content_hash: str) -> str:
    """Replace an exact passage in an existing note.

    **Call `vault_style` first** unless you already did in this session — an
    edit has to match the form around it.

    Targeted replacement, not a rewrite: `old_text` must occur exactly once, so a
    vague match fails loudly instead of changing the wrong paragraph.

    `content_hash` is the safety catch. Get it from `list_notes(with_hash=True)`;
    if the file changed since then, the write is refused rather than silently
    overwriting someone else's edit. That hash comes from the index, so a note
    edited outside titan is refused until `ingest_note` has caught up — which is
    the point, not a defect.

    Args:
        file_path: Path to the note inside the vault.
        old_text: The exact text to replace. Must appear exactly once.
        new_text: What to put there instead.
        content_hash: The sha256 from `list_notes(with_hash=True)`.

    Returns:
        Path, commit hash and index status.
    """
    path = resolve_note_path(file_path, must_exist=True)
    state = read_note(path)

    if content_hash != state.content_hash:
        raise StaleWriteError(
            f"You passed {content_hash[:12]}…, the file is now {state.content_hash[:12]}…. "
            "Read the note again and redo the edit against the current text."
        )

    treffer = state.body.count(old_text)
    if treffer == 0:
        raise VaultWriteError("`old_text` does not occur in the note. Copy it exactly.")
    if treffer > 1:
        raise VaultWriteError(
            f"`old_text` occurs {treffer} times — that is ambiguous. Include more "
            "surrounding lines so the passage is unique."
        )

    neuer_body = state.body.replace(old_text, new_text, 1)
    meta = markiere_als_agentenarbeit(state.meta)
    path.write_text(rendere(meta, neuer_body), encoding="utf-8", newline="\n")

    commit = git_commit([path], f"vault(agent): {path.stem} bearbeitet")
    return _nach_dem_schreiben(path, commit, f"Edited **{path.name}**.")


@mcp.tool()
@_write_errors
def append_section(file_path: str, section: str) -> str:
    """Append a section to the end of an existing note.

    **Call `vault_style` first** unless you already did in this session.
    Headings like `## Offene Punkte` follow a fixed form.

    The most common real case: adding a finding without touching anything else.
    Needs no `content_hash` — appending cannot collide with an edit elsewhere in
    the file.

    Args:
        file_path: Path to the note inside the vault.
        section: Markdown to append, normally starting with a `##` heading.

    Returns:
        Path, commit hash and index status.
    """
    path = resolve_note_path(file_path, must_exist=True)
    state = read_note(path)

    neuer_body = state.body.rstrip("\n") + "\n\n" + section.strip() + "\n"
    meta = markiere_als_agentenarbeit(state.meta)
    path.write_text(rendere(meta, neuer_body), encoding="utf-8", newline="\n")

    commit = git_commit([path], f"vault(agent): Abschnitt in {path.stem} ergaenzt")
    return _nach_dem_schreiben(path, commit, f"Appended to **{path.name}**.")


@mcp.tool()
@_write_errors
def mark_verified(file_path: str, quelle: str = "gemessen") -> str:
    """Record that a note's claims were checked against reality today.

    The counterpart to the writing tools: they clear `geprueft`, this restores
    it. Use it only when the claims were actually checked — an invented date
    takes the note out of `list_stale` forever, which is worse than no date.

    Args:
        file_path: Path to the note inside the vault.
        quelle: How the content is grounded — gemessen (measured),
            recherchiert (looked up), or ueberlegt (reasoned).

    Returns:
        Path and commit hash.
    """
    if quelle not in QUELLEN or quelle == QUELLE_AGENT:
        erlaubt = ", ".join(sorted(QUELLEN - {QUELLE_AGENT}))
        raise VaultWriteError(f"`quelle` must be one of: {erlaubt} (got {quelle!r}).")

    path = resolve_note_path(file_path, must_exist=True)
    state = read_note(path)

    heute = date.today().isoformat()
    meta = dict(state.meta)
    meta["geprueft"] = heute
    meta["quelle"] = quelle
    path.write_text(rendere(meta, state.body), encoding="utf-8", newline="\n")

    commit = git_commit([path], f"vault: {path.stem} geprueft ({heute})")
    try:
        _client.ingest_file(path, force=True)
        idx = "re-indexed"
    except httpx.HTTPError:
        idx = "not re-indexed — the watcher will pick it up"
    return (
        f"**{path.name}** marked as checked on {heute} (`quelle: {quelle}`).\n\n"
        f"- commit: `{commit}`\n- index: {idx}"
    )


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------


@mcp.tool()
@_titan_errors
def delete_note(file_path: str) -> str:
    """Remove a note from the search index (de-index only).

    This deletes the note's chunks from the index. The Markdown file on disk is
    NOT touched. Use it when a note should no longer be searchable, or to clear a
    stale entry whose file was already deleted.

    Note: editing and re-ingesting a note already replaces its old chunks
    automatically — you only need delete_note() to remove a note entirely.

    Args:
        file_path: Absolute path to the note inside the vault.

    Returns:
        A short status message with the number of chunks removed.
    """
    path = Path(file_path).resolve()
    if not path.is_relative_to(settings.vault_root):
        return f"Error: {file_path!r} is outside the vault root ({settings.vault_root})."

    deleted = _client.delete_chunks(path)

    if deleted == 0:
        return f"No chunks found for {path} — it was not in the index."
    return f"De-indexed {path}: {deleted} chunk(s) removed. The file on disk was not touched."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server.

    Transport is selected via BRAIN_MCP_TRANSPORT:
    - "stdio" (default): classic subprocess transport.
    - "http": Streamable-HTTP server on BRAIN_MCP_HOST:BRAIN_MCP_PORT, so it can
      be registered as a custom connector in Claude Desktop.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if settings.mcp_transport == "http":
        read_api.register(mcp)
        log.info("Starting MCP server (http) on %s:%s", settings.mcp_host, settings.mcp_port)
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
