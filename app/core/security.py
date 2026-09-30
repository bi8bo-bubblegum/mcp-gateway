import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

TOKEN_PREFIX = "gw_"
TOKEN_DISPLAY_LENGTH = 12
# 对外分发的 AI Key 前缀：与 MCP 令牌区分开，客户端 base_url + ai_xxx 接入
AI_KEY_PREFIX = "ai_"
_HMAC_PURPOSE = b"gateway-token"
_FERNET_PURPOSE = b"gateway-secret-box"


def generate_opaque_token() -> str:
    """Create a high-entropy bearer token shown to the admin exactly once."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def generate_ai_key() -> str:
    """生成对外分发的 AI Key，明文只在创建时返回一次（库里只存 HMAC 哈希）。"""
    return AI_KEY_PREFIX + secrets.token_urlsafe(32)


def token_display_prefix(token: str) -> str:
    return token[:TOKEN_DISPLAY_LENGTH]


class TokenHasher:
    """HMAC-SHA256 for tokens and audit values. Raw secrets are never stored."""

    def __init__(self, secret_key: str) -> None:
        self._key = hmac.new(
            secret_key.encode("utf-8"), _HMAC_PURPOSE, hashlib.sha256
        ).digest()

    def hash_token(self, token: str) -> str:
        return hmac.new(self._key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def fingerprint(self, value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()


class SecretBox:
    """Reversible encryption for upstream credentials at rest."""

    def __init__(self, secret_key: str) -> None:
        derived = hmac.new(
            secret_key.encode("utf-8"), _FERNET_PURPOSE, hashlib.sha256
        ).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt(self, ciphertext: str) -> dict[str, Any]:
        try:
            raw = self._fernet.decrypt(ciphertext.encode("utf-8"))
        except InvalidToken as error:
            raise ValueError(
                "upstream credentials cannot be decrypted; GATEWAY_SECRET_KEY changed?"
            ) from error
        return json.loads(raw.decode("utf-8"))