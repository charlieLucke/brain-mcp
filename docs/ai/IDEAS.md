# Ideas

> Out-of-scope ideas captured during work, to revisit later.
> Nothing here is committed. This is a parking lot.

## Format
- [ ] **YYYY-MM-DD:** Idea description. Why it matters. Rough effort estimate.

---

## Pending

- [x] **2026-06-20: WSL-Mirrored-Watchdog entschärfen + auf Resume triggern.**
      ✅ **Hinfällig seit 2026-06-22 (Umstieg auf NAT):** der Watchdog ist deaktiviert —
      NAT degradiert nicht, der gefährliche HNS-Brute-Force entfällt. Ersatz ist die
      harmlose Aufgabe `WSL-PortProxy`. Ursprüngliche Idee:
      brain-mcps öffentliche Erreichbarkeit hing an der WSL2-Mirrored-Bridge
      (Windows-Tailscale-Funnel → WSL-`localhost:9100`). Die degradiert wiederholt
      (`0x8007054f`/Timeout, bekannter MS-Bug #13454/#13587), bisher „repariert" vom
      Watchdog `C:\Tools\wsl-mirrored-fix.ps1`. Problem: dessen **Stufe 2
      (HNS.data-Reset) ist kaputt** (falscher Pfad) **und gefährlich** — sie löste am
      2026-06-18 einen `dxgkrnl`-BSOD aus (riss die WSL-VM weg, während titan die GPU
      geladen hatte). Außerdem läuft der Watchdog nur beim **Login**, obwohl
      **Sleep/Resume** ein Haupttrigger ist. Fix: (a) Stufe 2 raus/ersetzen, kein hartes
      `wsl --shutdown` unter GPU-Last; (b) zusätzlich per **Power-Resume-Event**
      triggern, nicht nur Login; (c) titan stoppen vor erzwungenem WSL-Neustart.
      Querbezug: Vault-Notiz `system-wsl-mirrored-fix`. *Effort: Medium.*

- [x] **2026-06-20: Funnel von der Windows↔WSL-Mirrored-Abhängigkeit lösen (Plan B).**
      ✅ **Gelöst 2026-06-22 via Option (c): NAT + `netsh portproxy`** (Aufgabe
      `WSL-PortProxy`, von `RAG-System.bat [1]` getriggert; end-to-end getestet,
      Dashboard von Windows = HTTP 200). Hub-Migration (b) blieb ungenutzt, weil titan
      GPU-gebunden auf der Workstation ist und brain-mcp es braucht. Ursprüngliche Idee:
      Mirrored-Networking ist auf dieser Maschine inhärent fragil (mehrere gespiegelte
      Adapter → HNS degradiert). Es existiert *nur*, weil **Tailscale auf Windows** läuft
      und der Funnel WSL-`localhost:9100` erreichen muss. Wenn die Dauer-Fixe
      (Fast-Startup aus, `dnsTunneling`, WSL-Update auf 2.7.8) nicht reichen, die
      Abhängigkeit ganz auflösen — Optionen: (a) **Tailscale in WSL** laufen lassen →
      zurück zu stabilem **NAT**; (b) brain-mcp/Funnel auf den **always-on Hub**
      verlagern (hat das Windows↔WSL-Problem gar nicht; passt zur Zwei-Tier-Architektur);
      (c) **NAT + `netsh portproxy`** für Port 9100 (mit dynamischem WSL-IP-Update).
      (b) ist strategisch am saubersten. *Effort: Medium–High; eigener Plan.*

- [ ] **2026-06-01: Cache the GitHub allowlist check per token.** The
      `GitHubAllowlistVerifier` calls GitHub `GET /user` (+ `/user/repos`) on *every*
      MCP request to resolve the login — visible in the logs as a burst of
      `api.github.com` calls per request. That is needlessly chatty and risks the
      GitHub API rate limit under load. Cache the verified login per access token with
      a short TTL (e.g. 60–300 s) so repeat requests skip the GitHub round-trip.
      Effort: Low.
