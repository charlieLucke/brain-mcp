# brain-mcp — Deployment

## Voraussetzungen

- WSL2 mit systemd (`/etc/wsl.conf` enthält `[boot]` / `systemd=true`)
- Titan-Service deployt und als `titan-service.service` aktiv
- Docker Desktop läuft (Qdrant-Container) — sonst kommt `titan-service` nicht hoch
- Tailscale auf dem Windows-Host, Funnel für den Node freigeschaltet
- Eine GitHub-OAuth-App (für die Connector-Authentifizierung, siehe Abschnitt 2)

---

## 1. systemd-User-Services (WSL)

brain-mcp besteht aus zwei Diensten:

- `brain-watcher` — überwacht den Vault und ingestiert geänderte Notes in Titan
- `brain-mcp` — stellt die vier MCP-Tools per HTTP auf `127.0.0.1:9100` bereit

```bash
mkdir -p ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now brain-watcher brain-mcp
systemctl --user status brain-watcher brain-mcp
```

---

## 2. Auth-Konfiguration (`.env`)

Der Server wird öffentlich erreichbar gemacht und braucht daher OAuth. Die
Konfiguration liegt in `~/projects/brain-mcp/.env` (gitignored — niemals committen):

```
BRAIN_MCP_AUTH=github
BRAIN_MCP_BASE_URL=https://charliespc.taild04050.ts.net
BRAIN_GITHUB_CLIENT_ID=Ov23li...
BRAIN_GITHUB_CLIENT_SECRET=...
BRAIN_GITHUB_ALLOWED_LOGINS=dein-github-login
```

GitHub-OAuth-App anlegen (https://github.com/settings/developers → OAuth Apps →
New OAuth App):

- **Homepage URL:** `https://charliespc.taild04050.ts.net`
- **Authorization callback URL:** `https://charliespc.taild04050.ts.net/auth/callback`

Nur GitHub-Logins aus `BRAIN_GITHUB_ALLOWED_LOGINS` werden zugelassen; alle anderen
werden bereits auf Auth-Ebene mit 401 abgewiesen.

---

## 3. Öffentlich erreichbar machen — Tailscale Funnel

Claude verbindet Custom Connectors serverseitig aus der Anthropic-Cloud; der
Endpoint muss daher öffentlich erreichbar sein. Auf dem **Windows-Host**:

```powershell
tailscale funnel --bg http://localhost:9100
tailscale funnel status
```

Das proxyt `https://charliespc.taild04050.ts.net/` → `http://localhost:9100`.

Voraussetzung: intakte WSL2-Mirrored-Networking-Brücke. Ist sie nach einem Reboot
degradiert (WSL hat nur `lo`, keine `ethX`), liefert der Funnel **502 Bad Gateway** —
Fix: `wsl --shutdown`, dann WSL neu starten.

---

## 4. Connector in Claude Desktop eintragen

Einstellungen → Connectors → „Add custom connector":

- **URL:** `https://charliespc.taild04050.ts.net/mcp`

Claude startet den OAuth-Flow → GitHub-Login (mit dem erlaubten Account) → fertig.
Danach sind die vier Tools `query_knowledge`, `list_domains`, `ingest_note`,
`find_related` verfügbar.

---

## 5. Smoke-Test

```bash
# Dienste laufen?
systemctl --user status brain-watcher brain-mcp

# Titan erreichbar?
curl localhost:8765/health

# brain-mcp lokal — OAuth-Discovery erreichbar (erwartet: 200)?
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:9100/.well-known/oauth-protected-resource/mcp

# /mcp ohne Token — erwartet: 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  http://127.0.0.1:9100/mcp
```
