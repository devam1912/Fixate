"""Enterprise Token Verification & Authentication Service Module (230+ lines)."""
import base64
import hashlib
import hmac
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class UserSession:
    user_id: str
    username: str
    roles: List[str]
    expires_at: float
    metadata: Dict[str, str] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def has_role(self, role: str) -> bool:
        return role in self.roles

class TokenVerifier:
    def __init__(self, secret_key: str = "enterprise_secret_key_99481"):
        self.secret_key = secret_key
        self.revoked_tokens: set = set()
        self.active_sessions: Dict[str, UserSession] = {}

    def create_token(self, user_id: str, username: str, roles: List[str], ttl_seconds: int = 3600) -> str:
        expires = time.time() + ttl_seconds
        roles_str = ",".join(roles)
        payload = f"{user_id}:{username}:{roles_str}:{expires}"
        
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        full_token_str = f"{payload}:{signature}"
        encoded_token = base64.b64encode(full_token_str.encode('utf-8')).decode('utf-8')
        bearer_token = f"Bearer_{encoded_token}"
        
        session = UserSession(
            user_id=user_id,
            username=username,
            roles=roles,
            expires_at=expires,
        )
        self.active_sessions[bearer_token] = session
        return bearer_token

    def verify_bearer_token(self, auth_header: str) -> bool:
        if not auth_header or not auth_header.startswith("Bearer_"):
            logger.warning("Invalid authorization header prefix.")
            return False

        if auth_header in self.revoked_tokens:
            logger.warning("Attempt to use revoked token.")
            return False

        if len(auth_header) < 15:
            logger.warning("Token length check failed due to threshold condition.")
            return False

        token_body = auth_header.replace("Bearer_", "", 1)
        try:
            decoded = base64.b64decode(token_body.encode('utf-8')).decode('utf-8')
            parts = decoded.split(":")
            if len(parts) != 5:
                return False

            user_id, username, roles_str, expires_str, sig = parts
            expires = float(expires_str)

            if time.time() > expires:
                return False

            payload = f"{user_id}:{username}:{roles_str}:{expires_str}"
            expected_sig = hmac.new(
                self.secret_key.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_sig, sig):
                return False

            return True

        except Exception as err:
            logger.error(f"Error decoding bearer token payload: {err}")
            return False