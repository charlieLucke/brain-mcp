# Großer Audit: Titan-Service + brain-mcp (Phase 1 & 2)

> **Auditor:** Claude Opus 4.7
> **Datum:** 2026-05-13
> **Scope:** Repos `titan` (Branch `feat/service-layer`) und `brain-mcp` gegen Plan v2 (`plan_titan_brain_v2.md`)
> **Vorgehen:** Code-Review jeder Datei, Plan-Konformitätsprüfung, Security/Robustness-Check, Schema-Symmetrie zwischen Repos

---

## TL;DR

**Gesamtbild:** Sehr ordentliche Umsetzung. Beide Repos folgen dem Plan in Struktur, Test-Disziplin und Sicherheits-Patterns. Die Architektur-Vorgaben (Wants= statt Requires=, Test-Hooks für Debouncing, lokale Schema-Kopien, systemd auf 127.0.0.1) sind sauber realisiert.

**Aber zwei harte Bugs verhindern Produktiv-Betrieb:**

1. **B-CRIT-1 (Schema-Mismatch):** `brain-mcp.HealthResponse.colbert_dim: int` (nicht-optional) bricht jedes Mal, wenn der Titan-Service degraded antwortet — und genau im Watcher-Reconnect-Loop, wo Health-Checks alle paar Sekunden laufen.

2. **B-CRIT-2 (Watcher-Blocking):** `_ensure_titan_available` blockt den Worker-Thread für bis zu **31 Sekunden** pro Aufruf. Bei mehreren wartenden Ingests in der Queue → Minutenlange Blockaden + Endlos-Reschedule-Loop, wenn Titan länger down ist.

Beide Befunde sind nicht-trivial, weil die existierenden Tests sie nicht treffen (Mocks geben immer `colbert_dim: 1024` zurück, und der Watcher-Survives-Restart-Test wartet nur 1 Sekunde).

**Außerdem ein Konfig-Loch:**

3. **T-CRIT-1 (`VAULT_ROOT` in `.env.example` fehlt):** Wer Titan frisch aufsetzt und kein `VAULT_ROOT` exportiert, bekommt überall 400-Errors. Die Variable ist nur in `CONTEXT.md` erwähnt, nicht in der `.env.example`.

Empfehlung: Diese drei Punkte fixen, dann sind beide Repos produktionsreif. Eine weitere Audit-Runde nach dem Fix ist nicht nötig — die Fixes sind klein und gut testbar.

---

## 1. Methodik

Pro Repo geprüft:
- **Plan-Konformität:** Alle Tasks A0–A13 / B0–B11 abgehakt?
- **Code-Korrektheit:** Toter Code, unused returns, Race Conditions
- **Sicherheit:** Path-Traversal, Input-Validation, Side-Channels
- **Schema-Symmetrie:** Stimmen die Pydantic-Modelle zwischen Service und Client überein?
- **Test-Abdeckung:** Decken die Tests die Pfade ab, die im Produktiv-Betrieb wichtig werden?

Schweregrade:
- **🔴 Kritisch:** Verhindert sicheren Produktiv-Betrieb. Muss vor Aktivierung gefixt werden.
- **🟡 Mittel:** Funktional korrekt, aber Plan-Drift oder Tech-Debt. Sollte vor Phase 3 gefixt werden.
- **🟢 Niedrig:** Kosmetik, Doku, Optimierung. Kann später.
- **✅ Positiv:** Lobenswerte Umsetzung, oft besser als der Plan vorgesehen hatte.

---

## 2. Titan-Repo (Phase 1)

### 2.1 Plan-Konformität

