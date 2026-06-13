# Entscheidungs-Log

> Architecture Decision Records. Nur anhängen. Ein Eintrag pro signifikanter Entscheidung.
> Das verhindert, dieselben Fragen in jeder neuen KI-Sitzung neu auszufechten.

---

## 2026-05-13: Schemas als lokale Kopie (nicht aus titan importiert)

**Entscheidung:** `brain_mcp/schemas.py` hält eine lokale Kopie der Titan-API-Schemas,
keinen Import aus dem `titan`-Paket.
**Begründung:** brain-mcp soll von titan entkoppelt sein — verbunden nur über die HTTP-
Schnittstelle. Ein Repo-übergreifender Import (`brain_mcp` importiert `titan`) würde titan als
Python-Abhängigkeit hereinziehen und beide Repos im Gleichschritt halten.
**Erwogene Alternativen:** Ein gemeinsames `titan-schemas`-Paket (ein drittes Repo) — zu viel
Overhead für sieben Schemas.
**Konsequenzen:** Bei API-Änderungen beide Seiten manuell synchronisieren. Beginnen die Schemas
signifikant auseinanderzulaufen: dann `titan-schemas` extrahieren.

## 2026-05-13: brain-mcp läuft nicht als Daemon (Per-Session-stdio)

**Entscheidung:** brain-mcp wird von Claude Desktop als Subprozess gestartet (stdio-Transport),
kein systemd-Service.
**Begründung:** Der MCP-stdio-Transport ist per-Session — Claude Desktop verwaltet den
Lebenszyklus. Ein systemd-Daemon wäre hier falsch, da MCP nicht dauerhaft lauschen muss.
**Konsequenzen:** `deploy/` enthält nur `brain-watcher.service`. brain-mcp hat keine
systemd-Unit. Deployment = Binary in `.venv/bin/brain-mcp` + ein JSON-Eintrag in Claude Desktop.

## 2026-05-13: Wants= statt Requires= in der systemd-Unit

**Entscheidung:** `brain-watcher.service` nutzt `Wants=titan-service.service`, nicht `Requires=`.
**Begründung:** Mit `Requires=` würde brain-watcher zusammen mit einem Titan-Neustart gekillt.
Die Reconnect-Logik des Watchers macht `Wants=` sicher: der Watcher wartet mit exponentiellem
Backoff, bis Titan wieder erreichbar ist.
**Konsequenzen:** Der Watcher überlebt Titan-Neustarts. Der Watcher überlebt auch, wenn Titan
beim Watcher-Start gar nicht läuft (Events bleiben im Pending-Dict, bis Titan zurückkehrt).

## 2026-05-13: use_decompose=False als MCP-Default

**Entscheidung:** `query_knowledge` übergibt `use_decompose=False` an titan.search.
**Begründung:** Wie in Plan-Abschnitt 7 beschrieben: Claude (Opus/Sonnet) kann die Query-
Zerlegung selbst. Phi-4-Decompose im Service wäre Doppelarbeit und zusätzliche
Latenz.
**Konsequenzen:** Der CLI-Pfad (`python -m titan.search`) nutzt weiterhin `use_decompose=True`
als Default. Nur der MCP-Pfad setzt False.

## 2026-05-13: Cool-down statt Per-Call-Backoff in _ensure_titan_available

**Entscheidung:** `_ensure_titan_available` macht genau eine health()-Probe pro Aufruf.
Bei Fehlschlag wird ein 30-Sekunden-Cool-down als `self._titan_dead_until` gesetzt; während des Cool-downs
geben alle weiteren Aufrufe sofort `False` zurück.
**Begründung:** Audit B-CRIT-2: das alte Backoff (1+2+4+8+16 = 31 s pro Aufruf) blockierte den
Worker-Thread minutenlang, wenn mehrere Events anstanden und Titan unten war. Außerdem wurde jeder
unerwartete Fehler (z. B. ValidationError bei einer degradierten Antwort) nicht abgefangen — Watcher-Crash.
**Konsequenzen:** Der Worker wird während des Cool-downs nicht blockiert. Events landen weiter in
`_pending` und werden nach Ablauf des Cool-downs normal verarbeitet.

## 2026-05-13: Failed-Delete-Queue (_pending_deletes)

