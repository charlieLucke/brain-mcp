# Current Task

> Keep this short. One screen max. Update as you progress.

## Goal

Phase 2: brain-mcp vollständig implementiert (B0–B10).
Plan: `~/projects/titan/docs/ai/plans/plan_titan_brain_v2.md`
Branch: `main`

## Sub-steps

- [x] B0: Repo aus `charlievincentlucke-afk/python-template` erstellt, deps installiert
- [x] B1: `titan_client.py` — TitanClient mit httpx + tenacity retry
- [x] B2: `mcp_server.py` — FastMCP Skeleton
- [x] B3: Tool `query_knowledge` — sucht im Vault, clamped top_k ≤ 30
- [x] B4: Tool `ingest_note` — sofortiger Re-Ingest mit Pfad-Check
- [x] B5: Tools `list_domains` + `find_related`
- [x] B6: `watcher.py` — VaultWatcher mit injectablem debounce (Test-Hook)
- [x] B7: Reconnect-Logik mit exp. Backoff (1s/2s/4s/8s/16s)
- [x] B8: `deploy/brain-watcher.service` + `deploy/README.md` (inkl. Claude Desktop Config)
- [x] B10: Tests: unit (mock), integration (watchdog), E2E (polling, kein sleep)
- [ ] B11: Audit-Runde (Opus) — noch ausstehend
- [ ] Manuelle Schritte: systemd aktivieren, Claude Desktop Config setzen, E2E-Test mit echtem Titan

## Status

**B0–B10 implementiert, committed.** ruff + mypy + 33 Tests grün.
Nächster Schritt: manuelle Aktivierung (deploy/README.md) + B11 Audit.

## Notes

- brain-mcp läuft per stdio, kein systemd-Daemon
- `BRAIN_DEBOUNCE_SECONDS` ist injectable (Tests nutzen 0.1s)
- Schemas sind lokale Kopie (nicht von titan importiert)
