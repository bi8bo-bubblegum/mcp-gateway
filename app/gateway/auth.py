from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from app.services.token_service import TokenService

CLAIM_TOKEN_ID = "gateway_token_id"
CLAIM_TOKEN_NAME = "gateway_token_name"

class GatewayTokenVerifier(TokenVerifier):
    def __init__(self, tokens: TokenService) -> None:
        super().__init__()
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        snapshot = await self._tokens.verify(token)
        if snapshot is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"gateway-token:{snapshot.id}",
            scopes=[],
            expires_at=None,
            subject=None,
            claims={
                CLAIM_TOKEN_ID: snapshot.id,
                CLAIM_TOKEN_NAME: snapshot.name,
            },
        )

def current_token_claims() -> tuple[int | None, str | None]:
    access = get_access_token()
    if access is None or not access.claims:
        return None, None
    raw_id = access.claims.get(CLAIM_TOKEN_ID)
    raw_name = access.claims.get(CLAIM_TOKEN_NAME)
    token_id = int(raw_id) if raw_id is not None else None
    token_name = str(raw_name) if raw_name is not None else None
    return token_id, token_name