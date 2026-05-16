# Handoff – 2026-05-16
Model: Claude Opus 4.7

## Done in this session

Claude-Anbindung von brain-mcp **vollständig umgesetzt** — OAuth + Tailscale Funnel.
Der `brain`-Connector ist in Claude live und End-to-End verifiziert.

**Code-Änderungen:**
- `src/brain_mcp/config.py` — Settings für HTTP-Transport (`mcp_transport/host/port`)
  und OAuth (`mcp_auth`, `mcp_base_url`, `github_client_id/secret`,
  `github_allowed_logins`)
- `src/brain_mcp/mcp_server.py` — HTTP-Transport in `main()`; `_build_auth()` baut bei
  `BRAIN_MCP_AUTH=github` den OAuth-Provider und übergibt ihn an `FastMCP(auth=...)`
- `src/brain_mcp/auth.py` (neu) — GitHub-OAuth-Proxy mit `GitHubAllowlistVerifier`,
  der nur erlaubte GitHub-Logins zulässt
- `deploy/brain-mcp.service` — systemd-User-Service (HTTP auf `127.0.0.1:9100`)
- `.env.example` — neue Variablen dokumentiert

**Qualitätsstand:** `ruff` + `mypy` grün, `pytest` 38 passed (Unit-Tests).

## Betriebs-Setup (läuft)

- `brain-mcp.service`: HTTP auf `127.0.0.1:9100`, `enabled` + `active`.
- Auth: GitHub-OAuth-Proxy, Allowlist = `charlievincentlucke-afk`. Konfiguration in
  `brain-mcp/.env` (gitignored): `BRAIN_MCP_AUTH=github`, `BRAIN_MCP_BASE_URL`,
  `BRAIN_GITHUB_CLIENT_ID/SECRET`, `BRAIN_GITHUB_ALLOWED_LOGINS`.
- `tailscale funnel` (persistent): `https://charliespc.taild04050.ts.net/` →
  `http://localhost:9100`. Reset: `tailscale funnel --https=443 off`.
- Claude-Connector-URL: `https://charliespc.taild04050.ts.net/mcp`.
- GitHub-OAuth-App: Callback `https://charliespc.taild04050.ts.net/auth/callback`.
- E2E verifiziert: `query_knowledge` aus Claude liefert Vault-Treffer (Score 5.71).

## Offen / Next steps

- Optional: Docker Desktop auf Windows-Autostart setzen (läuft nach Reboot sonst nicht
  → Qdrant-Container fehlt → titan-service kommt nicht hoch).

## Notes / gotchas

- Dienst-Reihenfolge: Docker Desktop → Qdrant-Container → `titan-service` → `brain-mcp`
  / `brain-watcher`. Steht die Kette nicht, geben die Tools „Titan unreachable" zurück.
- **WSL-Netzwerk:** Der Funnel (Windows-`tailscaled`) erreicht `localhost:9100` nur bei
  intakter WSL2-Mirrored-Networking-Brücke. Nach einem Reboot kann sie degradiert sein
  (WSL hat nur `lo`, keine `ethX`, keine Default-Route) → Funnel liefert **502 Bad
  Gateway**. Fix: `wsl --shutdown`, dann WSL neu starten.
- Vault-Ingest: Der Watcher nimmt nur `.md`-Dateien aus dem Vault auf; jede Note
  braucht ein Frontmatter-Feld `domain:` (sonst lehnt Titan sie ab). PDFs laufen über
  die Titan-CLI (`python -m titan.ingest`), nicht über den Watcher.

---

# Handoff – 2026-05-13
Model: Claude Sonnet 4.6

## Done in this session

Phase 2 (B0–B10) vollständig implementiert und committed auf `main`.