| Plan-Task | Status | Anmerkung |
|---|---|---|
| A0 VRAM-Validierung | ✅ | `_vram_probe.py` vorhanden |
| A1 FastAPI-Skeleton + Lifespan | ✅ | `app.py` mit korrektem Lifespan-Pattern |
| A2 Pydantic-Schemas + /health | ✅ | Alle Schemas in `schemas.py`, /health im routes.py |
| A3 search-Refactor (injectables BGE-M3) | ✅ | `search(model=None, qdrant_client=None)`-Signatur |
| A4 POST /search | ✅ | Mit Latenz-Tracking |
| A5 Markdown-Reader | ✅ | `read_markdown` in `ingest.py`, mit sanitize |
| A6 POST /ingest/file + Upsert-before-Delete | ⚠️ | Funktioniert, aber Implementation hat Schwächen (s.u. T-MED-1, T-LOW-1) |
| A7 GET /domains | ✅ | Mit in-memory Counter + Voll-Scan im Lifespan |
| A8 POST /find_related | ✅ | Erster-Chunk-als-Anchor-Strategie, exclude self via must_not |
| A9 DELETE /chunks | ✅ | Mit Counter-Update |
| A10 Cache-Invalidierung | ⚠️ | Implementiert, aber an falschem Ort (s.u. T-MED-2) |
| A11 systemd-Service | ✅ | `deploy/titan-service.service` |
| A12 Integration-Tests | ✅ | 15+ Tests in `test_service.py` gegen Test-Collection |
| A13 Audit-Runde | (Gemini-Audit lief, dieser Audit) | |

### 2.2 Kritische Befunde (Titan)

#### 🔴 T-CRIT-1: `VAULT_ROOT` fehlt in `.env.example`

**Wo:** `.env.example` enthält die Variable nicht; `src/titan/service/routes.py:42` liest sie aber:
```python
VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "/mnt/f/vault")).resolve()
```

**Auswirkung:** Bei einem frischen Setup (z.B. nach `git clone` + `cp .env.example .env`) bleibt `VAULT_ROOT` auf dem Hardcode-Default `/mnt/f/vault`. Liegt der echte Vault woanders, gibt **jeder** `/ingest/file`-, `/find_related`- und `DELETE /chunks`-Aufruf 400 zurück mit „Pfad liegt außerhalb VAULT_ROOT". Der Watcher in brain-mcp läuft dann sinnlos und produziert Endlos-Errors.

**Fix:** Zeile in `.env.example` ergänzen:
```env
# Vault-Wurzel (Service akzeptiert nur Pfade darunter)
VAULT_ROOT=/mnt/f/vault
```

**Aufwand:** 1 Minute.

#### 🟡 T-MED-1: `chunks_deleted` ist eine Approximation, nicht der echte Wert

**Wo:** `src/titan/service/routes.py:222–230` (im `/ingest/file`-Handler)

**Sequenz:**
```python
state.qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
n_old = _count_chunks_for_path(file_path)
n_old_estimate = max(0, n_old - len(new_chunks))
state.qdrant_client.delete(...)
```

Der `count` läuft NACHDEM die neuen Chunks bereits in Qdrant sind. Die Subtraktion `n_old - len(new_chunks)` ergibt dann näherungsweise die Zahl der „alten Reste", die durch die folgende Delete-Operation entfernt werden.

**Wirkliches Verhalten:**

| Szenario | n_old_estimate | Tatsächlich gelöscht |
|---|---|---|
| Note hatte 5 Chunks, neue Version hat 3 | 2 | 2 (korrekt) |
| Note hatte 3 Chunks, neue Version hat 5 | 0 | 0 (kein Rest, da alle UUIDs überschrieben wurden) |
| Note hatte 5 Chunks, neue Version hat 5 (gleiche chunk_ids) | 0 | 0 (alle überschrieben via stable_uuid) |

Funktional ist das alles korrekt — kein Datenverlust, keine Duplikate. Aber: Das Pattern funktioniert nur, weil `stable_uuid(source, chunk_id)` deterministisch ist. Eine echte „Upsert-before-Delete mit run_id"-Semantik liefert in Variante 2 z.B. 3 deleted chunks (die alten 0,1,2 mit anderer Version). Aktuell zeigt das API 0.

