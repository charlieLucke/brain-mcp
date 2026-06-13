# Decisions Log

> Architecture Decision Records. Append-only. One entry per significant decision.
> This prevents re-litigating the same questions in every new AI session.

---

## 2026-05-13: Schemas as a local copy (not imported from titan)

**Decision:** `brain_mcp/schemas.py` holds a local copy of the Titan API schemas,
not an import from the `titan` package.
**Reasoning:** brain-mcp should be decoupled from titan — connected only over the HTTP
interface. A cross-repo import (`brain_mcp` importing `titan`) would pull titan in as a
Python dependency and keep both repos in lock-step.
**Alternatives considered:** A shared `titan-schemas` package (a third repo) — too much
overhead for seven schemas.
**Consequences:** On API changes, sync both sides manually. If the schemas start to
diverge significantly: extract `titan-schemas` at that point.

## 2026-05-13: brain-mcp does not run as a daemon (per-session stdio)

**Decision:** brain-mcp is launched by Claude Desktop as a subprocess (stdio transport),
not a systemd service.
**Reasoning:** The MCP stdio transport is per-session — Claude Desktop manages the
lifecycle. A systemd daemon would be wrong here, since MCP doesn't need to listen
permanently.
**Consequences:** `deploy/` contains only `brain-watcher.service`. brain-mcp has no
systemd unit. Deployment = binary in `.venv/bin/brain-mcp` + a JSON entry in Claude Desktop.

## 2026-05-13: Wants= instead of Requires= in the systemd unit

**Decision:** `brain-watcher.service` uses `Wants=titan-service.service`, not `Requires=`.
**Reasoning:** With `Requires=`, brain-watcher would be killed along with a Titan restart.
The watcher's reconnect logic makes `Wants=` safe: the watcher waits with exponential
backoff until Titan is reachable again.
**Consequences:** The watcher survives Titan restarts. The watcher also survives if Titan
isn't running at all at watcher start (events stay in the pending dict until Titan returns).

## 2026-05-13: use_decompose=False as the MCP default

**Decision:** `query_knowledge` passes `use_decompose=False` to titan.search.
**Reasoning:** As described in plan section 7: Claude (Opus/Sonnet) can do query
decomposition itself. Phi-4 decompose in the service would be duplicate effort and extra
latency.
**Consequences:** The CLI path (`python -m titan.search`) still uses `use_decompose=True`
as its default. Only the MCP path sets False.

## 2026-05-13: Cool-down instead of per-call backoff in _ensure_titan_available

**Decision:** `_ensure_titan_available` makes exactly one health() probe per call.
On failure a 30-second cool-down is set as `self._titan_dead_until`; during the cool-down
all further calls return immediately with `False`.
**Reasoning:** Audit B-CRIT-2: the old backoff (1+2+4+8+16 = 31 s per call) blocked the
worker thread for minutes when several events were pending and Titan was down. Also, any
unexpected error (e.g. ValidationError on a degraded response) wasn't caught — watcher crash.
**Consequences:** The worker isn't blocked during the cool-down. Events keep landing in
`_pending` and are processed normally once the cool-down expires.

## 2026-05-13: Failed-delete queue (_pending_deletes)

**Decision:** If Titan is down on a delete event, the path moves into
`self._pending_deletes`. The worker loop processes the queue on every tick — as soon as
Titan is reachable again.
**Reasoning:** Audit B-MED-3: without a queue, delete events were lost when Titan was
restarting. The index drifted from the filesystem (deleted notes stayed indexed).
**Consequences:** Deletes are delayed by at most one cool-down cycle (30s). On a long Titan
outage they stay in the queue and are worked off after recovery.

## 2026-05-13: Debounce seconds as an injectable setting

**Decision:** `VaultWatcher.__init__` accepts `debounce_seconds: float` as a parameter.
`config.py` exposes `BRAIN_DEBOUNCE_SECONDS` (default 30.0).
**Reasoning:** Tests need a 0.1s debounce so they finish in <2s. Production uses 30s.
No `time.sleep(35)` in tests (was a Sonnet finding from plan v1).
**Consequences:** E2E fixtures can set `debounce_seconds=0.1`. The systemd unit sets
`BRAIN_DEBOUNCE_SECONDS=30` via Environment.

## 2026-05-16: brain-mcp as an HTTP daemon; Claude integration via Funnel + auth (open)

