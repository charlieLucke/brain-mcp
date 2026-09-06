"""Tests for the GitHub allowlist verifier.

GitHub's half of the exchange is stubbed out on purpose. What is under test is not
whether GitHub can validate a token — it can — but what this server does with the
answer. The stub stands in for a token GitHub has already accepted, which is exactly
the position anyone with any GitHub account is in.

The refusals matter more than the admission. The allowlist is the only thing between
"authenticated GitHub user" and "reads my whole vault", and it is checked inside
`verify_token`, which the auth layer calls on **every** request. That per-request
property is what these tests pin down: homebase, which copied this pattern but issues
its own session cookie, checked the allowlist once at login and let a revoked name
keep working until the cookie expired. Nothing here may drift that way.

Driven with `anyio.run` rather than pytest-asyncio: `verify_token` is async, anyio is
already a dependency, and a test framework is not worth adding for four coroutines.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio
import pytest
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubTokenVerifier

from brain_mcp.auth import GitHubAllowlistVerifier

ALLOWED = {"charlielucke"}


def token_with(claims: dict[str, Any]) -> AccessToken:
    """An access token GitHub has already accepted, carrying the given claims."""
    return AccessToken(token="gho_stub", client_id="Iv1.abc123", scopes=["user"], claims=claims)


@pytest.fixture
def github_says(monkeypatch: pytest.MonkeyPatch) -> Callable[[AccessToken | None], None]:
    """Fix what GitHub's own verification returns, so only the allowlist is under test."""

    def answer(result: AccessToken | None) -> None:
        async def verify_token(self: GitHubTokenVerifier, token: str) -> AccessToken | None:
            return result

        monkeypatch.setattr(GitHubTokenVerifier, "verify_token", verify_token)

    return answer


def verify() -> AccessToken | None:
    """Run the verifier once against whatever GitHub was made to answer."""
    verifier = GitHubAllowlistVerifier(allowed_logins=set(ALLOWED))
    return anyio.run(verifier.verify_token, "gho_stub")


# --- who gets in ---------------------------------------------------------------------


def test_a_listed_login_is_admitted(github_says: Callable[[AccessToken | None], None]) -> None:
    github_says(token_with({"login": "charlielucke"}))
    assert verify() is not None


def test_the_comparison_ignores_case(github_says: Callable[[AccessToken | None], None]) -> None:
    """GitHub reports the login as the person typed it; the allowlist must not care."""
    github_says(token_with({"login": "CharlieLucke"}))
    assert verify() is not None


# --- who does not --------------------------------------------------------------------


def test_an_unlisted_login_is_refused(github_says: Callable[[AccessToken | None], None]) -> None:
    """The case the allowlist exists for: a real GitHub account that is not mine."""
    github_says(token_with({"login": "somebody-else"}))
    assert verify() is None


def test_a_token_github_rejects_stays_rejected(
    github_says: Callable[[AccessToken | None], None],
) -> None:
    github_says(None)
    assert verify() is None


def test_a_token_with_no_login_claim_is_refused(
    github_says: Callable[[AccessToken | None], None],
) -> None:
    """A missing claim must not read as an empty login that slips past a weak check."""
    github_says(token_with({}))
    assert verify() is None


def test_a_non_string_login_claim_is_refused(
    github_says: Callable[[AccessToken | None], None],
) -> None:
    github_says(token_with({"login": ["charlielucke"]}))
    assert verify() is None


# --- the allowlist itself ------------------------------------------------------------


def test_an_empty_allowlist_is_refused_at_construction() -> None:
    """It would refuse everyone — safe, and indistinguishable from an outage.

    `_build_auth` checks the raw BRAIN_GITHUB_ALLOWED_LOGINS string, which `","`
    satisfies while parsing to nothing at all.
    """
    with pytest.raises(RuntimeError, match="empty allowlist"):
        GitHubAllowlistVerifier(allowed_logins=set())
