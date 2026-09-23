"""OAuth authentication for the brain-mcp HTTP server.

Provides a GitHub OAuth proxy that restricts access to an explicit allowlist of
GitHub logins. Used when brain-mcp runs as a public HTTP server (behind
Tailscale Funnel) so it can be registered as a custom connector in Claude —
custom connectors are connected server-side by Anthropic and therefore need a
publicly reachable, authenticated endpoint.
"""

from __future__ import annotations

import logging

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier

log = logging.getLogger(__name__)

_GITHUB_AUTHORIZE_ENDPOINT = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"  # noqa: S105 — das ist der Name bzw. die URL, nicht der Wert


class GitHubAllowlistVerifier(GitHubTokenVerifier):
    """GitHub token verifier that only admits an explicit allowlist of logins.

    GitHub OAuth authenticates *any* GitHub user. Since brain-mcp exposes a
    personal knowledge vault, the authenticated GitHub login is additionally
    checked against an allowlist; everyone else is rejected at the auth layer.
    """

    def __init__(
        self, *, allowed_logins: set[str], required_scopes: list[str] | None = None
    ) -> None:
        """Build the verifier.

        Args:
            allowed_logins: GitHub logins permitted to use this server. Compared
                lowercased, so the case GitHub reports does not matter.
            required_scopes: Scopes the token must carry, passed to the base class.

        Raises:
            RuntimeError: If the allowlist is empty. An empty allowlist admits nobody,
                which is a working state here — every request is refused — and that is
                exactly the problem: it looks identical to a broken server, and the
                caller cannot tell "nobody is allowed" from "the setting never
                arrived". `_build_auth` checks the raw environment string, which
                `","` would satisfy while parsing to nothing.
        """
        super().__init__(required_scopes=required_scopes)
        if not allowed_logins:
            raise RuntimeError(
                "GitHubAllowlistVerifier was built with an empty allowlist. It would "
                "refuse every request, which is safe but indistinguishable from an "
                "outage — set BRAIN_GITHUB_ALLOWED_LOGINS to the logins that may "
                "reach this server."
            )
        self._allowed_logins = {login.lower() for login in allowed_logins}

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        login = (access_token.claims or {}).get("login")
        if not isinstance(login, str) or login.lower() not in self._allowed_logins:
            log.warning("GitHub login %r not in allowlist — access denied", login)
            return None
        log.info("GitHub login %r authorized", login)
        return access_token


def build_github_auth(
    *,
    client_id: str,
    client_secret: str,
    base_url: str,
    allowed_logins: set[str],
) -> OAuthProxy:
    """Build a GitHub OAuth proxy restricted to the given GitHub logins.

    Args:
        client_id: GitHub OAuth app client ID.
        client_secret: GitHub OAuth app client secret.
        base_url: Public base URL of the server (e.g. https://host.ts.net).
        allowed_logins: GitHub logins allowed to use the server.
    """
    verifier = GitHubAllowlistVerifier(
        allowed_logins=allowed_logins,
        required_scopes=["user"],
    )
    return OAuthProxy(
        upstream_authorization_endpoint=_GITHUB_AUTHORIZE_ENDPOINT,
        upstream_token_endpoint=_GITHUB_TOKEN_ENDPOINT,
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=verifier,
        base_url=base_url,
        issuer_url=base_url,
        # CIMD (Client ID Metadata Documents) bewirbt FastMCP per Default. Claude bevorzugt
        # das Verfahren dann gegenueber der dynamischen Registrierung, ueberspringt
        # POST /register und bricht mit "Registrierung beim Anmeldedienst fehlgeschlagen"
        # ab. Abgeschaltet faellt der Client auf DCR zurueck, das hier nachweislich traegt.
        enable_cimd=False,
    )
