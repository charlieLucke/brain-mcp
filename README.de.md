# brain_mcp

Ein MCP-Server und Vault-Watcher, die einen Obsidian-Vault für Claude durchsuchbar
machen — gestützt auf den **Titan**-RAG-Service (ein Schwester-Repo).

> **Platzhalter:** Werte wie `<your-user>`, `<your-tailnet-host>.ts.net` und
> `<your-github-login>` sind Beispiele aus dem Setup des Autors — ersetze sie durch
> deine eigenen.

## Voraussetzungen

- **Python 3.12+** und **[uv](https://docs.astral.sh/uv/)**.
- **Ein laufender Titan-Service** (das RAG-Backend, Schwester-Repo `titan`). brain-mcp
  spricht über HTTP mit ihm unter `BRAIN_TITAN_URL` (Default `http://127.0.0.1:8765`);
  ohne ihn liefern die Tools „Titan unreachable".
- **Einen Transport wählen:**
  - **stdio** (Default, am einfachsten) — ein MCP-Client startet brain-mcp als Subprozess.
    Keine Netzwerk-Exposition, keine Auth. Am besten für lokale Nutzung.
  - **HTTP** (der deployte Modus) — ein langlebiger Server für einen Claude-*Custom-Connector*.
    Anthropic verbindet Custom Connectors serverseitig, der Endpunkt muss also öffentlich
    über HTTPS erreichbar **und** authentifiziert sein. Der Autor exponiert ihn über eine
    Tailscale-Funnel + einen GitHub-OAuth-Proxy mit Login-Allowlist — siehe `deploy/README.md`.

## Schnellaktivierung (das WSL-Deployment des Autors)

Dieser Abschnitt beschreibt das spezifische Always-on-Setup des Autors. Zwei systemd-User-Services;
Claude erreicht den MCP-Server als Custom Connector. Vollständige Anweisungen plus die
Hinweise zur Anpassung von Grund auf stehen in **`deploy/README.md`**.

**Services (WSL systemd)**

```bash
mkdir -p ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now brain-watcher brain-mcp
```

- `brain-watcher` — überwacht den Obsidian-Vault und ingestet geänderte Notizen in Titan.
- `brain-mcp` — stellt die MCP-Tools über Streamable-HTTP bereit. Im Deployment bindet er
  `0.0.0.0:9100` (nicht `127.0.0.1`), damit die Windows-seitige Tailscale-Funnel ihn
  unter WSL2 Mirrored Networking erreichen kann; siehe `deploy/README.md`.

**Claude-Integration**

Custom Connectors werden serverseitig von Anthropic verbunden, der MCP-Endpunkt muss
also öffentlich erreichbar und authentifiziert sein. brain-mcp wird über Tailscale Funnel
exponiert und durch einen GitHub-OAuth-Proxy mit Login-Allowlist geschützt. Siehe `deploy/README.md`
für die Connector-URL, die GitHub-OAuth-App und die `.env`-Auth-Variablen.

## MCP-Tools

Der Server stellt sechs Tools bereit, alle gestützt auf den Titan-RAG-Service:

| Tool | Zweck |
|---|---|
| `query_knowledge` | Den Vault in natürlicher Sprache durchsuchen (optionaler `domain`-Filter, `top_k`). |
| `find_related` | Notizen finden, die einer gegebenen Notiz semantisch verwandt sind. |
| `list_domains` | Alle Domains im Index mit ihrer Chunk-Anzahl auflisten. |
| `list_notes` | Jede indexierte Notiz auflisten (optionaler `domain`-Filter) mit Domain + Chunk-Anzahl. |
| `ingest_note` | Eine Notiz sofort neu indexieren, unter Umgehung der Watcher-Verzögerung (ersetzt alte Chunks). |
| `delete_note` | Eine Notiz de-indexieren (entfernt ihre Chunks; die Markdown-Datei auf der Platte bleibt unberührt). |

---

## Entwicklungs-Setup

Erfordert [uv](https://docs.astral.sh/uv/) und Python 3.12+.

```bash
make install
```

Das installiert alle Abhängigkeiten und registriert pre-commit-Hooks.

## Entwicklung

```bash
make run        # den Server lokal ausführen (python -m brain_mcp)
make test       # Tests mit Coverage ausführen
make test-fast  # nur schnelle Tests ausführen (langsame + Integration überspringen)
make check      # vollständiges Quality-Gate: Lint + Typen + Tests
make format     # Style-Probleme automatisch beheben
make help       # alle verfügbaren Befehle auflisten
```

## Projektstruktur

```
src/brain_mcp/    Quellcode
tests/               Pytest-Tests (spiegelt das src/-Layout)
docs/ai/             Kontext und Pläne für KI-Agenten
.github/workflows/   CI-Konfiguration
```

## Tooling

| Tool         | Zweck                                |
|--------------|--------------------------------------|
| **uv**       | Paketmanager + Python-Installer      |
| **ruff**     | Linter + Formatter                   |
| **mypy**     | Statischer Typprüfer (Strict Mode)   |
| **pytest**   | Test-Runner mit Coverage             |
| **pre-commit** | Git-Hook-Runner                    |

Alle Tools laufen bei jedem Push in der CI.

## Arbeiten mit KI-Tools

Dieses Projekt nutzt einen strukturierten Workflow für KI-gestütztes Coding. Jeder
KI-Agent (Claude, Gemini, Cursor, Aider usw.) sollte zuerst `CLAUDE.md` lesen — sie
ist als `AGENTS.md` und `GEMINI.md` für Tool-Kompatibilität gespiegelt.

Wichtige Dateien für den KI-Kontext:

- `docs/ai/CONTEXT.md` — Stack, Konventionen, Glossar
- `docs/ai/CURRENT_TASK.md` — woran aktiv gearbeitet wird
- `docs/ai/HANDOFF.md` — Zustand für die Fortsetzung von Sitzungen über Modellwechsel hinweg
- `docs/ai/DECISIONS.md` — Protokoll der Architekturentscheidungen
- `docs/ai/plans/` — gespeicherte Pläne, erstellt von einem Planungsmodell (z. B. Opus)

Der vorgesehene Workflow:

1. Architektur- und Feature-Pläne werden von einem starken Reasoning-Modell erstellt und unter `docs/ai/plans/` gespeichert
2. Ein schnelleres/günstigeres Modell implementiert die Pläne
3. Beide referenzieren den gemeinsamen Kontext in `docs/ai/`
4. Der Zustand wird über `HANDOFF.md` über Sitzungen hinweg bewahrt

## Lizenz

Noch offen (TBD)