**Decision:** brain-mcp can run as a persistent Streamable-HTTP server via
`BRAIN_MCP_TRANSPORT=http` (the default stays `stdio`). The new systemd user service
`deploy/brain-mcp.service` runs it as a pure HTTP server on `127.0.0.1:9100`.
For the Claude integration, **Tailscale Funnel + an auth layer (OAuth)** is planned —
but as of 2026-05-16 that part is **not yet implemented** (deferred).
**Reasoning:** The installed Claude Desktop build (internal "epitaxy"/Cowork build) has no
Developer Mode and treats `claude_desktop_config.json` purely as a preferences file — a
manually added `mcpServers` block is ignored and removed again the next time the app saves.
So the classic stdio path (decision 2026-05-13) isn't usable with this build; the only
remaining path is a *custom connector*. Per the Anthropic docs, Claude connects a custom
connector **server-side from the Anthropic cloud** (true for claude.ai, Desktop, Cowork,
Mobile) — so the MCP endpoint must be **publicly reachable from the internet**. A purely
local or tailnet-private solution fundamentally cannot work.
**Alternatives considered:**
- stdio via `claude_desktop_config.json` — not supported by this build (see above).
- `tailscale serve` (tailnet-private, valid HTTPS cert) — tested, does NOT work:
  Anthropic's cloud isn't in the tailnet, not a single request reached the server.
  Removed again (`tailscale serve --https=443 off`).
- Packaging as an `.mcpb` extension — the bundle would have to call `wsl.exe` (server lives
  in WSL, Claude Desktop on Windows); cumbersome and fragile.
- brain-mcp in Claude Code's MCP config (local, safe, no exposure) — only available in
  Claude Code sessions, not in normal Claude Desktop chat. Remains a possible fallback.