**Neue Dateien:**
- `src/brain_mcp/config.py` — Pydantic-Settings (BRAIN_ prefix)
- `src/brain_mcp/schemas.py` — Lokale Kopie Titan-API-Schemas
- `src/brain_mcp/titan_client.py` — TitanClient (httpx + tenacity)
- `src/brain_mcp/mcp_server.py` — FastMCP + 4 Tools
- `src/brain_mcp/watcher.py` — VaultWatcher + Reconnect-Logik
- `deploy/brain-watcher.service` — systemd User-Service
- `deploy/README.md` — Aktivierungs-Anleitung + Claude Desktop JSON
- `tests/test_titan_client.py` — httpx.MockTransport Unit-Tests
- `tests/test_mcp_tools.py` — MCP Tool Unit-Tests (patch)
- `tests/test_watcher.py` — Watcher Unit + Integration Tests
- `tests/integration/test_e2e_pipeline.py` — E2E Polling Tests

**Modifizierte Dateien:**
- `docs/ai/CONTEXT.md`, `CURRENT_TASK.md`, `DECISIONS.md` — gefüllt
- `pyproject.toml` — entry points, mypy overrides
- `.pre-commit-config.yaml` — mypy additional_dependencies

**Qualitätsstand:**
- `ruff check` → 0 Fehler
- `mypy src tests` → 0 Fehler (15 Dateien)
- `pytest` → 33 passed, 3 skipped (E2E ohne Titan)
- pre-commit → alle Hooks grün
- 1 Commit auf `main`

## In progress

Nichts offen — B0–B10 vollständig committed.

## Next concrete step

1. **B11: Audit-Runde (Opus)** — Checkliste aus Plan Abschnitt 4.13 prüfen
2. **Manuelle Aktivierung** (deploy/README.md):
   ```bash
   mkdir -p ~/.config/systemd/user/
   ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now brain-watcher
   systemctl --user status brain-watcher
   ```
3. **Claude Desktop Config** (Windows-Seite, manuell):
   - `%APPDATA%\Claude\claude_desktop_config.json` bearbeiten
   - Inhalt siehe `deploy/README.md` Abschnitt 2
   - Claude Desktop neu starten → 4 brain-Tools prüfen
4. **E2E-Test** mit echtem Titan:
   ```bash
   uv run pytest tests/integration/ -m integration -v
   ```

## Open questions / decisions needed

- **B11 Audit:** Opus sollte Checkliste aus Plan Abschnitt 4.13 prüfen, besonders:
  MCP-Tool-Descriptions, top_k-Clamp, Watcher-Exception-Handling, Pfad-Validierung
- **VAULT_ROOT korrekt?** Plan und CONTEXT.md sagen `/mnt/f/vault` — falls der Vault
  anders gemountet ist, muss `BRAIN_VAULT_ROOT` in der systemd-Unit und Claude Desktop
  Config angepasst werden.

## Files the next session must read first

1. `~/projects/titan/docs/ai/plans/plan_titan_brain_v2.md` Abschnitt 4.13 — Audit-Checkliste
2. `docs/ai/CONTEXT.md` — Stack und pitfalls
3. `src/brain_mcp/mcp_server.py` — Tool-Implementierungen
4. `src/brain_mcp/watcher.py` — Watcher + Reconnect

## Notes / gotchas discovered

- pre-commit mypy-Hook braucht zusätzliche `additional_dependencies` (pydantic, fastmcp,
  httpx, watchdog, tenacity) — ohne diese sieht er BaseModel als `Any`
- `@mcp.tool()` und tenacity `@_RETRY` sind untyped decorators in mypy 2.0 →
  pyproject.toml `disable_error_code = ["untyped-decorator", "no-any-return"]`
- `watchdog` hat keine Typstubs → `ignore_missing_imports = true`
- replace_all edit auf `# type: ignore[misc]` → `` hatte einen bug: entfernte den
  Whitespace vor `def` → Syntax-Fehler. Zukünftig: `# type: ignore` nicht mit replace_all
  entfernen, sondern gezielt pro Zeile editieren.
- VS Code zeigt "Package not installed" für alle brain-mcp deps — falsche venv (mein-projekt)
  ist im Workspace aktiv. Funktioniert alles korrekt in `.venv`.
