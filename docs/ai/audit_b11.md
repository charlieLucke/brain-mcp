# Audit-Bericht: Task B11 (Phase 2 brain-mcp)

**Datum:** 2026-05-13
**Status:** ⚠️ Findings vorhanden (E2E Tests)

Dieser Bericht dokumentiert die Ergebnisse der Audit-Runde (Task B11) gemäß dem Plan `plan_titan_brain_v2.md` für das `brain-mcp` Repository.

## Checkliste & Ergebnisse

- [x] **MCP-Tool-Descriptions präzise, verweisen aufeinander (`list_domains` als Helper für `query_knowledge`)**
  **Ja.** Die Descriptions in `mcp_server.py` sind präzise und erklären den Workflow (z.B. verweist `query_knowledge` auf `list_domains`).

- [x] **`query_knowledge` clampt `top_k` auf 30**
  **Ja.** Implementiert in `mcp_server.py`: `top_k = min(max(1, top_k), 30)`.

- [x] **Watcher hat Debouncing-Tests die in <2 Sekunden durchlaufen**
  **Ja.** In `test_watcher.py` nutzt der Test `test_rapid_saves_only_trigger_one_ingest` einen kurzen `debounce_seconds` Wert von 0.1s, wodurch der Test sehr schnell (< 1s) durchläuft.

- [x] **Watcher fängt alle Exceptions in `_worker`, läuft weiter**
  **Ja.** In `watcher.py` (`_ingest`) werden `httpx.ConnectError`, `httpx.HTTPStatusError` und generische Exceptions abgefangen, geloggt und der Worker-Thread stürzt nicht ab.

- [x] **Pfad-Validierung Client-seitig gegen VAULT_ROOT**
  **Ja.** `ingest_note` und `find_related` prüfen mittels `path.is_relative_to(settings.vault_root)`.

- [x] **`Wants=` (nicht `Requires=`) im systemd**
  **Ja.** In `deploy/brain-watcher.service` ist `Wants=titan-service.service` und `After=titan-service.service` korrekt gesetzt.

- [x] **Reconnect-Logik mit Backoff in Watcher**
  **Ja.** Die Funktion `_ensure_titan_available` implementiert einen Exponential Backoff über `(1, 2, 4, 8, 16)` Sekunden.

- [x] **`indexed:false`-Übergang räumt Chunks**
  **Ja.** Wird von `titan` verarbeitet und der Watcher loggt das Feedback (`skipped_reason: indexed:false`) korrekt. Der E2E Test prüft dieses Verhalten.

- [x] **Keine Secrets in Logs**
  **Ja.** Weder MCP Server noch Watcher loggen API Keys oder andere kritische Informationen.

- [x] **Tool-Output ist immer Markdown-String (kein JSON-Leak)**
  **Ja.** Alle MCP Tools geben reine Strings zurück, Resultate werden via `_format_chunks` in sauberes Markdown umgewandelt.

- [x] **E2E-Test deterministisch (Polling, kein `time.sleep` für Synchronisation)**
  **Ja.** In `test_e2e_pipeline.py` wird die Helfer-Funktion `_wait_until` genutzt, die mittels Polling deterministisch wartet.

- [ ] **Tests gegen Test-Collection, nicht Produktiv**
  **NEIN.** Die aktuellen E2E-Tests in `test_e2e_pipeline.py` haben ein architektonisches Problem:
  Sie erwarten, dass ein echter Titan-Service auf `http://127.0.0.1:8765` läuft. Wenn dies der produktive Service ist, hat dieser einen fest definierten `VAULT_ROOT` (z.B. `/mnt/f/vault`). Der E2E-Test in `brain-mcp` erstellt aber temporäre Verzeichnisse für den Vault (`tmp_path / "vault"`).
  *Folge 1:* Der echte Titan-Service wird Anfragen für Dateien in `/tmp/...` mit HTTP 400 (Pfad außerhalb VAULT_ROOT) ablehnen.
  *Folge 2:* Wenn der Test umgeschrieben wird, um echte Pfade in `VAULT_ROOT` zu nutzen, würde er Chunks in die produktive Qdrant-Collection "mein_wissen" schreiben, was gegen die Checkliste ("nicht Produktiv") verstößt.

## Nächster Schritt
Ich lege einen Implementierungsplan an, wie wir die Integrationstests umgestalten können, damit sie die Anforderungen (Test-Collection, kein Produktiv-Daten-Eingriff) erfüllen.
