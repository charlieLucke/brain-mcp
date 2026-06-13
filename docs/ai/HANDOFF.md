# Handoff – 2026-05-22
Model: Claude Opus 4.7

## Done in this session

**Connector outage fixed — the cause was infrastructure, not the OAuth code.**
After a PC restart the custom connector failed with "couldn't reach" / `start_error`.
OAuth code verified locally (`/mcp`→401, discovery→200, `POST /register`→201).
Found and fixed two real causes:

1. **`Linger=no`** → systemd user services die as soon as WSL goes idle → brain-mcp
   gone → Funnel points at nothing. Fix: `loginctl enable-linger charl` (persistent).
2. **`BRAIN_MCP_HOST=127.0.0.1`** → under WSL2 mirrored networking, unreachable from
   Windows/Funnel (502). Fix: `BRAIN_MCP_HOST=0.0.0.0` in `deploy/brain-mcp.service`.
   Proof: dashboard (`0.0.0.0:9200`) from Windows = 200, brain-mcp (`127.0.0.1:9100`)
   = unreachable; after `0.0.0.0` → Funnel 401.

Also: updated `BRAIN_GITHUB_ALLOWED_LOGINS` to `charlieLucke` (GitHub rename), rolled
fastmcp back to 3.2.4 as a test and back to lock-consistent 3.3.1 (not the cause).
Docs updated (deploy/README, DECISIONS, CONTEXT, this handoff). **End-to-end verified:
the connector connects again, brain tools live.**

## Operational setup (as of today)

- brain-mcp: HTTP on `0.0.0.0:9100`, linger active → services stay running.
- Connector URL unchanged: `https://<your-tailnet-host>.ts.net/mcp`.
- "`linked` instead of `enabled`" still applies — a stop for gaming stays in effect;
  linger just no longer kills services when idle.

## Open / Next steps

- Docker Desktop was off last → qdrant/titan down; for real queries bring the RAG
  stack up (Docker Desktop → qdrant → titan). Optional: Docker autostart.

---

# Handoff – 2026-05-17
Model: Claude Opus 4.7

## Done in this session

**Stage 2 — vault-admin.** Two new MCP tools in the `brain` server (now 6 tools).

**Code changes:**
- `src/brain_mcp/schemas.py` — new schemas `NoteInfo`, `NotesResponse`
- `src/brain_mcp/titan_client.py` — `TitanClient.list_notes()` (GET /notes)
- `src/brain_mcp/mcp_server.py` — new tools `list_notes` (all indexed notes,
  optional domain filter) and `delete_note` (remove a note from the index, de-index
  only — the `.md` file stays); `ingest_note` docstring clarified (re-ingest always
  replaces old chunks)
- `tests/test_titan_client.py`, `tests/test_mcp_tools.py` — tests for both

**Counterpart in the titan repo:** new endpoint `GET /notes` — see titan `docs/ai/`
(2026-05-17).

**Quality status:** `ruff` + `mypy --strict` green, `pytest` 52 passed.

## Operational setup

`titan-service` and `brain-mcp` were restarted — the two new tools are live in the
connector. Otherwise unchanged (see handoff 2026-05-16).

## Context: brain-dashboard

In parallel the new repo `~/projects/brain-dashboard` was created — a web control
panel (port 9200) for status, logs and control of the RAG system. Its own repo with
its own `docs/ai/`. Runs as an `enabled` systemd user unit.

## Open / Next steps

- No open items from stage 2.

---

# Handoff – 2026-05-16
Model: Claude Opus 4.7

## Done in this session

Claude integration of brain-mcp **fully implemented** — OAuth + Tailscale Funnel.
The `brain` connector is live in Claude and verified end-to-end.

**Code changes:**
- `src/brain_mcp/config.py` — settings for HTTP transport (`mcp_transport/host/port`)
  and OAuth (`mcp_auth`, `mcp_base_url`, `github_client_id/secret`,
  `github_allowed_logins`)
- `src/brain_mcp/mcp_server.py` — HTTP transport in `main()`; `_build_auth()` builds
  the OAuth provider when `BRAIN_MCP_AUTH=github` and passes it to `FastMCP(auth=...)`
- `src/brain_mcp/auth.py` (new) — GitHub OAuth proxy with `GitHubAllowlistVerifier`,
  which only admits allowed GitHub logins
- `deploy/brain-mcp.service` — systemd user service (HTTP on `127.0.0.1:9100`)
- `.env.example` — new variables documented

**Quality status:** `ruff` + `mypy` green, `pytest` 38 passed (unit tests).

## Operational setup (running)

- `brain-mcp.service`: HTTP on `127.0.0.1:9100`. The units (`titan-service`,
  `brain-mcp`, `brain-watcher`) are `linked` — **no** autostart. Start/stop go through
  the desktop script `RAG-System.bat` (see DECISIONS.md 2026-05-16).
- Auth: GitHub OAuth proxy, allowlist = `charlieLucke`. Configuration in
  `brain-mcp/.env` (gitignored): `BRAIN_MCP_AUTH=github`, `BRAIN_MCP_BASE_URL`,
  `BRAIN_GITHUB_CLIENT_ID/SECRET`, `BRAIN_GITHUB_ALLOWED_LOGINS`.