**Consequences:**
- This decision **supersedes** the 2026-05-13 decision ("brain-mcp does not run as a
  daemon"). stdio stays as the default (other MCP clients, local tests), but for the Claude
  integration brain-mcp runs as a daemon.
- `deploy/` now contains two units: `brain-watcher.service` and `brain-mcp.service`.
- `config.py` has new settings: `mcp_transport`, `mcp_host`, `mcp_port`
  (env: `BRAIN_MCP_TRANSPORT` / `BRAIN_MCP_HOST` / `BRAIN_MCP_PORT`).
- **Open / TODO before putting the connector into operation:**
  1. Build an auth layer (OAuth) into brain-mcp — a publicly reachable, unauthenticated
     vault server must NOT go on the internet.
  2. Only then enable `tailscale funnel` for `127.0.0.1:9100`.
  3. Add the connector in Claude Desktop with the Funnel URL.
  4. Update `deploy/README.md` (Claude Desktop section) to this path.
- Windows↔WSL reachability (for local tests / `tailscale` on Windows → `localhost` in WSL)
  goes through WSL2 mirrored networking — see titan `docs/ai/DECISIONS.md` (2026-05-16).

## 2026-05-16: OAuth auth implemented — GitHub proxy with allowlist, connector live

**Decision:** The Claude integration left open in the previous decision is implemented.
brain-mcp uses a GitHub OAuth proxy (`fastmcp` `OAuthProxy` with GitHub endpoints) and a
custom token verifier `GitHubAllowlistVerifier` (`src/brain_mcp/auth.py`) that only admits
GitHub logins from an allowlist. The server runs publicly behind `tailscale funnel`; in
Claude it is wired in as the custom connector `https://<your-tailnet-host>.ts.net/mcp`.
**Reasoning:** Claude connects custom connectors server-side → a public endpoint is needed
(Funnel). A public, unauthenticated vault server is unacceptable → OAuth. But GitHub OAuth
authenticates *any* GitHub account; since the vault is personal, the allowlist verifier
restricts it to the owner and rejects everyone else already at the auth layer (401).
**Alternatives considered:**
- No user filter (GitHub login only) — rejected: any GitHub account would get in.
- Allowlist via middleware / per-tool check — rejected: the token verifier rejects earlier
  (before every tool call) and is the clean place.
**Consequences:**
- New module `src/brain_mcp/auth.py`. New settings in `config.py`: `mcp_auth`,
  `mcp_base_url`, `github_client_id`, `github_client_secret`, `github_allowed_logins`.
- Secrets live in `brain-mcp/.env` (gitignored), not in the repo. `.env.example` documents
  the variables.
- Auth applies only in HTTP transport; stdio stays local/unauthenticated.
- Operational prerequisites: `tailscale funnel` active (persistent), a GitHub OAuth app
  with callback `https://<your-tailnet-host>.ts.net/auth/callback`, an intact
  WSL2 mirrored-networking bridge (otherwise 502 Bad Gateway at the Funnel; fix:
  `wsl --shutdown` + restart).
- End-to-end verified: `query_knowledge` from Claude returns vault hits.

## 2026-05-16: systemd units `linked` instead of `enabled` (autostart off)

**Decision:** `titan-service`, `brain-mcp` and `brain-watcher` are registered as systemd
user units with `linked`, **not** `enabled`. Start and stop go through the desktop script
`RAG-System.bat`.
**Reasoning:** With `enable`, the services start automatically on every WSL boot. Since any
`wsl` command (e.g. a status query) already boots WSL, a "stop" would immediately be undone
— the services would come back on their own and consume GPU VRAM/RAM. With `linked` they
stay off after a stop until they're started explicitly.
**Consequences:**
- After a Windows restart the system doesn't run on its own — `RAG-System.bat` → "Start"
  brings it up (as intended).
- `systemctl --user link <path>` registers the unit without autostart; `start` / `restart`
  work normally.
- Caution: for units symlinked into the repo, `systemctl --user disable` also removes the
  unit symlink itself — afterwards run `systemctl --user link` again.
- `deploy/README.md` section 1 uses `link` instead of `enable` accordingly.

## 2026-05-17: vault-admin as tools in brain-mcp (not a separate MCP server)

**Decision:** The vault-admin tools `list_notes` and `delete_note` are added as additional
tools in the existing `brain` server — not a separate `vault-admin` MCP server.
**Reasoning:** A separate MCP server would need a second custom connector in Claude with its
own OAuth setup and Funnel. The tools belong thematically with the existing vault tools; they
share `TitanClient`, config and auth.
**Alternatives considered:** A dedicated `vault-admin` server — rejected (overhead, second
connector, second OAuth).
**Consequences:** The `brain` server now has 6 tools. `delete_note` is purely de-indexing —
it only removes the chunks from the index, the `.md` file on disk stays untouched.
`list_notes` needs the new titan endpoint `GET /notes` (see titan `docs/ai/DECISIONS.md`,
2026-05-17).

## 2026-05-22: Connector outage was infrastructure, not OAuth — linger + 0.0.0.0 bind

**Decision:** Two operational fixes so the custom connector connects reliably:
(1) `loginctl enable-linger charl`, (2) `BRAIN_MCP_HOST=0.0.0.0` in
`deploy/brain-mcp.service` (was `127.0.0.1`).
**Reasoning:** The connector failed with "couldn't reach" / `start_error`, even though the
OAuth code was correct (tested locally: `/mcp`→401, discovery→200, `POST /register`→201).
Two infrastructure causes, both triggered by a PC restart:
- **Linger=no:** without linger, WSL terminates the systemd user instance once no session is
  open → brain-mcp (and the whole stack) dies when idle → the Funnel points at nothing.
  Explains "worked before, suddenly didn't".
- **`127.0.0.1` bind:** under WSL2 mirrored networking a loopback-only service is unreachable
  from Windows; the Funnel (on Windows) got **502**. Proof: the dashboard (`0.0.0.0:9200`)
  was reachable from Windows with 200, brain-mcp (`127.0.0.1:9100`) not at all. After
  switching to `0.0.0.0` → Funnel 401.
**Alternatives considered:** fastmcp upgrade 3.2.4→3.3.1 (no effect, not the cause; back to
lock-consistent 3.3.1). Dual-stack `::` bind (counterproductive under mirrored mode per
titan/dashboard experience) — rejected.
**Consequences:**
- Linger is persistent (survives reboots). Compatible with "`linked` instead of `enabled`":
  stopped services stay stopped (gaming workflow intact), only running ones no longer die
  when idle.
- brain-mcp is reachable over `0.0.0.0`; access is still gated by GitHub OAuth. The 502 note
  of the 2026-05-16 decision is thereby refined (the most common 502 cause = wrong bind, not
  the mirrored bridge).
- `BRAIN_GITHUB_ALLOWED_LOGINS` was updated to `charlieLucke` in the course of the GitHub
  rename (in `.env`, gitignored).
