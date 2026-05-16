# Decisions Log

> Architecture Decision Records. Append-only. One entry per significant decision.
> This prevents re-litigating the same questions in every new AI session.

---

## 2026-05-13: Schemas als lokale Kopie (nicht von titan importiert)

**Decision:** `brain_mcp/schemas.py` enthält eine lokale Kopie der Titan-API-Schemas,
nicht einen Import aus dem `titan`-Package.
**Reasoning:** brain-mcp soll von titan entkoppelt sein — nur über HTTP-Schnittstelle verbunden.
Cross-Repo-Import (`brain_mcp` importiert `titan`) würde titan als Python-Dependency ziehen
und beide Repos in Lock-Step halten.
**Alternatives considered:** Geteiltes `titan-schemas`-Package (drittes Repo) — zu viel Overhead
für sieben Schemas.
**Consequences:** Bei API-Änderungen beide Seiten manuell synchronisieren. Wenn Schemas
stark divergieren wollen: zu diesem Zeitpunkt `titan-schemas` extrahieren.

## 2026-05-13: brain-mcp läuft nicht als Daemon (per-Session stdio)

**Decision:** brain-mcp wird von Claude Desktop als Subprocess gestartet (stdio transport),
kein systemd-Service.
**Reasoning:** MCP stdio-Transport ist per-Session — Claude Desktop managed den Lifecycle.
Ein systemd-Daemon wäre hier falsch, da MCP nicht dauerhaft lauschen muss.
**Consequences:** `deploy/` enthält nur `brain-watcher.service`. brain-mcp hat keinen
systemd-Unit. Deployment = Binary in `.venv/bin/brain-mcp` + JSON-Eintrag in Claude Desktop.

## 2026-05-13: Wants= statt Requires= im systemd-Unit

**Decision:** `brain-watcher.service` nutzt `Wants=titan-service.service`, nicht `Requires=`.
**Reasoning:** Mit `Requires=` würde brain-watcher bei Titan-Restart mitgekillt. Die
Reconnect-Logik im Watcher macht `Wants=` sicher: Watcher wartet mit exp. Backoff bis
Titan wieder erreichbar ist.
**Consequences:** Watcher überlebt Titan-Restarts. Watcher überleben auch wenn Titan gar
nicht läuft beim Watcher-Start (events bleiben im pending-Dict bis Titan zurückkommt).

## 2026-05-13: use_decompose=False als MCP-Default

**Decision:** `query_knowledge` übergibt `use_decompose=False` an titan.search.
**Reasoning:** Wie in Plan Abschnitt 7 beschrieben: Claude (Opus/Sonnet) kann Query-Decomposition
selbst. Phi-4-Decompose im Service wäre doppelter Aufwand und zusätzliche Latenz.
**Consequences:** CLI-Pfad (`python -m titan.search`) nutzt weiterhin `use_decompose=True` als
Default. Nur der MCP-Pfad setzt False.

## 2026-05-13: Cool-down statt Pro-Call-Backoff in _ensure_titan_available

**Decision:** `_ensure_titan_available` macht genau eine health()-Probe pro Aufruf.
Bei Failure wird ein 30-Sekunden-Cool-down als `self._titan_dead_until` gesetzt;
während des Cool-downs kehren alle weiteren Aufrufe sofort mit `False` zurück.
**Reasoning:** Audit B-CRIT-2: Der alte Backoff (1+2+4+8+16 = 31 s pro Call) blockierte
den Worker-Thread minutenlang wenn mehrere Events pending waren und Titan down war.
Außerdem wurde jeder Unexpected-Error (z.B. ValidationError bei degraded-Response)
nicht gefangen — Watcher-Crash.
**Consequences:** Worker ist während des Cool-downs nicht blockiert. Events landen weiter
in `_pending` und werden nach Cool-down-Ablauf normal verarbeitet.

## 2026-05-13: Failed-Delete-Queue (_pending_deletes)

**Decision:** Wenn Titan beim Delete-Event down ist, wandert der Pfad in `self._pending_deletes`.
Der Worker-Loop verarbeitet die Queue bei jedem Tick — sobald Titan wieder erreichbar ist.
**Reasoning:** Audit B-MED-3: Ohne Queue gingen Delete-Events verloren wenn Titan gerade
neustartet. Der Index driftete vom Filesystem ab (gelöschte Notes blieben indexiert).
**Consequences:** Deletes werden maximal um einen Cool-down-Zyklus (30s) verzögert.
Bei langem Titan-Ausfall bleiben sie in der Queue und werden nach Recovery abgearbeitet.

