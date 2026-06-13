# Ideen

> Out-of-Scope-Ideen, die während der Arbeit festgehalten werden, um sie später wieder aufzugreifen.
> Nichts hier ist verbindlich. Das ist ein Parkplatz.

## Format
- [ ] **JJJJ-MM-TT:** Ideenbeschreibung. Warum sie wichtig ist. Grobe Aufwandsschätzung.

---

## Ausstehend

- [ ] **2026-06-01: Den GitHub-Allowlist-Check pro Token cachen.** Der
      `GitHubAllowlistVerifier` ruft bei *jedem* MCP-Request GitHub `GET /user`
      (+ `/user/repos`) auf, um den Login aufzulösen — in den Logs sichtbar als ein Schwall
      von `api.github.com`-Aufrufen pro Request. Das ist unnötig geschwätzig und riskiert das
      GitHub-API-Rate-Limit unter Last. Den verifizierten Login pro Access-Token mit
      kurzer TTL cachen (z. B. 60–300 s), sodass wiederholte Requests den GitHub-Round-Trip überspringen.
      Aufwand: Niedrig.
