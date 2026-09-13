# Übergabe – 2026-05-22
Modell: Claude Opus 4.7

## In dieser Sitzung erledigt

**Connector-Ausfall behoben — die Ursache war die Infrastruktur, nicht der OAuth-Code.**
Nach einem PC-Neustart scheiterte der Custom Connector mit „couldn't reach" / `start_error`.
OAuth-Code lokal verifiziert (`/mcp`→401, Discovery→200, `POST /register`→201).
Zwei reale Ursachen gefunden und behoben:

1. **`Linger=no`** → systemd-User-Services sterben, sobald WSL in den Leerlauf geht → brain-mcp
   weg → Funnel zeigt ins Leere. Fix: `loginctl enable-linger charl` (persistent).
2. **`BRAIN_MCP_HOST=127.0.0.1`** → unter WSL2 Mirrored Networking von
   Windows/Funnel unerreichbar (502). Fix: `BRAIN_MCP_HOST=0.0.0.0` in `deploy/brain-mcp.service`.
   Beweis: Dashboard (`0.0.0.0:9200`) von Windows = 200, brain-mcp (`127.0.0.1:9100`)
   = unerreichbar; nach `0.0.0.0` → Funnel 401.

Außerdem: `BRAIN_GITHUB_ALLOWED_LOGINS` auf `charlieLucke` aktualisiert (GitHub-Rename), fastmcp
testweise auf 3.2.4 zurück- und wieder auf lock-konsistentes 3.3.1 gerollt (nicht die Ursache).
Docs aktualisiert (deploy/README, DECISIONS, CONTEXT, diese Übergabe). **End-to-end verifiziert:
der Connector verbindet wieder, brain-Tools live.**

## Betriebliches Setup (Stand heute)

- brain-mcp: HTTP auf `0.0.0.0:9100`, Linger aktiv → Services bleiben laufend.
- Connector-URL unverändert: `https://<your-tailnet-host>.ts.net/mcp`.
- „`linked` statt `enabled`" gilt weiterhin — ein Stop fürs Gaming bleibt in Kraft;
  Linger killt nur nicht mehr Services im Leerlauf.

## Offen / Nächste Schritte

- Docker Desktop war zuletzt aus → qdrant/titan unten; für echte Queries den RAG-
  Stack hochfahren (Docker Desktop → qdrant → titan). Optional: Docker-Autostart.

---

# Übergabe – 2026-05-17
Modell: Claude Opus 4.7

## In dieser Sitzung erledigt

**Stage 2 — vault-admin.** Zwei neue MCP-Tools im `brain`-Server (jetzt 6 Tools).

**Code-Änderungen:**
- `src/brain_mcp/schemas.py` — neue Schemas `NoteInfo`, `NotesResponse`
- `src/brain_mcp/titan_client.py` — `TitanClient.list_notes()` (GET /notes)
- `src/brain_mcp/mcp_server.py` — neue Tools `list_notes` (alle indexierten Notizen,
  optionaler Domain-Filter) und `delete_note` (eine Notiz aus dem Index entfernen, nur de-indexieren
  — die `.md`-Datei bleibt); `ingest_note`-Docstring präzisiert (Re-Ingest ersetzt immer
  alte Chunks)
- `tests/test_titan_client.py`, `tests/test_mcp_tools.py` — Tests für beide

**Gegenstück im titan-Repo:** neuer Endpunkt `GET /notes` — siehe titan `docs/ai/`
(2026-05-17).

**Quality-Status:** `ruff` + `mypy --strict` grün, `pytest` 52 passed.

## Betriebliches Setup

`titan-service` und `brain-mcp` wurden neu gestartet — die zwei neuen Tools sind im
Connector live. Ansonsten unverändert (siehe Übergabe 2026-05-16).

## Kontext: brain-dashboard

Parallel wurde das neue Repo `~/projects/brain-dashboard` erstellt — ein Web-Control-
Panel (Port 9200) für Status, Logs und Steuerung des RAG-Systems. Eigenes Repo mit
eigenem `docs/ai/`. Läuft als `enabled` systemd-User-Unit.

## Offen / Nächste Schritte

- Keine offenen Punkte aus Stage 2.

---

