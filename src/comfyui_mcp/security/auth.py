"""Static bearer-token authentication for the Streamable HTTP transport.

The token values live in the environment — ``transport.remote.auth.tokens``
maps an identity label to the name of the environment variable that holds that
identity's token. Resolving at startup keeps secrets out of the YAML and lets a
container inject them the usual way.

This is deliberately a single-process static verifier: no OAuth server, no
token minting, no refresh. For OIDC/JWT deployments, terminate auth at the
reverse proxy (which is the recommended topology) or swap in a FastMCP
``JWTVerifier`` provider.
"""

from __future__ import annotations

import hmac
import os

from fastmcp.server.auth import AccessToken, TokenVerifier


def resolve_bearer_tokens(identity_envs: dict[str, str]) -> dict[str, str]:
    """Map ``token -> identity`` from ``identity -> env var name``.

    Unset or empty environment variables are skipped, so a deployment can roll
    a token out without inventing a placeholder secret.
    """
    resolved: dict[str, str] = {}
    for identity, env_name in identity_envs.items():
        token = os.environ.get(env_name, "").strip()
        if token:
            resolved[token] = identity
    return resolved


class StaticBearerAuth(TokenVerifier):
    """Verify opaque bearer tokens against a static ``token -> identity`` map.

    The client id on the returned ``AccessToken`` is the configured identity
    label, never the token itself, so it is safe to put in audit records.
    """

    def __init__(self, tokens: dict[str, str]) -> None:
        super().__init__()
        self._tokens = dict(tokens)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return access info for a known token, or ``None``."""
        for expected, identity in self._tokens.items():
            if hmac.compare_digest(token, expected):
                return AccessToken(token=token, client_id=identity, scopes=[])
        return None