## 2026-05-13: Debounce-Sekunden als injectables Setting

**Decision:** `VaultWatcher.__init__` akzeptiert `debounce_seconds: float` als Parameter.
`config.py` exponiert `BRAIN_DEBOUNCE_SECONDS` (Default 30.0).
**Reasoning:** Tests brauchen 0.1s Debounce damit sie in <2s durchlaufen. Production nutzt 30s.
Kein `time.sleep(35)` in Tests (war Sonnet-Befund aus Plan v1).
**Consequences:** E2E-Fixtures können `debounce_seconds=0.1` setzen. systemd-Unit setzt
`BRAIN_DEBOUNCE_SECONDS=30` via Environment.

## 2026-05-16: brain-mcp als HTTP-Daemon; Claude-Anbindung via Funnel + Auth (offen)

**Decision:** brain-mcp kann per `BRAIN_MCP_TRANSPORT=http` als dauerhafter
Streamable-HTTP-Server laufen (Default bleibt `stdio`). Der neue systemd-User-Service
`deploy/brain-mcp.service` betreibt ihn als reinen HTTP-Server auf `127.0.0.1:9100`.
Für die Anbindung an Claude ist **Tailscale Funnel + eine Auth-Schicht (OAuth)**
vorgesehen — dieser Teil ist Stand 2026-05-16 aber **noch nicht umgesetzt** (vertagt).
**Reasoning:** Der installierte Claude-Desktop-Build (intern „epitaxy"/Cowork-Build)
hat keinen Developer Mode und behandelt `claude_desktop_config.json` ausschließlich als
Präferenzen-Datei — ein manuell eingetragener `mcpServers`-Block wird ignoriert und beim
nächsten Speichern der App wieder entfernt. Der klassische stdio-Weg (Decision
2026-05-13) ist mit diesem Build also nicht nutzbar; der einzige verbleibende Weg ist
ein *Custom Connector*. Laut Anthropic-Doku verbindet Claude einen Custom Connector aber
**serverseitig aus der Anthropic-Cloud** (gilt für claude.ai, Desktop, Cowork, Mobile) —
der MCP-Endpoint muss daher **öffentlich aus dem Internet erreichbar** sein. Eine rein
lokale oder tailnet-private Lösung kann prinzipiell nicht funktionieren.
**Alternatives considered:**
- stdio über `claude_desktop_config.json` — von diesem Build nicht unterstützt (s.o.).
- `tailscale serve` (tailnet-privat, gültiges HTTPS-Zertifikat) — getestet, funktioniert
  NICHT: Anthropics Cloud ist nicht im Tailnet, am Server kam keine einzige Anfrage an.
  Wurde wieder entfernt (`tailscale serve --https=443 off`).
- Packaging als `.mcpb`-Extension — das Bundle müsste `wsl.exe` aufrufen (Server lebt in
  WSL, Claude Desktop unter Windows); umständlich und fragil.
- brain-mcp in Claude Codes MCP-Config (lokal, sicher, keine Exposition) — nur in
  Claude-Code-Sessions verfügbar, nicht im normalen Claude-Desktop-Chat. Bleibt als
  Fallback möglich.
**Consequences:**
- Diese Entscheidung **ersetzt** die Decision vom 2026-05-13 („brain-mcp läuft nicht als
  Daemon"). stdio bleibt als Default erhalten (andere MCP-Clients, lokale Tests), aber
  für die Claude-Anbindung läuft brain-mcp als Daemon.
- `deploy/` enthält jetzt zwei Units: `brain-watcher.service` und `brain-mcp.service`.
- `config.py` hat neue Settings: `mcp_transport`, `mcp_host`, `mcp_port`
  (Env: `BRAIN_MCP_TRANSPORT` / `BRAIN_MCP_HOST` / `BRAIN_MCP_PORT`).
- **Offen / TODO vor Inbetriebnahme des Connectors:**
  1. Auth-Schicht (OAuth) in brain-mcp einbauen — ein öffentlich erreichbarer,
     unauthentifizierter Vault-Server darf NICHT ins Internet.
  2. Erst danach `tailscale funnel` für `127.0.0.1:9100` aktivieren.
  3. Connector in Claude Desktop mit der Funnel-URL eintragen.
  4. `deploy/README.md` (Abschnitt Claude Desktop) auf diesen Weg aktualisieren.
- Erreichbarkeit Windows↔WSL (für lokale Tests / `tailscale` auf Windows → `localhost`
  in WSL) läuft über WSL2 Mirrored Networking — siehe titan `docs/ai/DECISIONS.md`
  (2026-05-16).
