# brain_mcp

MCP server and vault watcher that make my Obsidian notes searchable by Claude

## Quick activation

Two systemd user services run in WSL; Claude reaches the MCP server as a
custom connector. Full instructions: **`deploy/README.md`**.

**Services (WSL systemd)**

```bash
mkdir -p ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-watcher.service ~/.config/systemd/user/
ln -sf ~/projects/brain-mcp/deploy/brain-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now brain-watcher brain-mcp
```

- `brain-watcher` — watches the Obsidian vault and ingests changed notes into Titan.
- `brain-mcp` — serves the MCP tools over Streamable-HTTP. In deployment it binds
  `0.0.0.0:9100` (not `127.0.0.1`) so the Windows-side Tailscale Funnel can reach
  it under WSL2 mirrored networking; see `deploy/README.md`.

**Claude integration**

Custom connectors are connected server-side by Anthropic, so the MCP endpoint must
be publicly reachable and authenticated. brain-mcp is exposed via Tailscale Funnel
and protected by a GitHub OAuth proxy with a login allowlist. See `deploy/README.md`
for the connector URL, the GitHub OAuth app, and the `.env` auth variables.

## MCP tools

The server exposes six tools, all backed by the Titan RAG service:

| Tool | Purpose |
|---|---|
| `query_knowledge` | Search the vault in natural language (optional `domain` filter, `top_k`). |
| `find_related` | Find notes semantically related to a given note. |
| `list_domains` | List all domains in the index with their chunk counts. |
| `list_notes` | List every indexed note (optional `domain` filter) with domain + chunk count. |
| `ingest_note` | Re-index a note immediately, bypassing the watcher's delay (replaces old chunks). |
| `delete_note` | De-index a note (removes its chunks; the Markdown file on disk is untouched). |

---

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
make install
```

This installs all dependencies and registers pre-commit hooks.

## Development

```bash
make run        # run the server locally (python -m brain_mcp)
make test       # run tests with coverage
make test-fast  # run only fast tests (skip slow + integration)
make check      # full quality gate: lint + types + tests
make format     # auto-fix style issues
make help       # list all available commands
```

## Project Structure

```
src/brain_mcp/    Source code
tests/               Pytest tests (mirrors src/ layout)
docs/ai/             AI agent context and plans
.github/workflows/   CI configuration
```

## Tooling

| Tool         | Purpose                              |
|--------------|--------------------------------------|
| **uv**       | Package manager + Python installer   |
| **ruff**     | Linter + formatter                   |
| **mypy**     | Static type checker (strict mode)    |
| **pytest**   | Test runner with coverage            |
| **pre-commit** | Git hook runner                    |

All tools run in CI on every push.

## Working with AI Tools

This project uses a structured workflow for AI-assisted coding. Any AI agent (Claude, Gemini, Cursor, Aider, etc.) should read `CLAUDE.md` first — it's mirrored as `AGENTS.md` and `GEMINI.md` for tool compatibility.

Key files for AI context:

- `docs/ai/CONTEXT.md` — stack, conventions, glossary
- `docs/ai/CURRENT_TASK.md` — what's actively being worked on
- `docs/ai/HANDOFF.md` — state for resuming sessions across model switches
- `docs/ai/DECISIONS.md` — log of architectural decisions
- `docs/ai/plans/` — saved plans authored by a planning model (e.g. Opus)

The intended workflow:

1. Architecture and feature plans are authored by a strong reasoning model and saved to `docs/ai/plans/`
2. A faster/cheaper model implements the plans
3. Both reference the shared context in `docs/ai/`
4. State is preserved across sessions via `HANDOFF.md`

## License

TBD
