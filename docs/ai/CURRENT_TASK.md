# Current Task

> Keep this short. One screen max. Update as you progress.

## Goal

System produktiv. Offen: Anbindung von brain-mcp an Claude.

## Status

- [x] Phase 2 (B0–B11): brain-mcp implementiert + auditiert
- [x] `brain-watcher.service` läuft (systemd User-Service)
- [x] HTTP-Transport ergänzt (`BRAIN_MCP_TRANSPORT=http`); `brain-mcp.service` läuft
      als HTTP auf `127.0.0.1:9100` (enabled + active)
- [ ] Claude-Anbindung — VERTAGT. Weg: `tailscale funnel` + Auth-Schicht.
      Siehe `docs/ai/DECISIONS.md` + `HANDOFF.md` (2026-05-16).

## Nächste Schritte (für die Claude-Anbindung)

1. OAuth-Auth-Schicht in brain-mcp einbauen (Pflicht vor Internet-Exposition)
2. `tailscale funnel` aktivieren, Connector in Claude Desktop eintragen
3. `deploy/README.md` aktualisieren

## Notes

- Custom Connectors verbindet Anthropic serverseitig → der MCP-Endpoint muss öffentlich
  erreichbar sein; rein lokale / tailnet-private Lösungen scheiden aus.
- brain-mcp läuft sowohl per stdio (Default) als auch als HTTP-Daemon.
- Noch uncommitted/ungetrackt: `src/brain_mcp/watcher.py` (PollingObserver-Fix),
  `docs/ai/plans/audit_phase1_und_2.md`.