**Entscheidung:** Ist Titan bei einem Delete-Event unten, wandert der Pfad in
`self._pending_deletes`. Die Worker-Loop verarbeitet die Queue bei jedem Tick — sobald
Titan wieder erreichbar ist.
**Begründung:** Audit B-MED-3: ohne Queue gingen Delete-Events verloren, während Titan
neu startete. Der Index driftete vom Dateisystem ab (gelöschte Notizen blieben indexiert).
**Konsequenzen:** Deletes verzögern sich um höchstens einen Cool-down-Zyklus (30s). Bei einem langen Titan-
Ausfall bleiben sie in der Queue und werden nach der Wiederherstellung abgearbeitet.

## 2026-05-13: Debounce-Sekunden als injizierbares Setting

**Entscheidung:** `VaultWatcher.__init__` akzeptiert `debounce_seconds: float` als Parameter.
`config.py` exponiert `BRAIN_DEBOUNCE_SECONDS` (Default 30.0).
**Begründung:** Tests brauchen ein 0,1s-Debounce, damit sie in <2s fertig sind. Produktion nutzt 30s.
Kein `time.sleep(35)` in Tests (war ein Sonnet-Befund aus Plan v1).
**Konsequenzen:** E2E-Fixtures können `debounce_seconds=0.1` setzen. Die systemd-Unit setzt
`BRAIN_DEBOUNCE_SECONDS=30` via Environment.

## 2026-05-16: brain-mcp als HTTP-Daemon; Claude-Integration via Funnel + Auth (offen)

