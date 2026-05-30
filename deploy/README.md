# brain-mcp — Deployment

## Prerequisites

- WSL2 with systemd (`/etc/wsl.conf` contains `[boot]` / `systemd=true`)
- The Titan service deployed and running as `titan-service.service`
- Docker Desktop running (the Qdrant container) — otherwise `titan-service` won't start
- Tailscale on the Windows host, with Funnel enabled for the node
- A GitHub OAuth app (for connector authentication, see section 2)

---

## 1. systemd user services (WSL)

brain-mcp consists of two services:

- `brain-watcher` — watches the vault and ingests changed notes into Titan
- `brain-mcp` — serves the MCP tools over HTTP on `0.0.0.0:9100`

> **Bind address `0.0.0.0`, not `127.0.0.1`:** under WSL2 mirrored networking a
> loopback-only service is **unreachable from Windows** — and the Tailscale Funnel
> runs on Windows. With `127.0.0.1` the Funnel therefore returns **502 Bad
> Gateway**. Access stays protected by GitHub OAuth. Set via
> `BRAIN_MCP_HOST=0.0.0.0` in `deploy/brain-mcp.service`.

The units are registered as `linked` — **not** `enabled`. They therefore do **not**
start automatically at WSL boot; they are started and stopped deliberately via the
desktop script `RAG-System.bat`. This lets you free up resources (above all GPU
VRAM) when the system isn't needed.

```bash
systemctl --user link ~/projects/brain-mcp/deploy/brain-watcher.service
systemctl --user link ~/projects/brain-mcp/deploy/brain-mcp.service
systemctl --user daemon-reload
systemctl --user start brain-watcher brain-mcp
systemctl --user status brain-watcher brain-mcp
```

> `titan-service` is registered as `linked` the same way. `systemctl --user enable`
> would turn on autostart — then the services would come back up on their own after
> every WSL boot, even after a "stop". Hence `link` instead of `enable` on purpose.

### Enable linger (required)

```bash
loginctl enable-linger charl
```

Without linger, WSL terminates the systemd user instance (and with it **all**
running user services) as soon as the last WSL session ends / the distro shuts down
when idle. Result: brain-mcp dies unnoticed, the Funnel points at nothing, and the
Claude connector fails with "couldn't reach" / `start_error`. With linger the user
instance stays active permanently.

Important — no contradiction with "`linked` instead of `enabled`": linger only
starts **enabled** units at boot. Since `titan-service` / `brain-mcp` /
`brain-watcher` are `linked` (not enabled), they do **not** start automatically — a
"stop" for gaming stays in effect. Linger only keeps *already running* services
alive instead of killing them when idle.

---

## 2. Auth configuration (`.env`)

The server is exposed publicly and therefore needs OAuth. The configuration lives
in `~/projects/brain-mcp/.env` (gitignored — never commit it):

```
BRAIN_MCP_AUTH=github
BRAIN_MCP_BASE_URL=https://charliespc.taild04050.ts.net
BRAIN_GITHUB_CLIENT_ID=Ov23li...
BRAIN_GITHUB_CLIENT_SECRET=...
BRAIN_GITHUB_ALLOWED_LOGINS=your-github-login
```

Create a GitHub OAuth app (https://github.com/settings/developers → OAuth Apps →
New OAuth App):

- **Homepage URL:** `https://charliespc.taild04050.ts.net`
- **Authorization callback URL:** `https://charliespc.taild04050.ts.net/auth/callback`

Only GitHub logins listed in `BRAIN_GITHUB_ALLOWED_LOGINS` are allowed; everyone
else is rejected with a 401 already at the auth layer.

---

## 3. Make it publicly reachable — Tailscale Funnel

Claude connects custom connectors server-side from the Anthropic cloud, so the
endpoint must be publicly reachable. On the **Windows host**:

```powershell
tailscale funnel --bg http://localhost:9100
tailscale funnel status
```

This proxies `https://charliespc.taild04050.ts.net/` → `http://localhost:9100`.

**502 Bad Gateway at the Funnel?** Most common cause: brain-mcp is bound to
`127.0.0.1` instead of `0.0.0.0` (see section 1) — then it isn't reachable from
Windows / the Funnel. Check: from Windows `iwr http://127.0.0.1:9100/mcp` → must
return `401`. If that fails, the bind is wrong (or the service is down). Less
common: a degraded WSL2 mirrored bridge (WSL has only `lo`, no `ethX`) — fix:
`wsl --shutdown`, then restart WSL.

---

## 4. Add the connector in Claude Desktop

Settings → Connectors → "Add custom connector":

- **URL:** `https://charliespc.taild04050.ts.net/mcp`

Claude starts the OAuth flow → GitHub login (with the allowed account) → done.
Afterwards the six tools `query_knowledge`, `find_related`, `list_domains`,
`list_notes`, `ingest_note`, and `delete_note` are available.

---

## 5. Smoke test

```bash
# Are the services running?
systemctl --user status brain-watcher brain-mcp

# Is Titan reachable?
curl localhost:8765/health

# brain-mcp locally — is OAuth discovery reachable (expected: 200)?
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:9100/.well-known/oauth-protected-resource/mcp

# /mcp without a token — expected: 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  http://127.0.0.1:9100/mcp
```
