# brain-mcp — Deployment

## Voraussetzungen

- WSL2 mit systemd (`/etc/wsl.conf` muss `[boot]\nsystemd=true` enthalten)
- Titan-Service bereits deployt und als `titan-service.service` aktiv
- Claude Desktop installiert (Windows-Seite)

---

## 1. brain-watcher als systemd-User-Service

```bash
# Verzeichnis für Service-Datei anlegen
mkdir -p ~/.config/systemd/user/

# Symlink auf die Service-Datei im Repo
ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/

# systemd neu laden und Service starten
systemctl --user daemon-reload
systemctl --user enable --now brain-watcher

# Status prüfen
systemctl --user status brain-watcher
journalctl --user -u brain-watcher -f
```

---

## 2. Claude Desktop einbinden (Windows-Seite)

Die MCP-Server-Config liegt unter:

```
%APPDATA%\Claude\claude_desktop_config.json
```

Typischer Pfad: `C:\Users\<username>\AppData\Roaming\Claude\claude_desktop_config.json`

Inhalt (anpassen falls Datei bereits existiert — `mcpServers`-Key hinzufügen/ergänzen):

```json
{
  "mcpServers": {
    "brain": {
      "command": "wsl",
      "args": [
        "-d", "Ubuntu",
        "--",
        "/home/charl/projects/brain-mcp/.venv/bin/brain-mcp"
      ],
      "env": {
        "BRAIN_TITAN_URL": "http://127.0.0.1:8765",
        "BRAIN_VAULT_ROOT": "/mnt/f/vault"
      }
    }
  }
}
```

**Nach der Änderung:** Claude Desktop neu starten. In einer neuen Konversation sollten die Tools
`brain__query_knowledge`, `brain__list_domains`, `brain__ingest_note`, `brain__find_related` sichtbar sein.

---

## 3. Smoke-Test

```bash
# Watcher läuft?
systemctl --user status brain-watcher

# Titan erreichbar?
curl localhost:8765/health

# Domains?
curl localhost:8765/domains

# MCP-Server manuell testen (stdio-Modus):
/home/charl/projects/brain-mcp/.venv/bin/brain-mcp
# Ctrl+C zum Beenden
```
