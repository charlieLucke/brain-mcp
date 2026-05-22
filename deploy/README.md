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
- `brain-mcp` — stellt die MCP-Tools per HTTP auf `0.0.0.0:9100` bereit

> **Bind-Adresse `0.0.0.0`, nicht `127.0.0.1`:** Im WSL2-Mirrored-Modus ist ein
> nur-loopback gebundener Dienst **von Windows aus nicht erreichbar** — und der
> Tailscale-Funnel läuft auf Windows. Mit `127.0.0.1` liefert der Funnel daher
> **502 Bad Gateway**. Zugriff bleibt durch GitHub-OAuth abgesichert. Gesetzt via
> `BRAIN_MCP_HOST=0.0.0.0` in `deploy/brain-mcp.service`.

Die Units werden als `linked` registriert — **nicht** `enabled`. Sie starten also
**nicht** automatisch beim WSL-Boot, sondern werden bewusst über das Desktop-Skript
`RAG-System.bat` gestartet und gestoppt. So lassen sich die Ressourcen (v. a.
GPU-VRAM) gezielt freigeben, wenn das System nicht gebraucht wird.

```bash
systemctl --user link ~/projects/brain-mcp/deploy/brain-watcher.service
systemctl --user link ~/projects/brain-mcp/deploy/brain-mcp.service
systemctl --user daemon-reload
systemctl --user start brain-watcher brain-mcp
systemctl --user status brain-watcher brain-mcp
```

> `titan-service` wird analog als `linked` registriert. `systemctl --user enable`
> würde Autostart einschalten — dann starten die Dienste nach jedem WSL-Boot von
> selbst wieder, auch nach einem „Stop". Daher bewusst `link` statt `enable`.

### Linger aktivieren (Pflicht)

```bash
loginctl enable-linger charl
```

Ohne Linger beendet WSL die systemd-User-Instanz (und damit **alle** laufenden
User-Dienste), sobald die letzte WSL-Sitzung endet / die Distro im Leerlauf
runterfährt. Folge: brain-mcp stirbt unbemerkt, der Funnel zeigt ins Leere, und
der Claude-Connector scheitert mit „couldn't reach"/`start_error`. Mit Linger
bleibt die User-Instanz dauerhaft aktiv.

Wichtig — kein Widerspruch zu „`linked` statt `enabled`": Linger startet beim
Boot nur **enabled** Units. Da `titan-service`/`brain-mcp`/`brain-watcher`
`linked` (nicht enabled) sind, starten sie **nicht** automatisch — ein „Stop"
fürs Zocken bleibt also bestehen. Linger hält nur *bereits laufende* Dienste am
Leben, statt sie beim Idle zu killen.

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

**502 Bad Gateway am Funnel?** Häufigste Ursache: brain-mcp bindet `127.0.0.1`
statt `0.0.0.0` (s. Abschnitt 1) — dann ist es von Windows/Funnel nicht
erreichbar. Prüfen: von Windows `iwr http://127.0.0.1:9100/mcp` → muss `401`
liefern. Schlägt das fehl, ist der Bind falsch (oder der Dienst aus). Seltener:
degradierte WSL2-Mirrored-Brücke (WSL hat nur `lo`, keine `ethX`) — Fix:
`wsl --shutdown`, dann WSL neu starten.

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