**Entscheidung:** brain-mcp kann als persistenter Streamable-HTTP-Server über
`BRAIN_MCP_TRANSPORT=http` laufen (der Default bleibt `stdio`). Der neue systemd-User-Service
`deploy/brain-mcp.service` betreibt ihn als reinen HTTP-Server auf `127.0.0.1:9100`.
Für die Claude-Integration ist **Tailscale Funnel + eine Auth-Schicht (OAuth)** geplant —
aber per 2026-05-16 ist dieser Teil **noch nicht implementiert** (zurückgestellt).
**Begründung:** Der installierte Claude-Desktop-Build (interner „epitaxy"/Cowork-Build) hat keinen
Developer Mode und behandelt `claude_desktop_config.json` rein als Preferences-Datei — ein
manuell hinzugefügter `mcpServers`-Block wird ignoriert und beim nächsten App-Save wieder entfernt.
Der klassische stdio-Pfad (Entscheidung 2026-05-13) ist mit diesem Build also nicht nutzbar; der einzige
verbleibende Pfad ist ein *Custom Connector*. Laut Anthropic-Doku verbindet Claude einen Custom
Connector **serverseitig aus der Anthropic-Cloud** (gilt für claude.ai, Desktop, Cowork,
Mobile) — der MCP-Endpunkt muss also **öffentlich aus dem Internet erreichbar** sein. Eine rein
lokale oder tailnet-private Lösung kann grundsätzlich nicht funktionieren.
**Erwogene Alternativen:**
- stdio via `claude_desktop_config.json` — von diesem Build nicht unterstützt (siehe oben).
- `tailscale serve` (tailnet-privat, gültiges HTTPS-Zertifikat) — getestet, funktioniert NICHT:
  Anthropics Cloud ist nicht im Tailnet, nicht ein einziger Request erreichte den Server.
  Wieder entfernt (`tailscale serve --https=443 off`).
- Paketierung als `.mcpb`-Extension — das Bundle müsste `wsl.exe` aufrufen (Server lebt
  in WSL, Claude Desktop auf Windows); umständlich und fragil.
- brain-mcp in der MCP-Konfiguration von Claude Code (lokal, sicher, keine Exposition) — nur in
  Claude-Code-Sitzungen verfügbar, nicht im normalen Claude-Desktop-Chat. Bleibt ein möglicher Fallback.
**Konsequenzen:**
- Diese Entscheidung **ersetzt** die Entscheidung vom 2026-05-13 („brain-mcp läuft nicht als
  Daemon"). stdio bleibt der Default (andere MCP-Clients, lokale Tests), aber für die Claude-
  Integration läuft brain-mcp als Daemon.
- `deploy/` enthält jetzt zwei Units: `brain-watcher.service` und `brain-mcp.service`.
- `config.py` hat neue Settings: `mcp_transport`, `mcp_host`, `mcp_port`
  (env: `BRAIN_MCP_TRANSPORT` / `BRAIN_MCP_HOST` / `BRAIN_MCP_PORT`).
- **Offen / TODO vor Inbetriebnahme des Connectors:**
  1. Eine Auth-Schicht (OAuth) in brain-mcp einbauen — ein öffentlich erreichbarer, nicht
     authentifizierter Vault-Server darf NICHT ins Internet.
  2. Erst dann `tailscale funnel` für `127.0.0.1:9100` aktivieren.
  3. Den Connector in Claude Desktop mit der Funnel-URL hinzufügen.
  4. `deploy/README.md` (Claude-Desktop-Abschnitt) auf diesen Pfad aktualisieren.
- Windows↔WSL-Erreichbarkeit (für lokale Tests / `tailscale` auf Windows → `localhost` in WSL)
  läuft über WSL2 Mirrored Networking — siehe titan `docs/ai/DECISIONS.md` (2026-05-16).

## 2026-05-16: OAuth-Auth implementiert — GitHub-Proxy mit Allowlist, Connector live

**Entscheidung:** Die in der vorherigen Entscheidung offen gelassene Claude-Integration ist implementiert.
brain-mcp nutzt einen GitHub-OAuth-Proxy (`fastmcp` `OAuthProxy` mit GitHub-Endpunkten) und einen
benutzerdefinierten Token-Verifier `GitHubAllowlistVerifier` (`src/brain_mcp/auth.py`), der nur
GitHub-Logins aus einer Allowlist zulässt. Der Server läuft öffentlich hinter `tailscale funnel`; in
Claude ist er als Custom Connector `https://<your-tailnet-host>.ts.net/mcp` verdrahtet.
**Begründung:** Claude verbindet Custom Connectors serverseitig → ein öffentlicher Endpunkt ist nötig
(Funnel). Ein öffentlicher, nicht authentifizierter Vault-Server ist inakzeptabel → OAuth. Aber GitHub-OAuth
authentifiziert *jedes* GitHub-Konto; da der Vault persönlich ist, beschränkt der Allowlist-Verifier
ihn auf den Besitzer und weist alle anderen bereits auf der Auth-Ebene (401) ab.
**Erwogene Alternativen:**
- Kein User-Filter (nur GitHub-Login) — verworfen: jedes GitHub-Konto käme rein.
- Allowlist via Middleware / Per-Tool-Check — verworfen: der Token-Verifier weist früher ab
  (vor jedem Tool-Call) und ist die saubere Stelle.
**Konsequenzen:**
- Neues Modul `src/brain_mcp/auth.py`. Neue Settings in `config.py`: `mcp_auth`,
  `mcp_base_url`, `github_client_id`, `github_client_secret`, `github_allowed_logins`.
- Secrets liegen in `brain-mcp/.env` (gitignored), nicht im Repo. `.env.example` dokumentiert
  die Variablen.
- Auth gilt nur im HTTP-Transport; stdio bleibt lokal/nicht authentifiziert.
- Betriebliche Voraussetzungen: `tailscale funnel` aktiv (persistent), eine GitHub-OAuth-App
  mit Callback `https://<your-tailnet-host>.ts.net/auth/callback`, eine intakte
  WSL2-Mirrored-Networking-Bridge (sonst 502 Bad Gateway an der Funnel; Fix:
  `wsl --shutdown` + Neustart).
- End-to-end verifiziert: `query_knowledge` aus Claude liefert Vault-Treffer.

## 2026-05-16: systemd-Units `linked` statt `enabled` (Autostart aus)

**Entscheidung:** `titan-service`, `brain-mcp` und `brain-watcher` sind als systemd-
User-Units mit `linked` registriert, **nicht** `enabled`. Start und Stopp laufen über das Desktop-Skript
`RAG-System.bat`.
**Begründung:** Mit `enable` starten die Services bei jedem WSL-Boot automatisch. Da jeder
`wsl`-Befehl (z. B. eine Statusabfrage) WSL bereits bootet, würde ein „Stop" sofort rückgängig gemacht
— die Services kämen von selbst wieder hoch und verbrauchten GPU-VRAM/RAM. Mit `linked` bleiben sie
nach einem Stop aus, bis sie explizit gestartet werden.
**Konsequenzen:**
- Nach einem Windows-Neustart läuft das System nicht von selbst — `RAG-System.bat` → „Start"
  bringt es hoch (wie beabsichtigt).
- `systemctl --user link <path>` registriert die Unit ohne Autostart; `start` / `restart`
  funktionieren normal.
- Achtung: bei Units, die ins Repo gesymlinkt sind, entfernt `systemctl --user disable` auch den
  Unit-Symlink selbst — danach erneut `systemctl --user link` ausführen.
- `deploy/README.md` Abschnitt 1 nutzt entsprechend `link` statt `enable`.

## 2026-05-17: vault-admin als Tools in brain-mcp (kein separater MCP-Server)

**Entscheidung:** Die vault-admin-Tools `list_notes` und `delete_note` werden als zusätzliche
Tools im bestehenden `brain`-Server ergänzt — kein separater `vault-admin`-MCP-Server.
**Begründung:** Ein separater MCP-Server bräuchte einen zweiten Custom Connector in Claude mit
eigenem OAuth-Setup und eigener Funnel. Die Tools gehören thematisch zu den bestehenden Vault-Tools; sie
teilen sich `TitanClient`, Config und Auth.
**Erwogene Alternativen:** Ein dedizierter `vault-admin`-Server — verworfen (Overhead, zweiter
Connector, zweites OAuth).
**Konsequenzen:** Der `brain`-Server hat jetzt 6 Tools. `delete_note` ist reines De-Indexieren —
es entfernt nur die Chunks aus dem Index, die `.md`-Datei auf der Platte bleibt unberührt.
`list_notes` braucht den neuen titan-Endpunkt `GET /notes` (siehe titan `docs/ai/DECISIONS.md`,
2026-05-17).

## 2026-05-22: Connector-Ausfall war Infrastruktur, nicht OAuth — Linger + 0.0.0.0-Bind

**Entscheidung:** Zwei betriebliche Fixes, damit der Custom Connector zuverlässig verbindet:
(1) `loginctl enable-linger charl`, (2) `BRAIN_MCP_HOST=0.0.0.0` in
`deploy/brain-mcp.service` (war `127.0.0.1`).
**Begründung:** Der Connector scheiterte mit „couldn't reach" / `start_error`, obwohl der
OAuth-Code korrekt war (lokal getestet: `/mcp`→401, Discovery→200, `POST /register`→201).
Zwei Infrastruktur-Ursachen, beide durch einen PC-Neustart ausgelöst:
- **Linger=no:** ohne Linger beendet WSL die systemd-User-Instanz, sobald keine Sitzung
  offen ist → brain-mcp (und der ganze Stack) stirbt im Leerlauf → die Funnel zeigt ins Leere.
  Erklärt „funktionierte vorher, plötzlich nicht mehr".
- **`127.0.0.1`-Bind:** unter WSL2 Mirrored Networking ist ein reiner Loopback-Service unerreichbar
  von Windows; die Funnel (auf Windows) bekam **502**. Beweis: das Dashboard (`0.0.0.0:9200`)
  war von Windows mit 200 erreichbar, brain-mcp (`127.0.0.1:9100`) gar nicht. Nach dem
  Wechsel auf `0.0.0.0` → Funnel 401.
**Erwogene Alternativen:** fastmcp-Upgrade 3.2.4→3.3.1 (kein Effekt, nicht die Ursache; zurück auf
lock-konsistentes 3.3.1). Dual-Stack-`::`-Bind (unter Mirrored-Modus laut
titan/dashboard-Erfahrung kontraproduktiv) — verworfen.
**Konsequenzen:**
- Linger ist persistent (übersteht Reboots). Kompatibel mit „`linked` statt `enabled`":
  gestoppte Services bleiben gestoppt (Gaming-Workflow intakt), nur laufende sterben nicht mehr
  im Leerlauf.
- brain-mcp ist über `0.0.0.0` erreichbar; der Zugriff ist weiterhin durch GitHub-OAuth abgesichert. Der 502-Hinweis
  der Entscheidung vom 2026-05-16 wird damit präzisiert (die häufigste 502-Ursache = falscher Bind, nicht
  die Mirrored-Bridge).
- `BRAIN_GITHUB_ALLOWED_LOGINS` wurde im Zuge des GitHub-Renames auf `charlieLucke`
  aktualisiert (in `.env`, gitignored).