- `tailscale funnel` (persistent): `https://<your-tailnet-host>.ts.net/` →
  `http://localhost:9100`. Reset: `tailscale funnel --https=443 off`.
- Claude connector URL: `https://<your-tailnet-host>.ts.net/mcp`.
- GitHub OAuth app: callback `https://<your-tailnet-host>.ts.net/auth/callback`.
- E2E verified: `query_knowledge` from Claude returns vault hits (score 5.71).

## Open / Next steps

- Optional: set Docker Desktop to autostart on Windows (otherwise it isn't running
  after a reboot → Qdrant container missing → titan-service won't start).

## Notes / gotchas

- Service order: Docker Desktop → Qdrant container → `titan-service` → `brain-mcp`
  / `brain-watcher`. If the chain isn't up, the tools return "Titan unreachable".
- **WSL networking:** the Funnel (Windows `tailscaled`) only reaches `localhost:9100`
  with an intact WSL2 mirrored-networking bridge. After a reboot it can be degraded
  (WSL has only `lo`, no `ethX`, no default route) → Funnel returns **502 Bad
  Gateway**. Fix: `wsl --shutdown`, then restart WSL.
- Vault ingest: the watcher only picks up `.md` files from the vault; each note needs
  a frontmatter field `domain:` (otherwise Titan rejects it). PDFs go through the
  Titan CLI (`python -m titan.ingest`), not the watcher.

---

# Handoff – 2026-05-13
Model: Claude Sonnet 4.6

## Done in this session

Phase 2 (B0–B10) fully implemented and committed to `main`.

**New files:**
- `src/brain_mcp/config.py` — Pydantic settings (BRAIN_ prefix)
- `src/brain_mcp/schemas.py` — local copy of the Titan API schemas
- `src/brain_mcp/titan_client.py` — TitanClient (httpx + tenacity)
- `src/brain_mcp/mcp_server.py` — FastMCP + 4 tools
- `src/brain_mcp/watcher.py` — VaultWatcher + reconnect logic
- `deploy/brain-watcher.service` — systemd user service
- `deploy/README.md` — activation guide + Claude Desktop JSON
- `tests/test_titan_client.py` — httpx.MockTransport unit tests
- `tests/test_mcp_tools.py` — MCP tool unit tests (patch)
- `tests/test_watcher.py` — watcher unit + integration tests
- `tests/integration/test_e2e_pipeline.py` — E2E polling tests

**Modified files:**
- `docs/ai/CONTEXT.md`, `CURRENT_TASK.md`, `DECISIONS.md` — filled in
- `pyproject.toml` — entry points, mypy overrides
- `.pre-commit-config.yaml` — mypy additional_dependencies

**Quality status:**
- `ruff check` → 0 errors
- `mypy src tests` → 0 errors (15 files)
- `pytest` → 33 passed, 3 skipped (E2E without Titan)
- pre-commit → all hooks green
- 1 commit on `main`

## In progress

Nothing open — B0–B10 fully committed.

## Next concrete step

1. **B11: audit round (Opus)** — check the checklist from plan section 4.13
2. **Manual activation** (deploy/README.md):
   ```bash
   mkdir -p ~/.config/systemd/user/
   ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now brain-watcher
   systemctl --user status brain-watcher
   ```
3. **Claude Desktop config** (Windows side, manual):
   - edit `%APPDATA%\Claude\claude_desktop_config.json`
   - content see `deploy/README.md` section 2
   - restart Claude Desktop → check the 4 brain tools
4. **E2E test** with a real Titan:
   ```bash
   uv run pytest tests/integration/ -m integration -v
   ```

## Open questions / decisions needed

- **B11 audit:** Opus should check the checklist from plan section 4.13, especially:
  MCP tool descriptions, top_k clamp, watcher exception handling, path validation
- **VAULT_ROOT correct?** Plan and CONTEXT.md say `/mnt/f/vault` — if the vault is
  mounted elsewhere, `BRAIN_VAULT_ROOT` in the systemd unit and Claude Desktop config
  must be adjusted.

## Files the next session must read first

1. `~/projects/titan/docs/ai/plans/plan_titan_brain_v2.md` section 4.13 — audit checklist
2. `docs/ai/CONTEXT.md` — stack and pitfalls
3. `src/brain_mcp/mcp_server.py` — tool implementations
4. `src/brain_mcp/watcher.py` — watcher + reconnect

## Notes / gotchas discovered

- The pre-commit mypy hook needs extra `additional_dependencies` (pydantic, fastmcp,
  httpx, watchdog, tenacity) — without them it sees BaseModel as `Any`
- `@mcp.tool()` and tenacity `@_RETRY` are untyped decorators in mypy 2.0 →
  pyproject.toml `disable_error_code = ["untyped-decorator", "no-any-return"]`
- `watchdog` has no type stubs → `ignore_missing_imports = true`
- A replace_all edit on `# type: ignore[misc]` → `` had a bug: it removed the
  whitespace before `def` → syntax error. In future: don't remove `# type: ignore`
  with replace_all; edit it per line instead.
- VS Code shows "Package not installed" for all brain-mcp deps — the wrong venv
  (mein-projekt) is active in the workspace. Everything works correctly in `.venv`.
```