# Übergabe – 2026-05-16
Modell: Claude Opus 4.7

## In dieser Sitzung erledigt

Claude-Integration von brain-mcp **vollständig implementiert** — OAuth + Tailscale Funnel.
Der `brain`-Connector ist in Claude live und end-to-end verifiziert.

**Code-Änderungen:**
- `src/brain_mcp/config.py` — Settings für HTTP-Transport (`mcp_transport/host/port`)
  und OAuth (`mcp_auth`, `mcp_base_url`, `github_client_id/secret`,
  `github_allowed_logins`)
- `src/brain_mcp/mcp_server.py` — HTTP-Transport in `main()`; `_build_auth()` baut
  den OAuth-Provider, wenn `BRAIN_MCP_AUTH=github`, und übergibt ihn an `FastMCP(auth=...)`
- `src/brain_mcp/auth.py` (neu) — GitHub-OAuth-Proxy mit `GitHubAllowlistVerifier`,
  der nur erlaubte GitHub-Logins zulässt
- `deploy/brain-mcp.service` — systemd-User-Service (HTTP auf `127.0.0.1:9100`)
- `.env.example` — neue Variablen dokumentiert

**Quality-Status:** `ruff` + `mypy` grün, `pytest` 38 passed (Unit-Tests).

## Betriebliches Setup (laufend)

- `brain-mcp.service`: HTTP auf `127.0.0.1:9100`. Die Units (`titan-service`,
  `brain-mcp`, `brain-watcher`) sind `linked` — **kein** Autostart. Start/Stopp laufen über
  das Desktop-Skript `RAG-System.bat` (siehe DECISIONS.md 2026-05-16).
- Auth: GitHub-OAuth-Proxy, Allowlist = `charlieLucke`. Konfiguration in
  `brain-mcp/.env` (gitignored): `BRAIN_MCP_AUTH=github`, `BRAIN_MCP_BASE_URL`,
  `BRAIN_GITHUB_CLIENT_ID/SECRET`, `BRAIN_GITHUB_ALLOWED_LOGINS`.
- `tailscale funnel` (persistent): `https://<your-tailnet-host>.ts.net/` →
  `http://localhost:9100`. Reset: `tailscale funnel --https=443 off`.
- Claude-Connector-URL: `https://<your-tailnet-host>.ts.net/mcp`.
- GitHub-OAuth-App: Callback `https://<your-tailnet-host>.ts.net/auth/callback`.
- E2E verifiziert: `query_knowledge` aus Claude liefert Vault-Treffer (Score 5,71).

## Offen / Nächste Schritte

- Optional: Docker Desktop unter Windows auf Autostart setzen (sonst läuft es nach
  einem Reboot nicht → Qdrant-Container fehlt → titan-service startet nicht).

## Notizen / Stolperfallen

- Service-Reihenfolge: Docker Desktop → Qdrant-Container → `titan-service` → `brain-mcp`
  / `brain-watcher`. Ist die Kette nicht oben, liefern die Tools „Titan unreachable".
- **WSL-Networking:** die Funnel (Windows `tailscaled`) erreicht `localhost:9100` nur
  mit intakter WSL2-Mirrored-Networking-Bridge. Nach einem Reboot kann sie degradiert
  sein (WSL hat nur `lo`, kein `ethX`, keine Default-Route) → Funnel liefert **502 Bad
  Gateway**. Fix: `wsl --shutdown`, dann WSL neu starten.
- Vault-Ingest: der Watcher nimmt nur `.md`-Dateien aus dem Vault auf; jede Notiz braucht
  ein Frontmatter-Feld `domain:` (sonst weist Titan sie ab). PDFs laufen über die
  Titan-CLI (`python -m titan.ingest`), nicht über den Watcher.

---

# Übergabe – 2026-05-13
Modell: Claude Sonnet 4.6

## In dieser Sitzung erledigt

Phase 2 (B0–B10) vollständig implementiert und nach `main` committet.

