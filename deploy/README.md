# brain-mcp — Deployment

> **Platzhalter:** `<your-user>` ist dein Linux-Benutzername, `<your-tailnet-host>.ts.net`
> ist dein Tailscale-Funnel-Hostname, `<your-github-login>` ist das GitHub-Konto,
> das sich verbinden darf. Ersetze sie durch deine eigenen (der Host des Autors ist
> beispielsweise `<your-tailnet-host>.ts.net`).
>
> Diese Anleitung beschreibt das **WSL2**-Deployment des Autors, das brain-mcp als
> öffentlichen Claude-Custom-Connector exponiert. brain-mcp selbst läuft auf jedem Linux,
> und für lokale Nutzung kannst du die Abschnitte 2–4 komplett überspringen und es
> stattdessen im `stdio`-Transport betreiben (keine Funnel, kein OAuth). Das unten
> referenzierte `RAG-System.bat` ist das Windows-Start/Stopp-Skript des Autors —
> optional, nicht erforderlich.

## Voraussetzungen

- WSL2 mit systemd (`/etc/wsl.conf` enthält `[boot]` / `systemd=true`)
- Der Titan-Service deployt und laufend als `titan-service.service`
- Docker Desktop laufend (der Qdrant-Container) — sonst startet `titan-service` nicht
- Tailscale auf dem Windows-Host, mit aktivierter Funnel für den Node
- Eine GitHub-OAuth-App (für die Connector-Authentifizierung, siehe Abschnitt 2)

---

## 1. systemd-User-Services (WSL)

brain-mcp besteht aus zwei Services:

- `brain-watcher` — überwacht den Vault und ingestet geänderte Notizen in Titan
- `brain-mcp` — stellt die MCP-Tools über HTTP auf `0.0.0.0:9100` bereit

> **Bind-Adresse `0.0.0.0`, nicht `127.0.0.1`:** unter WSL2 Mirrored Networking ist ein
> reiner Loopback-Service **von Windows aus unerreichbar** — und die Tailscale-Funnel
> läuft auf Windows. Mit `127.0.0.1` liefert die Funnel daher **502 Bad
> Gateway**. Der Zugriff bleibt durch GitHub-OAuth geschützt. Gesetzt über
> `BRAIN_MCP_HOST=0.0.0.0` in `deploy/brain-mcp.service`.

Die Units sind als `linked` registriert — **nicht** als `enabled`. Sie starten daher **nicht**
automatisch beim WSL-Boot; sie werden bewusst über das Desktop-Skript `RAG-System.bat`
gestartet und gestoppt. So lassen sich Ressourcen freigeben (vor allem GPU-
VRAM), wenn das System nicht gebraucht wird.

```bash
systemctl --user link ~/projects/brain-mcp/deploy/brain-watcher.service
systemctl --user link ~/projects/brain-mcp/deploy/brain-mcp.service
systemctl --user daemon-reload
systemctl --user start brain-watcher brain-mcp
systemctl --user status brain-watcher brain-mcp
```

> `titan-service` ist auf dieselbe Weise als `linked` registriert. `systemctl --user enable`
> würde Autostart einschalten — dann kämen die Services nach jedem WSL-Boot von selbst
> wieder hoch, selbst nach einem „Stop". Daher bewusst `link` statt `enable`.

### Linger aktivieren (erforderlich)

```bash
loginctl enable-linger <your-user>
```

Ohne Linger beendet WSL die systemd-User-Instanz (und mit ihr **alle**
laufenden User-Services), sobald die letzte WSL-Sitzung endet / die Distro im Leerlauf
herunterfährt. Folge: brain-mcp stirbt unbemerkt, die Funnel zeigt ins Leere, und der
Claude-Connector scheitert mit „couldn't reach" / `start_error`. Mit Linger bleibt die User-
Instanz dauerhaft aktiv.

Wichtig — kein Widerspruch zu „`linked` statt `enabled`": Linger startet nur
**enabled** Units beim Boot. Da `titan-service` / `brain-mcp` /
`brain-watcher` `linked` (nicht enabled) sind, starten sie **nicht** automatisch — ein
„Stop" fürs Gaming bleibt in Kraft. Linger hält nur *bereits laufende* Services
am Leben, statt sie im Leerlauf zu killen.

