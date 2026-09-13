# Architektur

> Design auf Systemebene. Aktualisieren, wenn sich Module, Contracts oder Datenmodelle ändern.

## Überblick

brain-mcp ist die Brücke zwischen einem Obsidian-Vault, dem
[titan](https://github.com/charlieLucke/titan)-RAG-Service und Claude. Es besteht
aus zwei kooperierenden, aber unabhängigen Diensten: einem **Vault-Watcher**, der
geänderte Notizen automatisch in titan indexiert, und einem **MCP-Server**, der
Claude sechs Such-/Verwaltungs-Werkzeuge bereitstellt. Beide sprechen mit titan
ausschließlich über dessen HTTP-API — es gibt keine direkte Kopplung an titans
Code oder an Qdrant.

```
Obsidian (Windows) → Vault (F:\vault\) → brain-watcher (watchdog)
                                            │ HTTP POST /ingest/file
                                            ▼
                                     titan-service :8765  (separates Repo)
                                            ▲
Claude ──(stdio | HTTP/Funnel-Connector)──► brain-mcp    │ HTTP /search usw.
```

## Modulübersicht

```
src/brain_mcp/
├── config.py        # Settings (Env-Präfix BRAIN_): titan-URL, Vault-Root, Debounce, Transport, OAuth
├── schemas.py       # Pydantic Request/Response-Schemas (lokale Kopie der titan-API-Schemas)
├── titan_client.py  # TitanClient: async httpx + Retry via tenacity
├── mcp_server.py    # FastMCP-Server + die sechs MCP-Tools + Transport-Wahl (stdio | http)
├── auth.py          # GitHub-OAuth-Proxy + GitHubAllowlistVerifier (Login-Allowlist)
└── watcher.py       # VaultWatcher: watchdog-Observer, Debounce, Reconnect, Reconcile
deploy/
├── brain-watcher.service  # systemd-User-Service (Vault-Watcher)
├── brain-mcp.service      # systemd-User-Service (HTTP-MCP-Server)
└── README.md              # Aktivierungs- + Connector-Anleitung
```

## Die zwei Dienste

### brain-watcher
Ein systemd-User-Daemon, der den Vault rekursiv überwacht. Geänderte `.md`-Dateien
werden mit **30 s Debounce** gebündelt (mehrere schnelle Speichervorgänge ergeben
einen Ingest) und per `POST /ingest/file` an titan gereicht. Eine **Reconnect-Logik**
mit exponentiellem Backoff und ein **Cool-down** sorgen dafür, dass ein Titan-Ausfall
den Watcher nicht blockiert oder abstürzen lässt; Lösch-Events landen bei Bedarf in
einer Pending-Queue und werden nach Wiederherstellung abgearbeitet. Beim Start
gleicht ein **Reconcile-Pass** den Vault gegen titans Index ab und holt Änderungen
nach, die während einer Downtime entstanden sind.

### brain-mcp (der MCP-Server)
Auf Basis von **FastMCP**. Der Transport ist umschaltbar:
- **stdio** — der MCP-Client (z. B. Claude Desktop) startet brain-mcp als Subprozess;
  keine Netzwerk-Exposition, keine Auth.
- **Streamable-HTTP** — ein langlebiger Server (systemd-Service auf Port 9100), der
  über eine Tailscale Funnel öffentlich erreichbar gemacht und durch GitHub-OAuth
  abgesichert als Claude-Custom-Connector eingebunden wird.

## Externe Services

| Service | Verbindung | Zweck |
|---|---|---|
| titan | HTTP `127.0.0.1:8765` | RAG-Backend: Suche, Ingest, Notes/Domains |
| GitHub OAuth | HTTPS (api.github.com) | Authentifizierung + Login-Allowlist im HTTP-Modus |
| Tailscale Funnel | öffentliches HTTPS | macht den lokalen MCP-Server für die Anthropic-Cloud erreichbar |
| Obsidian-Vault | Dateisystem (watchdog) | Quelle der zu indexierenden Notizen |

## Datenfluss

### Indexierung (Vault → titan)
```
.md geändert → watchdog-Event → Debounce (30 s) → TitanClient.ingest_file()
            → POST titan /ingest/file → (titan: Late Chunking + BGE-M3 + Qdrant-Upsert)
```

### Abfrage (Claude → Vault)
```
Claude ruft MCP-Tool query_knowledge auf → brain-mcp → POST titan /search
       → gerankte Chunks → als Markdown formatiert zurück an Claude
```

MCP-Tool-Rückgabewerte sind immer Markdown-Strings (nie rohes JSON), damit Claude
sie direkt darstellen kann.

## Sicherheit & Grenzen

- **Auth nur im HTTP-Modus:** stdio bleibt lokal/unauthentifiziert; der öffentliche
  HTTP-Modus erzwingt OAuth + Allowlist.
- **Pfadvalidierung gegen `VAULT_ROOT`** erfolgt sowohl clientseitig (brain-mcp) als
  auch serverseitig (titan).
- **Entkopplung:** brain-mcp importiert keinen titan-Code, sondern hält eine lokale
  Kopie der API-Schemas — die Repos bleiben unabhängig deploybar.

## Deployment

Zwei systemd-User-Services. Im Always-on-Modus bindet `brain-mcp` an `0.0.0.0:9100`
(nicht `127.0.0.1`), damit die Windows-seitige Tailscale Funnel ihn unter WSL2
Mirrored Networking erreicht. Linger hält die Dienste auch ohne offene Login-Sitzung
am Leben. Details: [`deploy/README.md`](../../deploy/README.md).