**Neue Dateien:**
- `src/brain_mcp/config.py` — Pydantic-Settings (BRAIN_-Präfix)
- `src/brain_mcp/schemas.py` — lokale Kopie der Titan-API-Schemas
- `src/brain_mcp/titan_client.py` — TitanClient (httpx + tenacity)
- `src/brain_mcp/mcp_server.py` — FastMCP + 4 Tools
- `src/brain_mcp/watcher.py` — VaultWatcher + Reconnect-Logik
- `deploy/brain-watcher.service` — systemd-User-Service
- `deploy/README.md` — Aktivierungsanleitung + Claude-Desktop-JSON
- `tests/test_titan_client.py` — httpx.MockTransport-Unit-Tests
- `tests/test_mcp_tools.py` — MCP-Tool-Unit-Tests (patch)
- `tests/test_watcher.py` — Watcher-Unit- + Integrationstests
- `tests/integration/test_e2e_pipeline.py` — E2E-Polling-Tests

**Geänderte Dateien:**
- `docs/ai/CONTEXT.md`, `CURRENT_TASK.md`, `DECISIONS.md` — befüllt
- `pyproject.toml` — Entry Points, mypy-Overrides
- `.pre-commit-config.yaml` — mypy additional_dependencies

**Quality-Status:**
- `ruff check` → 0 Fehler
- `mypy src tests` → 0 Fehler (15 Dateien)
- `pytest` → 33 passed, 3 skipped (E2E ohne Titan)
- pre-commit → alle Hooks grün
- 1 Commit auf `main`

## In Arbeit

Nichts offen — B0–B10 vollständig committet.

## Nächster konkreter Schritt

1. **B11: Audit-Runde (Opus)** — die Checkliste aus Plan-Abschnitt 4.13 prüfen
2. **Manuelle Aktivierung** (deploy/README.md):
   ```bash
   mkdir -p ~/.config/systemd/user/
   ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now brain-watcher
   systemctl --user status brain-watcher
   ```
3. **Claude-Desktop-Konfiguration** (Windows-Seite, manuell):
   - `%APPDATA%\Claude\claude_desktop_config.json` bearbeiten
   - Inhalt siehe `deploy/README.md` Abschnitt 2
   - Claude Desktop neu starten → die 4 brain-Tools prüfen
4. **E2E-Test** mit einem echten Titan:
   ```bash
   uv run pytest tests/integration/ -m integration -v
   ```

## Offene Fragen / nötige Entscheidungen

- **B11-Audit:** Opus sollte die Checkliste aus Plan-Abschnitt 4.13 prüfen, besonders:
  MCP-Tool-Beschreibungen, top_k-Clamp, Watcher-Exception-Handling, Pfadvalidierung
- **VAULT_ROOT korrekt?** Plan und CONTEXT.md sagen `/mnt/f/vault` — ist der Vault
  woanders gemountet, müssen `BRAIN_VAULT_ROOT` in der systemd-Unit und der Claude-Desktop-Konfiguration
  angepasst werden.

## Dateien, die die nächste Sitzung zuerst lesen muss

1. `~/projects/titan/docs/ai/plans/plan_titan_brain_v2.md` Abschnitt 4.13 — Audit-Checkliste
2. `docs/ai/CONTEXT.md` — Stack und Fallstricke
3. `src/brain_mcp/mcp_server.py` — Tool-Implementierungen
4. `src/brain_mcp/watcher.py` — Watcher + Reconnect

## Notizen / entdeckte Stolperfallen

- Der pre-commit mypy-Hook braucht zusätzliche `additional_dependencies` (pydantic, fastmcp,
  httpx, watchdog, tenacity) — ohne sie sieht er BaseModel als `Any`
- `@mcp.tool()` und tenacity `@_RETRY` sind in mypy 2.0 untypisierte Dekoratoren →
  pyproject.toml `disable_error_code = ["untyped-decorator", "no-any-return"]`
- `watchdog` hat keine Type-Stubs → `ignore_missing_imports = true`
- Ein replace_all-Edit auf `# type: ignore[misc]` → `` hatte einen Bug: er entfernte das
  Whitespace vor `def` → Syntaxfehler. Künftig: `# type: ignore` nicht mit replace_all
  entfernen; stattdessen pro Zeile editieren.
- VS Code zeigt „Package not installed" für alle brain-mcp-Deps — das falsche venv
  (mein-projekt) ist im Workspace aktiv. In `.venv` funktioniert alles korrekt.