---

## 2. Auth-Konfiguration (`.env`)

Der Server wird öffentlich exponiert und braucht daher OAuth. Die Konfiguration liegt
in `~/projects/brain-mcp/.env` (gitignored — niemals committen):

```
BRAIN_MCP_AUTH=github
BRAIN_MCP_BASE_URL=https://<your-tailnet-host>.ts.net
BRAIN_GITHUB_CLIENT_ID=Ov23li...
BRAIN_GITHUB_CLIENT_SECRET=...
BRAIN_GITHUB_ALLOWED_LOGINS=your-github-login
```

Eine GitHub-OAuth-App anlegen (https://github.com/settings/developers → OAuth Apps →
New OAuth App):

- **Homepage URL:** `https://<your-tailnet-host>.ts.net`
- **Authorization callback URL:** `https://<your-tailnet-host>.ts.net/auth/callback`

Nur die in `BRAIN_GITHUB_ALLOWED_LOGINS` aufgeführten GitHub-Logins sind erlaubt; alle
anderen werden bereits auf der Auth-Ebene mit einem 401 abgelehnt.

---

## 3. Öffentlich erreichbar machen — Tailscale Funnel

Claude verbindet Custom Connectors serverseitig aus der Anthropic-Cloud, der
Endpunkt muss also öffentlich erreichbar sein. Auf dem **Windows-Host**:

```powershell
tailscale funnel --bg http://localhost:9100
tailscale funnel status
```

Das proxyt `https://<your-tailnet-host>.ts.net/` → `http://localhost:9100`.

**502 Bad Gateway an der Funnel?** Häufigste Ursache: brain-mcp ist an
`127.0.0.1` statt `0.0.0.0` gebunden (siehe Abschnitt 1) — dann ist es von
Windows / der Funnel aus nicht erreichbar. Prüfen: von Windows `iwr http://127.0.0.1:9100/mcp` → muss
`401` zurückgeben. Schlägt das fehl, ist der Bind falsch (oder der Service ist unten). Seltener:
eine degradierte WSL2-Mirrored-Bridge (WSL hat nur `lo`, kein `ethX`) — Fix:
`wsl --shutdown`, dann WSL neu starten.

---

## 4. Den Connector in Claude Desktop hinzufügen

Einstellungen → Connectors → „Add custom connector":

- **URL:** `https://<your-tailnet-host>.ts.net/mcp`

Claude startet den OAuth-Flow → GitHub-Login (mit dem erlaubten Konto) → fertig.
Danach sind die sechs Tools `query_knowledge`, `find_related`, `list_domains`,
`list_notes`, `ingest_note` und `delete_note` verfügbar.

---

## 5. Smoke-Test

```bash
# Laufen die Services?
systemctl --user status brain-watcher brain-mcp

# Ist Titan erreichbar?
curl localhost:8765/health

# brain-mcp lokal — ist OAuth-Discovery erreichbar (erwartet: 200)?
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:9100/.well-known/oauth-protected-resource/mcp

# /mcp ohne Token — erwartet: 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  http://127.0.0.1:9100/mcp
```

---

## 6. Aktualisieren — vor jedem Neustart

`WorkingDirectory` und `ExecStart` der Unit zeigen auf den Checkout
`~/projects/brain-mcp`: **der laufende Code ist dieses Arbeitsverzeichnis.** Ein
Push nach GitHub ändert daran nichts, und ein Neustart allein bringt denselben
alten Stand wieder hoch — inklusive der Werkzeugbeschreibungen, die der Client
beim Verbinden liest.

```bash
cd ~/projects/brain-mcp
git pull
uv sync   # nur nötig, wenn sich Abhängigkeiten geändert haben; `uv sync` installiert das Projekt editierbar
systemctl --user restart brain-watcher brain-mcp
```

Wer in diesem Verzeichnis den Branch wechselt, wechselt den laufenden Server mit.