**Warum kritisch genug für mittlere Stufe:** Die API-Doku verspricht `chunks_deleted: int` und der Client/Watcher loggt diesen Wert. Logs sind irreführend bei wachsenden Notes („0 alte Chunks ersetzt" obwohl Version komplett ausgetauscht wurde).

**Empfehlung:** Pattern auf echtes „Upsert-before-Delete with run_id" umstellen:
```python
# Vor upsert:
n_before = _count_chunks_for_path(file_path)
# upsert mit neuem run_id
state.qdrant_client.upsert(...)
# delete must_not run_id
state.qdrant_client.delete(...)
# chunks_deleted = n_before (vor upsert gezählt, gibt alte Welt-Größe an)
```

So spiegelt `chunks_deleted` die Anzahl der ersetzten Chunks der vorherigen Version wider. Alternativ: API-Beschreibung anpassen auf „Anzahl Chunks alter Versionen, die übrig waren und gelöscht wurden".

#### 🟡 T-MED-2: Cache-Invalidierung lebt im Service-Endpoint statt in `titan.search`

**Wo:** `src/titan/service/routes.py:357–386` definiert `_invalidate_cache_for_domain`.

**Plan v2 sagt explizit (Abschnitt 3.12):**
> Wichtig: Diese Logik ist in `titan.search`-Modul, nicht im Service-Endpoint. So bleibt sie testbar ohne FastAPI.

**Realisierung:** Logik ist in `titan.service.routes`. Begründung im Code-Kommentar:
```python
# Implementierungsort hier in titan.service.routes statt titan.search,
# da die Cache-Collection-Konfiguration aus state.qdrant_client kommt.
```

Das Argument hält der genaueren Betrachtung nicht stand: `qdrant_client` kann ja schon jetzt als Argument übergeben werden (s. `search()`-Signatur). Eine Funktion `invalidate_domain_cache(qdrant_client, domain)` in `titan.search` ist testbar ohne FastAPI und ohne Mocking des state-Singletons.

**Auswirkung:** Wenn man später Cache-Invalidierung auch außerhalb des Service triggern will (z.B. nach einem CLI-`titan.ingest`), muss man die Logik nachträglich verschieben. Aktuell: Plan-Drift, nicht-funktional.

**Fix:** Funktion verschieben:
```python
# src/titan/search.py
def invalidate_domain_cache(qdrant_client: Any, domain: str) -> None:
    if not CACHE_ENABLED:
        return
    try:
        qdrant_client.delete(collection_name=CACHE_COLLECTION_NAME, ...)
    except Exception as exc:
        log.warning("Cache-Invalidierung fehlgeschlagen: %s", exc)

# src/titan/service/routes.py
from titan.search import invalidate_domain_cache
invalidate_domain_cache(state.qdrant_client, domain)
```

#### 🟡 T-MED-3: `_delete_chunks_for_path` ist toter Code

**Wo:** `src/titan/service/routes.py:166–183`

Die Funktion ist definiert, gibt aber immer `return 0` zurück (Kommentar: „wird durch Caller überschrieben"). Sie wird nirgendwo aufgerufen — alle Delete-Operationen in den Handlern inlined das Qdrant-Delete direkt.

**Fix:** Funktion entfernen.

#### 🟢 T-LOW-1: `_count_chunks_for_path` macht einen sinnlosen Scroll

**Wo:** `src/titan/service/routes.py:188–207`

```python
def _count_chunks_for_path(file_path: Path) -> int:
    ...
    _, _ = state.qdrant_client.scroll(  # ← unused result
        collection_name=COLLECTION_NAME, ...
    )
    count_result = state.qdrant_client.count(...)
    return int(count_result.count)
```

Der Scroll-Call ist ein toter Netzwerk-Roundtrip. `count()` liefert ohnehin die exakte Zahl.

**Fix:** Den Scroll entfernen.

#### 🟢 T-LOW-2: `/health` macht BGE-M3-Encode bei jedem Aufruf

**Wo:** `src/titan/service/routes.py:69–80`

Jeder `/health`-Aufruf führt:
```python
out = state.bge_model.encode(["health check"], return_colbert_vecs=True, ...)
colbert_dim = len(out["colbert_vecs"][0][0])
```

Das BGE-M3-Encode kostet ~50ms GPU-Zeit. `colbert_dim` ändert sich zur Laufzeit nie — sollte einmal im Lifespan gemessen und in `state.colbert_dim` gecached werden. Wird durch B-CRIT-2 (Watcher Health-Polling) zur echten Latenz- und VRAM-Belastung im Reconnect-Loop.

**Fix:** Cache in `state`, im Lifespan füllen, im `/health` nur abrufen.

### 2.3 Positive Befunde (Titan)

- **✅ T-POS-1:** Lifespan-Pattern korrekt: GPU-Lock → BGE-M3 → Qdrant → Dimension-Check → Domain-Counter-Init. Shutdown spiegelbildlich. `contextlib.suppress` beim Lock-Close vermeidet Crashes bei Reentry.
- **✅ T-POS-2:** Path-Sicherheit konsistent: `_path_check` mit `resolve() + is_relative_to(VAULT_ROOT)` an allen drei betroffenen Endpoints. Vorbildlich.
- **✅ T-POS-3:** Pydantic-Limits passen (`max_length=10_000` auf query, `top_k` mit `ge=1, le=50`, find_related mit `le=20`).
- **✅ T-POS-4:** `find_related` mit `must_not source_path == own_path` ist genau die Anti-Self-Logik aus dem Plan.
- **✅ T-POS-5:** Test-Suite verwendet eine **separate Test-Collection** mit Random-Suffix (`titan_test_<random>`), wird im Fixture-Teardown gelöscht. Produktiv-Daten unangetastet.
- **✅ T-POS-6:** `main.py`-Dispatcher (Service-Mode + Help-Übersicht aller Sub-CLIs) ist deutlich besser als das ursprüngliche Hello-World-Template-Erbe.
- **✅ T-POS-7:** `_init_domain_counts` per Scroll mit `offset`-Paging — korrekt umgesetzt für Qdrant. Fail-soft: bei Fehler läuft der Service weiter mit leerem Counter.
- **✅ T-POS-8:** Embedding-Dimension-Check im Lifespan greift den ColBERT-1024-vs-128-Fallstrick ab. Service refused to start bei Mismatch.

---

## 3. brain-mcp-Repo (Phase 2)

### 3.1 Plan-Konformität

| Plan-Task | Status | Anmerkung |
|---|---|---|
| B0 Repo aus Template | ✅ | |
| B1 TitanClient HTTP-Wrapper | ✅ | Mit tenacity-Retries, Context Manager Support |
| B2 MCP-Server-Skeleton | ✅ | FastMCP, Module-Level Tools |
| B3 query_knowledge | ✅ | Mit top_k-Clamping (1–30), klare Error-Messages |
| B4 ingest_note | ✅ | Client-side path check vor HTTP-Call |
| B5 list_domains + find_related | ✅ | Beide implementiert |
| B6 Watcher mit Test-Hook | ✅ | `debounce_seconds` und `poll_interval` injectierbar |
| B7 Reconnect-Logik | ⚠️ | Existiert, aber blockiert zu lange (s.u. B-CRIT-2) |
| B8 systemd-Services | ✅ | `deploy/brain-watcher.service` mit `Wants=` |
| B9 Claude Desktop Config | ✅ | In `deploy/README.md` dokumentiert |
| B10 E2E-Test deterministisch | ✅ | pytest-httpserver, Polling-Pattern statt `time.sleep` |
| B11 Audit-Runde | (Gemini lief, dieser Audit) | |

### 3.2 Kritische Befunde (brain-mcp)

#### 🔴 B-CRIT-1: Schema-Mismatch in HealthResponse → Watcher crasht im Degraded-Fall

**Wo:**
- Titan: `src/titan/service/schemas.py:21` → `colbert_dim: int | None  # None wenn BGE nicht geladen`
- brain-mcp: `src/brain_mcp/schemas.py:30` → `colbert_dim: int` (nicht-optional!)

**Reproduktion:**
1. Titan-Service startet, BGE-M3 lädt nicht (z.B. GPU-Lock konfliktet, CUDA OOM)
2. Titan antwortet auf `/health` mit `{"status": "degraded", "bge_loaded": false, "colbert_dim": null, ...}`
3. `TitanClient.health()` ruft `HealthResponse.model_validate(resp.json())`
4. Pydantic-ValidationError: `colbert_dim: Input should be a valid integer, got NoneType`
5. Exception propagiert nach oben → im Watcher-Reconnect (`_ensure_titan_available`) führt das zum **falschen Fehlerpfad**: keine `httpx.ConnectError`, sondern eine ValidationError, die der `try/except httpx.ConnectError` nicht fängt → **Watcher crasht**

**Warum das nicht im Test auffällt:** Sowohl `tests/test_titan_client.py:32` als auch `tests/integration/test_e2e_pipeline.py:50` geben in ihren Mocks `colbert_dim: 1024` oder `128` zurück. Kein Test simuliert den degraded-Fall.

**Fix:** Eine Zeile in `brain-mcp/src/brain_mcp/schemas.py`:
```python
colbert_dim: int | None  # None wenn BGE nicht geladen
```

**Aufwand:** 1 Minute Code + 5 Minuten neuer Test, der `colbert_dim=None` im Mock setzt und prüft, dass `health()` nicht crasht.

#### 🔴 B-CRIT-2: Watcher-Backoff blockiert Worker-Thread bis zu 31 Sekunden pro Call

**Wo:** `src/brain_mcp/watcher.py:222–238` (`_ensure_titan_available`)

```python
for delay in (1, 2, 4, 8, 16):
    try:
        self.titan_client.health()
        return True
    except httpx.ConnectError:
        log.warning("Titan unreachable, retrying in %ds…", delay)
        if self._stop.wait(delay):
            return False
```

Wenn Titan länger nicht erreichbar ist:
- **Pro Call** dauert die Sequenz `1 + 2 + 4 + 8 + 16 = 31` Sekunden
- `_ensure_titan_available` wird sowohl in `_handle_delete` als auch in `_ingest` aufgerufen
- Im `_ingest`-Pfad: wenn `False`, wird `self._schedule(path)` aufgerufen → Pfad landet wieder in `_pending` mit aktualisiertem Timestamp → nach `debounce_seconds` (30s default) wieder versucht → wieder 31s blockiert → **Endloser Backoff-Loop, der den Worker komplett dichtmacht.**
- Wenn mehrere Pfade `pending` sind und Titan länger down ist: jeder versucht 31s → bei 5 Pfaden = 2:35 Minuten Worker-Blockade.

**Test fängt das nicht ab:** `test_watcher_survives_titan_restart` wartet nur `time.sleep(1.0)` und prüft, dass der Worker noch lebt. Bei 1s ist der Backoff-Loop erst im ersten Versuch — der Test passt zufällig.

**Was im Plan v2 stand:**
> Wenn nach 5 Versuchen immer noch tot: weiter normal arbeiten, beim nächsten Ingest-Versuch wird's neu probiert. Keinen permanenten „dead"-State setzen.

Das ist umgesetzt — aber der Plan hat nicht spezifiziert, dass die 5 Versuche INNERHALB eines einzelnen Calls passieren. Das ist Watcher-feindlich.

**Fix-Vorschlag:** Backoff-State globalisieren, nicht pro Call:

```python
class VaultWatcher:
    def __init__(self, ...):
        ...
        self._titan_dead_until: float = 0.0  # monotonic timestamp

    def _ensure_titan_available(self) -> bool:
        # Skip wenn wir kürzlich gescheitert sind (cool-down)
        if time.monotonic() < self._titan_dead_until:
            return False
        try:
            self.titan_client.health()
            self._titan_dead_until = 0.0
            return True
        except httpx.ConnectError:
            # Eine einzelne Probe pro Aufruf; bei Failure cool-down setzen
            self._titan_dead_until = time.monotonic() + 30.0
            log.warning("Titan unreachable, cooling down for 30s")
            return False
        except Exception as exc:  # ← B-CRIT-1 auch hier abfangen
            log.warning("Titan health check failed unexpectedly: %s", exc)
            self._titan_dead_until = time.monotonic() + 30.0
            return False
```

So:
- Pro Call max. 1 HTTP-Request (schnell)
- Bei Failure: 30 Sekunden Cool-down, in denen keine weiteren Probes laufen
- Andere Events können in der Zwischenzeit normal in `pending` landen
- Wenn der Service wieder oben ist: nächster Call nach Cool-down probt, erfolgreich, normal weiter

**Plus:** Schreiben eines Tests, der Titan **länger** als 1 Sekunde down hält (z.B. 35 Sekunden simulierten Ausfall mit `pytest-httpserver` der erst nach Verzögerung antwortet), und prüft dass der Watcher nicht blockiert.

#### 🟡 B-MED-1: `force`-Parameter in `ingest_note` ist toter Code

**Wo:** Tool-Description in `src/brain_mcp/mcp_server.py:81`:
> force: If True, re-index even if the file has not changed. Default False.

Der Parameter wird durch `TitanClient.ingest_file(path, force=force)` an Titan weitergereicht. **Titan ignoriert `force` komplett** — in `routes.py:ingest_file_endpoint` wird er gelesen (`req.force`), aber nirgendwo verwendet. Der Re-Ingest passiert immer, egal was `force` sagt.

**Auswirkung:** Tool-Description lügt Claude an. Claude könnte `force=True` setzen, denken es habe einen Effekt, und sich auf Garantien verlassen, die nicht existieren.

**Fix-Optionen:**
- **A (Implementieren):** Titan vergleicht File-Hash mit `payload.content_hash` der existierenden Chunks, überspringt wenn identisch. Mehr Aufwand, echte Semantik.
- **B (Entfernen):** Parameter aus Tool und Client raus, oder Doku-Hinweis „aktuell ohne Effekt, immer Re-Ingest".

Variante B mit ehrlichem Doku-Hinweis ist der kleinste Fix. Variante A in IDEAS.md parken.

#### 🟡 B-MED-2: `_should_ignore` ist potenziell zu aggressiv

**Wo:** `src/brain_mcp/watcher.py:39–41`

```python
def _should_ignore(path: Path) -> bool:
    return any(part in _IGNORE_DIRS or part.startswith(".") for part in path.parts)
```

Iteriert über **alle** Pfad-Teile — auch die oberhalb des Vault-Roots. Wenn der Vault unter einem Dotfile-Verzeichnis liegt (z.B. `/home/user/.config/myapp/vault/`), werden ALLE Notes ignoriert, weil `.config` mit `.` beginnt.

**Realistisches Risiko:** Niedrig in der aktuellen Setup-Geographie (`/mnt/f/vault`). Aber für jemanden, der den Vault unter `~/Documents/.notes/` ablegt: kaputt.

**Fix:**
```python
def _should_ignore(path: Path, vault_root: Path) -> bool:
    try:
        relative = path.relative_to(vault_root)
    except ValueError:
        return True  # Pfad gar nicht unter vault_root
    return any(part in _IGNORE_DIRS or part.startswith(".") for part in relative.parts)
```

Etwas mehr Signatur-Aufwand (`vault_root` als Argument durchreichen), aber semantisch korrekt.

#### 🟡 B-MED-3: `_handle_delete` ohne Re-Schedule bei Titan-Down

**Wo:** `src/brain_mcp/watcher.py:153–160`

```python
def _handle_delete(self, path: Path) -> None:
    ...
    if not self._ensure_titan_available():
        log.error("Titan unreachable — could not delete chunks for %s", path)
        return  # ← Delete-Event geht verloren
```

Wenn Titan beim Delete down ist, wird das Event geloggt und vergessen. Beim nächsten Watcher-Start ist die Note bereits aus dem Filesystem weg, aber ihre Chunks bleiben im Index. **Index driftet von Filesystem ab.**

**Fix:** Failed Deletes in eine zweite Queue `self._pending_deletes: set[Path]` legen, und im Worker-Loop ebenfalls verarbeiten wenn Titan wieder verfügbar ist.

Aufwand: ca. 20 Zeilen + Test. Nicht trivial, aber überschaubar.

#### 🟢 B-LOW-1: Mock-Server im E2E-Test liest echte Datei

**Wo:** `tests/integration/test_e2e_pipeline.py:55–64`

```python
def ingest(request: Request) -> Response:
    data = json.loads(request.data)
    path = data["file_path"]
    content = Path(path).read_text(encoding="utf-8")
    if "indexed: false" in content:
        ...
```

Der Mock liest das echte Datei-System für sein „indexed: false"-Verhalten. Das ist OK in pytest (alles temp), aber konzeptuell unsauber: Der Mock simuliert Titans Frontmatter-Parsing durch primitives String-Matching. Falscher positiver Treffer möglich, wenn z.B. eine Note `indexed: true` im Frontmatter hat, aber im Body über `indexed: false`-Verhalten **schreibt**.

**Fix:** Echtes Frontmatter-Parsing im Mock via `python-frontmatter`. Aufwand: 2 Zeilen.

### 3.3 Positive Befunde (brain-mcp)

- **✅ B-POS-1:** Mock-Test-Strategie ist ausgezeichnet. pytest-httpserver mit In-Memory-Chunk-Store macht E2E-Tests offline-fähig, deterministisch und schnell. Gemini hat hier sehr gute Arbeit geleistet — die Tests sind besser, als der Plan vorgesehen hatte.
- **✅ B-POS-2:** Tool-Descriptions sind präzise, verweisen aufeinander (`list_domains` als Helper vor `query_knowledge`), klären Defaults und Limits.
- **✅ B-POS-3:** `top_k`-Clamping (`min(max(1, top_k), 30)`) verhindert Token-Explosion sauber.
- **✅ B-POS-4:** Client-side `is_relative_to(vault_root)` vor jedem HTTP-Call. Doppelte Sicherheit (Server checkt auch).
- **✅ B-POS-5:** Watcher-Worker fängt `Exception` als Catch-All in `_ingest` — der Worker stirbt nicht an unerwarteten Errors. Das ist Plan-Punkt B11 erfolgreich umgesetzt.
- **✅ B-POS-6:** systemd-Unit mit `Wants=` statt `Requires=` ist genau die Plan-Vorgabe.
- **✅ B-POS-7:** `delete_chunks` ist **nicht** mit `@_RETRY` dekoriert. Korrekt — Deletes sollten nicht silent retried werden (Idempotenz mag stimmen, aber Logs wären verwirrend).
- **✅ B-POS-8:** Lokale Schema-Kopie mit erklärendem Docstring: „intentionally kept as a local copy". Genau die Plan-Empfehlung Variante 1.
- **✅ B-POS-9:** HANDOFF.md ist ausgefüllt, dokumentiert Stand und Pitfalls. Eine echte Sitzungs-zu-Sitzungs-Brücke.

---

## 4. Konsolidierte Fix-Liste

In strikter Reihenfolge nach Schweregrad. Geschätzte Gesamt-Aufwand: 2–3 Stunden Code + Tests.

### Sofort (vor Produktiv-Aktivierung)

1. **T-CRIT-1:** `VAULT_ROOT=/mnt/f/vault` in `titan/.env.example` ergänzen. (1 min)
2. **B-CRIT-1:** `colbert_dim: int | None` in `brain-mcp/src/brain_mcp/schemas.py`. (1 min) Plus Test mit `colbert_dim=None`-Mock. (5 min)
3. **B-CRIT-2:** `_ensure_titan_available` umbauen auf Cool-down-State statt Pro-Call-Backoff. Plus Test mit ausgedehntem Ausfall. (30 min)

Nach diesen drei Fixes ist das System produktiv aktivierbar.

### Vor Phase 3

4. **T-MED-1:** Upsert-before-Delete-Count auf „n_before" umstellen oder API-Doku ehrlich machen. (15 min)
5. **T-MED-2:** `_invalidate_cache_for_domain` nach `titan.search` verschieben. (15 min)
6. **T-MED-3:** Toten Code `_delete_chunks_for_path` entfernen. (1 min)
7. **B-MED-1:** `force`-Parameter klären: implementieren oder Doku-Hinweis. (5 min für Doku, 1 h für Implementation)
8. **B-MED-2:** `_should_ignore` relativ zum Vault-Root prüfen. (10 min)
9. **B-MED-3:** Failed-Delete-Queue im Watcher. (20 min + Test)

### Wenn Zeit ist

10. **T-LOW-1:** Sinnloser Scroll in `_count_chunks_for_path` raus. (1 min)
11. **T-LOW-2:** `/health`-Endpoint cached `colbert_dim`. (10 min)
12. **B-LOW-1:** Mock-Server nutzt echtes Frontmatter-Parsing. (5 min)

### Doku-Nachträge

13. ADR in `titan/docs/ai/DECISIONS.md`: „Cache-Invalidierung bei Re-Ingest" — was, warum, Aggressivitäts-Trade-off.
14. ADR in `titan/docs/ai/DECISIONS.md`: „Service nur 127.0.0.1, kein Remote-Zugriff" — bewusste Härtung.
15. README in `brain-mcp` ergänzen: Aktivierungs-Anleitung in Repo-Root sichtbar machen (aktuell nur in `deploy/README.md`).

---

## 5. Was komplett fehlt vs. Plan v2

Bei aller Plan-Konformität: zwei Punkte sind im Plan vorgesehen, aber im Code nicht klar erkennbar:

1. **`VRAM_MODE=strict|relaxed`-Config-Switch** (Plan Abschnitt 3.3): Sollte als Fallback existieren, falls A0-Probe ergibt, dass BGE-M3 + Phi-4 nicht parallel passen. Im Code: keine Spur. Eventuell hat die A0-Probe gezeigt, dass es überall klappt, und der Switch wurde weggelassen. Wenn ja: in `DECISIONS.md` festhalten.

2. **`adr_status: accepted` Frontmatter-Konvention** (Plan Abschnitt 9): Beispiel-Frontmatter für Projekt-ADRs. Markdown-Reader akzeptiert beliebige Frontmatter-Felder, das ist kein Bug. Aber im `.env.example` oder `CONTEXT.md` könnte die Konvention dokumentiert sein — habe ich nicht gefunden.

Beides nicht-kritisch.

---

## 6. Sicherheits-Bewertung

| Vektor | Status | Anmerkung |
|---|---|---|
| Path-Traversal | ✅ | Doppelt geschützt (Client + Server), `is_relative_to` mit `resolve()` |
| Prompt-Injection via Frontmatter | ✅ | `sanitize()` wird auf `domain`-Feld angewendet vor Payload-Insert |
| Externe Erreichbarkeit | ✅ | uvicorn auf 127.0.0.1, systemd ohne Bind-Address-Erweiterung |
| API-Key-Leakage in Logs | ✅ | Keine Spuren in geprüften Log-Statements |
| Untrusted Input in HTTP-Body | ✅ | Pydantic-Validation greift vor dem Handler |
| Massenhafte Anfragen (DoS) | ⚠️ | Kein Rate-Limit. Akzeptabel für Single-User-Setup auf 127.0.0.1, würde bei Multi-User/Public kritisch. |
| Sensitives in `/health` | 🟡 | `vram_used_mb` und `collection_name` leaked Setup-Details. In Single-User-Setup OK. |

Empfehlung: Plan-konformes Härtungsniveau erreicht. Wenn der Service jemals hinter einen Reverse-Proxy gestellt wird, muss zusätzlich überlegt werden: Auth-Header, Rate-Limit, `/health`-Detail-Reduktion.

---

## 7. Abschließende Bewertung

**Code-Qualität:** Hoch. Type-Hints durchgängig, Docstrings präzise, Modulgrenzen sauber. Tests folgen Mocking-Best-Practices.

**Plan-Treue:** ~93%. Drei Plan-Drifts: Cache-Invalidierung-Ort (T-MED-2), `chunks_deleted`-Semantik (T-MED-1), VRAM_MODE-Switch (fehlt). Alle drei beheb-/erklärbar in einer Sitzung.

**Sicherheitsniveau:** Plan-Vorgaben erfüllt. Single-User-Setup auf 127.0.0.1 ist ausreichend gehärtet.

**Robustness:** Hier sitzen die zwei harten Bugs (B-CRIT-1, B-CRIT-2). Nach Fix: produktionsreif.

**Test-Disziplin:** Sehr gut. Mock-Server-Pattern (Gemini) hebt die E2E-Tests auf ein Niveau, das im ursprünglichen Plan nicht spezifiziert war. Einzige Lücke: degraded-State und langer Titan-Ausfall sind nicht abgedeckt — beides direkt mit den B-CRIT-Fixes nachholbar.

**Nächster Schritt:** Die drei CRIT-Fixes (15 Minuten Code + 35 Minuten Test) implementieren, dann manuelle Aktivierung gemäß `brain-mcp/deploy/README.md`. Danach kann das System in Produktivbetrieb.

---

*Audit durchgeführt am 2026-05-13 durch Claude Opus 4.7. Bei Fragen zu einzelnen Befunden: HANDOFF in der jeweiligen Sitzung referenzieren.*
