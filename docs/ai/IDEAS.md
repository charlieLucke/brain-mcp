# Ideas

> Out-of-scope ideas captured during work, to revisit later.
> Nothing here is committed. This is a parking lot.

## Format
- [ ] **YYYY-MM-DD:** Idea description. Why it matters. Rough effort estimate.

---

## Pending

- [ ] **2026-06-01: Cache the GitHub allowlist check per token.** The
      `GitHubAllowlistVerifier` calls GitHub `GET /user` (+ `/user/repos`) on *every*
      MCP request to resolve the login — visible in the logs as a burst of
      `api.github.com` calls per request. That is needlessly chatty and risks the
      GitHub API rate limit under load. Cache the verified login per access token with
      a short TTL (e.g. 60–300 s) so repeat requests skip the GitHub round-trip.
      Effort: Low.
